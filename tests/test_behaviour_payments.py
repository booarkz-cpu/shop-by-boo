"""v28.30.0: behaviour tests that replace source-text checks of the payment path.

Each test here used to be an ``assert '<code line>' in MAIN`` in test_v44_5_8_deep_regressions.py.
Those checks broke on any rename and passed on wrong code that kept the line; these run it."""
import asyncio
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import main as shop
from app.models import AutoRenewMethod, Payment, Subscription, User
from app.remnawave import RemnawaveClient, RemnawaveError
from test_money_review import FakeRW, _renewable, _run_scheduler_once, _scheduler_env
from test_subscription_commerce import database  # noqa: F401


@pytest.mark.asyncio
async def test_remote_extension_refuses_an_expiry_that_moved_on_its_own(monkeypatch):
    """Was: 'Remote expiry advanced unexpectedly' in remnawave.py."""
    client = RemnawaveClient.__new__(RemnawaveClient)
    before = datetime(2026, 11, 1)
    calls = []

    async def expiry(uid):
        return before + timedelta(days=3)  # someone else already extended it

    async def extend(uid, days):
        calls.append(days)
    monkeypatch.setattr(client, "get_expiry", expiry, raising=False)
    monkeypatch.setattr(client, "extend_user", extend, raising=False)
    with pytest.raises(RemnawaveError, match="advanced unexpectedly"):
        await client.extend_idempotent("u1", 30, before, before + timedelta(days=30))
    assert calls == []  # never a second grant


@pytest.mark.asyncio
async def test_remote_extension_is_idempotent_and_verified(monkeypatch):
    client = RemnawaveClient.__new__(RemnawaveClient)
    before = datetime(2026, 11, 1)
    after = before + timedelta(days=30)
    state = {"expiry": before}

    async def expiry(uid):
        return state["expiry"]

    async def extend(uid, days):
        state["expiry"] = state["expiry"] + timedelta(days=days)
    monkeypatch.setattr(client, "get_expiry", expiry, raising=False)
    monkeypatch.setattr(client, "extend_user", extend, raising=False)
    assert (await client.extend_idempotent("u1", 30, before, after))["already_applied"] is False
    assert (await client.extend_idempotent("u1", 30, before, after))["already_applied"] is True  # retry is a no-op
    assert state["expiry"] == after


@pytest.mark.asyncio
async def test_auto_renew_stores_the_intent_before_charging(database, monkeypatch):
    """Was: MAIN.index('db.add(payment)') < MAIN.index('charge_recurring')."""
    charges = []
    _scheduler_env(monkeypatch, database, charges)
    seen = []

    async def charge(self, amount, order_id, desc, token):
        # Read from a separate session: the row must already be committed.
        async with AsyncSession(database.bind) as other:
            row = await other.scalar(select(Payment).where(Payment.order_id == order_id))
        seen.append((row.status, row.provider_payment_id) if row else None)
        return {"id": "yk-1"}
    monkeypatch.setattr(shop.YooKassaProvider, "charge_recurring", charge)
    await _renewable(database)
    await _run_scheduler_once(monkeypatch)
    assert seen == [("creating", None)]


@pytest.mark.asyncio
async def test_existing_remote_user_gets_the_purchased_traffic_devices_and_profile(database, monkeypatch):
    """Was: 'await rw.update_entitlements(sub.remnawave_uuid,traffic_limit_gb,...)' in MAIN."""
    db = database
    p = Payment(user_id=1, subscription_id=1, plan_id=2, provider="yookassa", order_id="ent-1", amount=200, currency="RUB",
                status="paid", fulfillment_status="pending", duration_days_snapshot=30, traffic_limit_gb_snapshot=200,
                device_limit_snapshot=4, remnawave_profile_id_snapshot="squad-plus", purpose="subscription")
    db.add(p)
    await db.commit()
    rw = FakeRW(status="ACTIVE")
    rw.expiry = (await db.get(Subscription, 1)).expires_at
    monkeypatch.setattr(shop, "RemnawaveClient", lambda: rw)
    monkeypatch.setattr(shop, "redis_client", object())
    await shop.fulfill(p.id, db)
    update = next(c for c in rw.calls if c[0] == "update")
    assert update[1][:3] == ("remote-1", 200, "squad-plus")
    sub = await db.get(Subscription, 1)
    assert (sub.traffic_limit_gb_snapshot, sub.device_limit_snapshot, sub.remnawave_profile_id_snapshot) == (200, 4, "squad-plus")
