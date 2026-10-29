"""v28.50: a customer freezes a paid subscription (paid days kept, panel off), thaws it early or on time; a purchase
thaws it first. Dunning: the retry schedule, grace, customer messages and the wallet fallback after a declined renewal."""
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app import dunning
from app import subscription_freeze as fz
from app.models import AutoRenewMethod, Notification, Payment, Subscription, SubscriptionFreeze, User
from test_subscription_commerce import database  # noqa: F401

ADMIN = SimpleNamespace(email="owner@example.com")


class Panel:
    def __init__(self):
        self.calls = []

    async def patch_user(self, uuid, body):
        self.calls.append(("patch", uuid, body))

    async def disable_user(self, uuid):
        self.calls.append(("disable", uuid))

    async def enable_user(self, uuid):
        self.calls.append(("enable", uuid))


@pytest.fixture
def panel(monkeypatch):
    p = Panel()
    monkeypatch.setattr(fz, "_panel", lambda: p)
    return p


async def _enable(db, **extra):
    await fz.admin_freeze_config(fz.FreezeConfigIn(enabled=True, **extra), db, ADMIN)


async def _paid(db, sub_id=1):
    db.add(Payment(user_id=1, subscription_id=sub_id, plan_id=1, provider="yookassa", order_id=f"paid-{sub_id}", amount=Decimal("100"),
                   original_amount=Decimal("100"), discount_amount=Decimal("0"), currency="RUB", status="paid", fulfillment_status="completed",
                   idempotency_key=f"paid-{sub_id}", purpose="subscription", bonus_days=0))
    await db.commit()


@pytest.mark.asyncio
async def test_freeze_rules_then_freeze_and_early_thaw(database, panel):  # noqa: F811
    db = database
    user, sub = await db.get(User, 1), await db.get(Subscription, 1)
    assert "недоступна" in await fz.check(db, user, sub, 7)
    await _enable(db)
    assert "оплаченную" in await fz.check(db, user, sub, 7)
    await _paid(db)
    assert "от 3 до 30" in await fz.check(db, user, sub, 2)
    before = sub.expires_at
    result = await fz.freeze(db, user, sub, 7, panel)
    assert sub.lifecycle_status == "frozen" and sub.expires_at == before + timedelta(days=7)
    assert panel.calls[0][0] == "patch" and panel.calls[1] == ("disable", "remote-1")
    assert result["until"]
    assert "уже заморожена" in await fz.check(db, user, sub, 7)
    # Two days later the customer comes back early: five unused frozen days are taken back.
    row = await db.scalar(select(SubscriptionFreeze))
    row.started_at -= timedelta(days=2)
    row.until -= timedelta(days=2)
    await db.commit()
    assert await fz.thaw(db, sub, panel, commit=True)
    assert sub.lifecycle_status == "active"
    assert abs((sub.expires_at - (before + timedelta(days=2))).total_seconds()) < 5
    assert panel.calls[-1] == ("enable", "remote-1") and row.ended_at is not None
    used = await fz.usage(db, 1)
    assert used == {"times": 1, "days": 2}


@pytest.mark.asyncio
async def test_yearly_limits_and_planned_thaw(database, panel):  # noqa: F811
    db = database
    await _enable(db, year_times=1)
    await _paid(db)
    user, sub = await db.get(User, 1), await db.get(Subscription, 1)
    await fz.freeze(db, user, sub, 5, panel)
    row = await db.scalar(select(SubscriptionFreeze))
    row.until = datetime.utcnow() - timedelta(minutes=1)
    await db.commit()
    sent = []

    async def notify(chat, text):
        sent.append(text)
    user.telegram_id = 555
    await db.commit()
    assert await fz.thaw_due(db, panel, notify) == [1]
    assert sub.lifecycle_status == "active" and sent and "снова работает" in sent[0]
    assert "не больше 1 раз" in await fz.check(db, user, sub, 5)
    status = await fz.my_freeze(SimpleNamespace(), None, db)
    assert status["enabled"] and status["times_left"] == 0 and status["frozen"] is None


