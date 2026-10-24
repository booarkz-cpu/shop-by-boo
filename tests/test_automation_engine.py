"""Automation engine: validated rules, one execution per anchor, bounded actions, campaigns."""
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import automation, main, v3_api
from app.models import AutomationExecution, AutomationRule, Broadcast, Campaign, FinancialLedger, Notification, Payment, Subscription, User
from test_subscription_commerce import database

ADMIN = SimpleNamespace(email="root@example.test", role="admin")


def factory(db):
    return lambda: AsyncSession(db.bind, expire_on_commit=False)


async def rule(db, event, conditions=None, actions=None, created=None):
    cond, act = automation.validate_rule(event, conditions or {}, actions or {"notify": {"title": "Привет", "body": "Срок до {expires_at}", "telegram": True}})
    row = AutomationRule(name=event, event=event, conditions=cond, actions=act, enabled=True, priority=1,
                         created_at=created or datetime.utcnow() - timedelta(days=30))
    db.add(row)
    await db.commit()
    return row


def test_validation_rejects_unknown_events_unbounded_bonus_and_empty_actions():
    for event, cond, act in [("order.weird", {}, {"notify": {"title": "a", "body": "b"}}),
                             ("payment.paid", {}, {"wallet_bonus": {"amount": "5000"}}),
                             ("payment.paid", {}, {}),
                             ("subscription.expiring", {"days": 90}, {"notify": {"title": "a", "body": "b"}}),
                             ("user.registered", {"min_amount": "10"}, {"notify": {"title": "a", "body": "b"}})]:
        with pytest.raises(HTTPException):
            automation.validate_rule(event, cond, act)
    cond, act = automation.validate_rule("payment.paid", {"min_amount": 100}, {"wallet_bonus": {"amount": 25}})
    assert cond["min_amount"] == "100.00" and act == {"wallet_bonus": {"amount": "25.00"}}


@pytest.mark.asyncio
async def test_expiring_subscription_runs_once_and_sends_telegram(database):
    owner = await database.get(User, 1)
    owner.telegram_id = 777
    await database.commit()
    r = await rule(database, "subscription.expiring", {"days": 30})
    sent = []

    async def send(chat, text):
        sent.append((chat, text))
    assert await automation.run_rule(factory(database), r.id, send=send) == 1
    assert await automation.run_rule(factory(database), r.id, send=send) == 0  # idempotent
    note = (await database.execute(select(Notification).where(Notification.kind == "automation"))).scalar_one()
    sub = await database.get(Subscription, 1)
    assert note.body == f"Срок до {sub.expires_at:%d.%m.%Y}"
    assert sent == [(777, f"Привет\n\nСрок до {sub.expires_at:%d.%m.%Y}")]
    fresh = await database.get(AutomationRule, r.id, populate_existing=True)
    assert fresh.run_count == 1 and fresh.last_run_at is not None


@pytest.mark.asyncio
async def test_wallet_bonus_is_ledgered_once_and_respects_payment_conditions(database):
    now = datetime.utcnow()
    database.add_all([Payment(user_id=1, plan_id=1, provider="yookassa", order_id="auto-1", amount=Decimal("150"), currency="RUB",
                              status="paid", fulfillment_status="completed", paid_at=now),
                      Payment(user_id=2, plan_id=1, provider="yookassa", order_id="auto-2", amount=Decimal("50"), currency="RUB",
                              status="paid", fulfillment_status="completed", paid_at=now)])
    await database.commit()
    r = await rule(database, "payment.paid", {"min_amount": 100}, {"wallet_bonus": {"amount": 10}}, created=now - timedelta(hours=1))
    before = (await database.get(User, 1)).wallet_balance
    assert await automation.run_rule(factory(database), r.id) == 1
    assert await automation.run_rule(factory(database), r.id) == 0
    owner = await database.get(User, 1, populate_existing=True)
    assert owner.wallet_balance == Decimal(before) + Decimal("10")
    ledger = (await database.execute(select(FinancialLedger).where(FinancialLedger.kind == "automation_bonus"))).scalars().all()
    assert len(ledger) == 1 and ledger[0].user_id == 1


