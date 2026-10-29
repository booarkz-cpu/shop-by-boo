"""v28.46 CloudPayments: refunds through the API and auto-renew with the saved card token."""
import json
from contextlib import asynccontextmanager
from decimal import Decimal

import pytest
from sqlalchemy import select

from app import main as shop
from app import schedulers
from app.config import settings
from app.gateways import GATEWAYS, cloudpayments as cpm, common, refunders
from app.models import AutoRenewMethod, Payment, Subscription, User
from test_e2e_journeys import _lock
from test_money_review import _renewable, _scheduler_env
from test_subscription_commerce import database  # noqa: F401


class Api:
    def __init__(self, answers):
        self.calls = []
        self.answers = answers

    async def post(self, url, json=None, headers=None):
        self.calls.append({"url": url, "json": json, "headers": headers or {}})
        body = self.answers[next(k for k in self.answers if url.endswith(k))]
        body = body(json) if callable(body) else body
        return type("R", (), {"raise_for_status": lambda self: None, "json": lambda self: body})()


@pytest.fixture
def cp(monkeypatch):
    api = Api({"/payments/find": {"Success": True, "Model": {"TransactionId": 777, "Status": "Completed", "Amount": 199.0, "Currency": "RUB"}},
               "/payments/refund": {"Success": True, "Model": {"TransactionId": 778}},
               "/payments/get": {"Success": True, "Model": {"TransactionId": 777, "Status": "Completed", "Refunded": True}},
               "/payments/tokens/charge": {"Success": True, "Model": {"TransactionId": 900, "Status": "Completed"}}})

    @asynccontextmanager
    async def client(timeout):
        yield api
    monkeypatch.setattr(common, "_public_client", client)
    monkeypatch.setattr(settings, "cloudpayments_public_id", "pk")
    monkeypatch.setattr(settings, "cloudpayments_api_secret", "sec")
    return api


def test_the_table_marks_cloudpayments_refunds_and_recurring():
    g = GATEWAYS["cloudpayments"]
    assert g.refunds and g.recurring and set(refunders()) == {"cloudpayments"}
    assert schedulers.RECURRING_PROVIDERS == ("yookassa", "cloudpayments")


@pytest.mark.asyncio
async def test_refund_finds_the_transaction_and_is_idempotent(cp):
    out = await cpm.CloudPaymentsProvider().refund("order-7", Decimal("199"), "RUB", "Refund for order order-7")
    assert out == {"id": "cp-refund-777", "status": "succeeded"}
    call = cp.calls[-1]
    assert call["url"].endswith("/payments/refund") and call["json"] == {"TransactionId": 777, "Amount": 199.0}
    assert call["headers"]["X-Request-ID"] == "refund-order-7", "a repeated call never refunds twice"
    assert await cpm.CloudPaymentsProvider().get_refund_status("cp-refund-777") == "succeeded"
    cp.answers["/payments/find"] = {"Success": True, "Model": {"TransactionId": 777, "Status": "Declined"}}
    with pytest.raises(cpm.PaymentError):
        await cpm.CloudPaymentsProvider().refund("order-7", Decimal("199"), "RUB")


@pytest.mark.asyncio
async def test_token_charge_success_decline_and_status(cp):
    token = json.dumps({"t": "tk_1", "a": "42"})
    out = await cpm.CloudPaymentsProvider().charge_recurring(Decimal("199"), "auto-renew-42-sub-1-1-20261101", "Auto-renew Basic", token)
    call = cp.calls[-1]
    assert out == {"id": "auto-renew-42-sub-1-1-20261101", "status": "succeeded"}
    assert call["json"]["Token"] == "tk_1" and call["json"]["AccountId"] == "42" and call["json"]["InvoiceId"] == "auto-renew-42-sub-1-1-20261101"
    assert call["headers"]["X-Request-ID"] == "auto-renew-42-sub-1-1-20261101"
    cp.answers["/payments/tokens/charge"] = {"Success": False, "Model": {"TransactionId": 901, "Status": "Declined", "CardHolderMessage": "Недостаточно средств"}}
    declined = await cpm.CloudPaymentsProvider().charge_recurring(Decimal("199"), "auto-renew-42-x", "x", "plain-token")
    assert declined["status"] == "failed" and "средств" in declined["reason"] and cp.calls[-1]["json"]["AccountId"] == "42"
    cp.answers["/payments/find"] = {"Success": True, "Model": {"TransactionId": 901, "Status": "Declined"}}
    assert await cpm.CloudPaymentsProvider().recurring_status("auto-renew-42-x") == "failed"
    assert await cpm.CloudPaymentsProvider().find_by_order_id("auto-renew-42-x") == {"id": "auto-renew-42-x"}


async def _paid(db, order="cp-order-1", purpose="subscription"):
    db.add(Payment(user_id=1, plan_id=1, provider="cloudpayments", order_id=order, provider_payment_id=order, amount=Decimal("100"),
                   original_amount=Decimal("100"), discount_amount=Decimal("0"), currency="RUB", status="paid", fulfillment_status="completed",
                   idempotency_key=order, purpose=purpose, bonus_days=0))
    await db.commit()


@pytest.mark.asyncio
async def test_card_token_is_saved_only_with_auto_renew_and_never_over_a_yookassa_card(database, monkeypatch):  # noqa: F811
    db = database
    monkeypatch.setattr(shop, "encrypt_secret", lambda v: "enc:" + v)
    await _paid(db)
    user = await db.get(User, 1)
    user.auto_renew_enabled = False
    await db.commit()
    assert await cpm.save_renewal_token(db, "cp-order-1", "tk_1", "1") is False, "auto-renew is off"
    user.auto_renew_enabled = True
    await db.commit()
    assert await cpm.save_renewal_token(db, "cp-order-1", "tk_1", "1") is True
    method = await db.scalar(select(AutoRenewMethod))
    assert method.provider == "cloudpayments" and json.loads(method.external_token_encrypted[4:]) == {"t": "tk_1", "a": "1"}
    method.provider = "yookassa"
    await db.commit()
    assert await cpm.save_renewal_token(db, "cp-order-1", "tk_2", "1") is False, "a working YooKassa card stays"
    await _paid(db, "topup-1", "topup")
    assert await cpm.save_renewal_token(db, "topup-1", "tk_3", "1") is False, "a wallet top-up does not switch auto-renew"


@pytest.mark.asyncio
async def test_auto_renew_pass_charges_a_cloudpayments_card(database, monkeypatch):  # noqa: F811
    charges = []
    _scheduler_env(monkeypatch, database, charges)
    monkeypatch.setattr(shop, "_acquire_payment_side_effect_lock", lambda *a, **k: _lock())
    made = []

    async def charge(self, amount, order_id, desc, token):
        made.append((order_id, token))
        return {"id": order_id, "status": "succeeded"}

    async def verified(self, *a, **k):
        return False  # confirmation comes on the next pass
    monkeypatch.setattr(cpm.CloudPaymentsProvider, "charge_recurring", charge)
    monkeypatch.setattr(cpm.CloudPaymentsProvider, "verify_succeeded", verified)
    await _renewable(database)
    method = await database.scalar(select(AutoRenewMethod))
    method.provider = "cloudpayments"
    await database.commit()
    await shop.run_auto_renew_pass(database)
    assert len(made) == 1 and made[0][0].startswith("auto-renew-1-sub-1-") and charges == [], "YooKassa is not charged"
    payment = await database.scalar(select(Payment).where(Payment.order_id == made[0][0]))
    assert payment.provider == "cloudpayments" and payment.status == "pending"
    sub = await database.get(Subscription, 1)
    assert sub.next_renewal_at is not None