@pytest.mark.asyncio
async def test_purchase_onto_frozen_subscription_thaws_it_first(database, panel):  # noqa: F811
    from app.subscriptions import reserve_target
    db = database
    await _enable(db)
    await _paid(db)
    user, sub = await db.get(User, 1), await db.get(Subscription, 1)
    before = sub.expires_at
    await fz.freeze(db, user, sub, 10, panel)
    target = await reserve_target(db, user, 1, {"subscription_id": 1})
    assert target.id == 1 and target.lifecycle_status == "active"
    assert abs((target.expires_at - before).total_seconds()) < 5  # the unused frozen days are not kept on top of the purchase
    assert ("enable", "remote-1") in panel.calls


@pytest.mark.asyncio
async def test_admin_thaw_and_config_validation(database, panel):  # noqa: F811
    db = database
    with pytest.raises(HTTPException):
        await fz.admin_freeze_config(fz.FreezeConfigIn(enabled=True, min_days=10, max_days=5), db, ADMIN)
    await _enable(db)
    await _paid(db)
    user, sub = await db.get(User, 1), await db.get(Subscription, 1)
    await fz.freeze(db, user, sub, 4, panel)
    listing = await fz.admin_freeze(db, ADMIN)
    assert listing["frozen_now"] == 1 and listing["items"][0]["subscription_id"] == 1
    assert (await fz.admin_thaw(1, db, ADMIN))["ok"]
    with pytest.raises(HTTPException):
        await fz.admin_thaw(1, db, ADMIN)


def test_dunning_schedule_and_messages():
    off = dict(dunning.DEFAULT)
    assert dunning.next_attempt(1, off) == timedelta(hours=2) and dunning.max_failures(off) == 3 and dunning.grace(off) == timedelta(hours=72)
    on = {**dunning.DEFAULT, "enabled": True, "retry_hours": [24, 72], "max_failures": 4, "grace_hours": 120}
    assert dunning.next_attempt(1, on) == timedelta(hours=24)
    assert dunning.next_attempt(2, on) == timedelta(hours=72)
    assert dunning.next_attempt(3, on) == timedelta(hours=72)  # the last interval repeats
    assert dunning.max_failures(on) == 4 and dunning.grace(on) == timedelta(hours=120)
    assert "попытка 1 из 4" in dunning.notice(1, on, datetime(2026, 11, 2, 10, 0), True)
    assert "выключено" in dunning.notice(4, on, None, True)


@pytest.mark.asyncio
async def test_dunning_notice_and_wallet_fallback(database):  # noqa: F811
    db = database
    await dunning.put_dunning(dunning.DunningIn(enabled=True), db, ADMIN)
    user, sub = await db.get(User, 1), await db.get(Subscription, 1)
    user.telegram_id = 777
    method = AutoRenewMethod(user_id=1, provider="yookassa", external_token_encrypted="x", enabled=True, status="past_due", failure_count=1,
                             next_attempt_at=datetime.utcnow() + timedelta(days=1))
    db.add(method)
    sub.auto_renew_enabled = True
    sub.lifecycle_status = "grace"
    sub.last_renewal_failure_at = datetime.utcnow()
    await db.commit()
    sent = []

    async def send(chat, text):
        sent.append((chat, text))
    await dunning.on_failure(db, user, sub, method, await dunning.load(db), send)
    await dunning.on_failure(db, user, sub, method, await dunning.load(db), send)
    notes = (await db.execute(select(Notification).where(Notification.kind == "renewal_failed"))).scalars().all()
    assert len(notes) == 1 and sent[0][0] == 777 and "попытка 1 из 3" in sent[0][1]
    spent = []

    async def spend(session, customer, payload, idem):
        spent.append((customer.id, payload, idem))
        return {"ok": True, "payment_id": 99}
    assert await dunning.wallet_pass(db, spend) == [1]
    assert spent[0][1] == {"plan_id": 1, "subscription_id": 1} and spent[0][2].startswith("dunning-wallet-1-")
    method = await db.scalar(select(AutoRenewMethod))
    assert method.failure_count == 0 and method.status == "active"
    assert (await db.get(Subscription, 1)).last_renewal_failure_at is None
    overview = await dunning.get_dunning(db, ADMIN)
    assert overview["config"]["enabled"] and overview["past_due"] == 0
