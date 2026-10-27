"""v44.3: an idempotent checkout retry is checked against the stored intent, checked by running checkout
(was: code lines searched in main.py and worker.py). The verified panel expiry is kept after an extension:
test_integration_billing_vpn.py («premium payment extends the panel user exactly once»)."""
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app import main as shop
from app.models import Payment, Plan
from test_behaviour_payments_v2 import checkout
from test_subscription_commerce import database  # noqa: F401
from test_v44_5_7_deep_regressions import checkout_env


@pytest.mark.asyncio
async def test_a_key_reused_for_another_plan_is_refused(database, monkeypatch):
    await checkout_env(database, monkeypatch)
    key = [(b"idempotency-key", b"same-key")]
    first = await shop.create_payment({"plan_id": 1, "provider": "yookassa"}, checkout(key), database)
    with pytest.raises(HTTPException) as other:
        await shop.create_payment({"plan_id": 2, "provider": "yookassa"}, checkout(key), database)
    assert (other.value.status_code, other.value.detail) == (409, "Idempotency-Key уже использован для другого платежа")
    again = await shop.create_payment({"plan_id": 1, "provider": "yookassa"}, checkout(key), database)
    assert again["id"] == first["id"], "the same request returns the same checkout"


@pytest.mark.asyncio
async def test_a_recovered_intent_keeps_its_stored_price(database, monkeypatch):
    await checkout_env(database, monkeypatch)
    database.add(Payment(user_id=1, subscription_id=1, plan_id=1, provider="yookassa", order_id="o-intent", amount=Decimal("100"),
                         currency="RUB", status="creation_unknown", idempotency_key="intent-key", purpose="subscription"))
    await database.commit()
    (await database.get(Plan, 1)).price = Decimal("350")  # the plan got more expensive after the lost answer
    await database.commit()
    charged = []

    class Gateway:
        async def create(self, amount, order_id, description, return_url):
            charged.append((amount, order_id))
            return {"id": "yk-recovered", "url": "https://pay"}
    monkeypatch.setattr(shop, "YooKassaProvider", Gateway)
    await shop.create_payment({"plan_id": 1, "provider": "yookassa"}, checkout([(b"idempotency-key", b"intent-key")]), database)
    assert charged == [(Decimal("100"), "o-intent")], "the customer pays what was agreed, under the same order"
    row = await database.scalar(select(Payment).where(Payment.order_id == "o-intent").execution_options(populate_existing=True))
    assert row.provider_payment_id == "yk-recovered"