@pytest.mark.asyncio
async def test_rules_do_not_mail_customers_from_before_the_rule(database):
    r = await rule(database, "user.registered", created=datetime.utcnow())
    assert await automation.run_rule(factory(database), r.id) == 0
    database.add(User(id=50, referral_code="NEWBIE", created_at=datetime.utcnow() + timedelta(seconds=1)))
    await database.commit()
    assert await automation.run_rule(factory(database), r.id, now=datetime.utcnow() + timedelta(seconds=5)) == 1


@pytest.mark.asyncio
async def test_daily_limit_caps_executions(database):
    for i in range(5):
        database.add(User(id=100 + i, referral_code=f"LIM{i}", created_at=datetime.utcnow()))
    await database.commit()
    r = await rule(database, "user.registered", {"daily_limit": 2}, created=datetime.utcnow() - timedelta(hours=1))
    assert await automation.run_rule(factory(database), r.id) == 2
    assert await automation.run_rule(factory(database), r.id) == 0
    assert await database.scalar(select(func.count()).select_from(AutomationExecution)) == 2


@pytest.mark.asyncio
async def test_toggle_validates_legacy_rules(database):
    database.add(AutomationRule(id=9, name="legacy", event="subscription.expiring", conditions={}, actions={"type": "notify"}, enabled=False))
    await database.commit()
    with pytest.raises(HTTPException):
        await v3_api.toggle_automation(9, {"enabled": True}, database, ADMIN)


@pytest.mark.asyncio
async def test_scheduled_campaign_goes_through_the_broadcast_queue(database, monkeypatch):
    monkeypatch.setattr(automation.settings, "bot_token", "123:abc")
    database.add_all([Campaign(name="Осень", kind="promotion", status="scheduled", audience={"segment": "inactive"},
                               content={"text": "Скидка 20%"}, starts_at=datetime.utcnow() - timedelta(minutes=1)),
                      Campaign(name="Пусто", kind="broadcast", status="scheduled", audience={"segment": "all"}, content={})])
    await database.commit()
    assert await automation.run_campaigns(factory(database)) == 1
    camp = (await database.execute(select(Campaign).where(Campaign.name == "Осень"))).scalar_one()
    empty = (await database.execute(select(Campaign).where(Campaign.name == "Пусто"))).scalar_one()
    await database.refresh(camp); await database.refresh(empty)
    assert camp.status == "running" and empty.status == "paused"
    b = await database.get(Broadcast, camp.content["broadcast_id"])
    assert b.target == "inactive" and b.text == "Скидка 20%"
    b.status, b.sent_count, b.failed_count = "completed", 7, 1
    await database.commit()
    await automation.run_campaigns(factory(database))
    await database.refresh(camp)
    assert (camp.status, camp.sent_count, camp.failed_count) == ("completed", 7, 1)


@pytest.mark.asyncio
async def test_only_administrators_manage_wallet_bonus_rules(database):
    operator = SimpleNamespace(email="op@example.test", role="operator")
    payload = main.RuleIn(name="bonus", event="payment.paid", actions={"wallet_bonus": {"amount": 10}})
    with pytest.raises(HTTPException) as denied:
        await main.enterprise_rule_create(payload, database, operator)
    assert denied.value.status_code == 403
    created = await main.enterprise_rule_create(main.RuleIn(name="bonus", event="payment.paid", actions={"wallet_bonus": {"amount": 10}}), database, ADMIN)
    with pytest.raises(HTTPException):
        await v3_api.toggle_automation(created["id"], {"enabled": True}, database, operator)
    assert (await v3_api.toggle_automation(created["id"], {"enabled": True}, database, ADMIN))["enabled"] is True
