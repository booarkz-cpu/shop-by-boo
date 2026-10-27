"""v44.5.7 logic hardening, checked by running the code (was: code lines searched in main.py and worker.py).

Covered elsewhere: the trial re-enables a disabled panel user (test_integration_billing_vpn.py), the referral
credit reads the payment's snapshot (test_referral_program.py), the extension starts from the later of the
local and the panel expiry (test_money_review.py, test_behaviour_payments.py)."""
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app import main as shop
from app.models import Payment, PaymentProviderHealth, PromoCode, PromoReservation, User
from app_contract import columns, revision, tables
from test_behaviour_payments_v2 import FakeRedis, checkout
from test_subscription_commerce import database  # noqa: F401


class Paid:
    async def create(self, amount, order_id, description, return_url):
        return {"id": f"yk-{order_id}", "url": "https://pay.example/1"}


async def checkout_env(database, monkeypatch):
    async def yes(*a, **k):
        return True

    async def providers(db, requested):
        return ["yookassa"]

    async def risk(*a):
        return 0, "allow", {}
    monkeypatch.setattr(shop, "_risk_score", risk)
    monkeypatch.setattr(shop, "production_payments_allowed", yes)
    monkeypatch.setattr(shop, "e2e_checkout_allowed", yes)
    monkeypatch.setattr(shop, "_payment_provider_order", providers)
    monkeypatch.setattr(shop, "redis_client", FakeRedis())
    monkeypatch.setattr(shop, "YooKassaProvider", Paid)


@pytest.mark.asyncio
async def test_a_success_closes_the_circuit_but_keeps_the_operators_switch(database, monkeypatch):
    await checkout_env(database, monkeypatch)
    database.add(PaymentProviderHealth(provider="yookassa", enabled=False, failure_count=4, last_error="timeout",
                                       circuit_open_until=datetime.utcnow() - timedelta(minutes=1)))
    await database.commit()
    await shop.create_payment({"plan_id": 1, "provider": "yookassa"}, checkout([(b"idempotency-key", b"buy-health")]), database)
    health = await database.scalar(select(PaymentProviderHealth).execution_options(populate_existing=True))
    assert (health.failure_count, health.circuit_open_until, health.last_error) == (0, None, None)
    assert health.enabled is False, "a provider the operator switched off stays off"


@pytest.mark.asyncio
async def test_the_referrer_is_fixed_on_the_payment_when_it_is_created(database, monkeypatch):
    await checkout_env(database, monkeypatch)
    (await database.get(User, 1)).referred_by_id = 2
    await database.commit()
    await shop.create_payment({"plan_id": 1, "provider": "yookassa"}, checkout([(b"idempotency-key", b"buy-ref")]), database)
    (await database.get(User, 1)).referred_by_id = None  # the attribution changes later
    await database.commit()
    payment = await database.scalar(select(Payment).where(Payment.idempotency_key == "buy-ref"))
    assert payment.referrer_id_snapshot == 2 and payment.referral_terms_snapshot is not None


@pytest.mark.asyncio
async def test_promo_uses_are_reserved_and_released(database):
    promo = PromoCode(code="SPRING", kind="percent", value=Decimal("10"), usage_limit=1, used_count=0, enabled=True)
    database.add(promo)
    await database.commit()
    promo_id = promo.id
    first = await shop.reserve_promo(database, promo, 1, "order-1")
    first_id = first.id
    await database.commit()
    assert first.status == "reserved" and (await database.get(PromoCode, promo_id)).reserved_count == 1
    with pytest.raises(HTTPException) as taken:
        await shop.reserve_promo(database, promo, 2, "order-2")
    assert taken.value.detail == "Лимит промокода исчерпан", "a reserved use counts against the limit"
    await database.rollback()
    assert await shop.release_promo_reservation(database, first_id) is True
    assert await shop.release_promo_reservation(database, first_id) is False, "a release happens once"
    await database.commit()
    promo = await database.get(PromoCode, promo_id, populate_existing=True)
    assert promo.reserved_count == 0
    assert (await shop.reserve_promo(database, promo, 2, "order-3")).status == "reserved"


@pytest.mark.asyncio
async def test_refunding_an_older_payment_keeps_access_paid_by_a_newer_one(database, monkeypatch):
    common = dict(user_id=1, subscription_id=1, plan_id=1, provider="yookassa", amount=Decimal("100"), currency="RUB",
                  duration_days_snapshot=30, purpose="subscription")
    old = Payment(id=60, order_id="o-60", idempotency_key="k-60", status="refunded", fulfillment_status="completed", **common)
    database.add_all([old, Payment(id=61, order_id="o-61", idempotency_key="k-61", status="paid", fulfillment_status="completed", **common)])
    await database.commit()
    patched = []

    class Panel:
        async def patch_user(self, uid, body):
            patched.append(body)

        async def disable_user(self, uid):
            patched.append(("disable", uid))
    monkeypatch.setattr(shop, "RemnawaveClient", Panel)
    out = await shop._safe_revoke_for_refunded_payment(database, old, "a@b.c", "subscription.revoked.refund")
    assert out == {"revoked": False, "reason": "newer_fulfilled_payment"} and patched == []
    newer = await database.get(Payment, 61)
    newer.fulfillment_status = "failed"  # a newer payment that never gave access does not protect
    await database.commit()
    out = await shop._safe_revoke_for_refunded_payment(database, old, "a@b.c", "subscription.revoked.refund")
    assert out == {"revoked": True} and patched == [("disable", "remote-1")], "15 days left, 30 refunded: access ends"


def test_promo_reservation_schema():
    assert "promo_reservations" in tables() and "reserved_count" in columns("promo_codes")
    assert revision("0024_v44_5_7_logic_hardening") is not None
    assert {"referrer_id_snapshot", "referral_terms_snapshot"} <= columns("payments")


def test_promo_reservation_model_is_importable():
    assert PromoReservation.__tablename__ == "promo_reservations"
