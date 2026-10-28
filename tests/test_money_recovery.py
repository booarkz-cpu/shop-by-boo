"""Money recovery through the automation engine: a forgotten checkout and a declined auto-renewal get a nudge,
once per customer and period, and never after the customer has paid."""
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app import automation
from app.models import AutoRenewMethod, Notification, Payment, User
from test_automation_engine import factory, rule
from test_subscription_commerce import database  # noqa: F401


async def noop(*a):
    return None


def payment(**fields):
    base = dict(user_id=1, subscription_id=1, plan_id=1, provider="yookassa", amount=Decimal("100"), currency="RUB", status="pending",
                purpose="subscription", fulfillment_status="pending")
    base.update(fields)
    return Payment(**base)


async def notes(db):
    return (await db.execute(select(Notification).where(Notification.kind == "automation").execution_options(populate_existing=True))).scalars().all()


@pytest.mark.asyncio
async def test_a_forgotten_checkout_gets_one_nudge_and_a_paid_one_none(database):  # noqa: F811
    now = datetime.utcnow()
    database.add_all([payment(order_id="a1", idempotency_key="a1", created_at=now - timedelta(minutes=40)),
                      payment(order_id="a2", idempotency_key="a2", created_at=now - timedelta(minutes=30), status="failed")])
    await database.commit()
    preset = automation.PRESETS["checkout_nudge"]
    r = await rule(database, preset["event"], preset["conditions"], preset["actions"])
    assert await automation.run_rule(factory(database), r.id, send=noop) == 1, "two attempts of one customer, one message"
    assert await automation.run_rule(factory(database), r.id, send=noop) == 0
    assert "СБП" in (await notes(database))[0].body
    # A customer who paid after the forgotten attempt is left alone.
    user2 = User(email="paid@corgi.test", referral_code="PAID2")
    database.add(user2)
    await database.commit()
    database.add_all([payment(user_id=user2.id, subscription_id=None, order_id="b1", idempotency_key="b1", created_at=now - timedelta(minutes=50)),
                      payment(user_id=user2.id, subscription_id=None, order_id="b2", idempotency_key="b2", status="paid", created_at=now - timedelta(minutes=45),
                              paid_at=now - timedelta(minutes=44))])
    await database.commit()
    assert await automation.run_rule(factory(database), r.id, send=noop) == 0
    # Too fresh: the customer may still be on the payment page.
    database.add(payment(user_id=1, plan_id=2, order_id="a3", idempotency_key="a3", created_at=now - timedelta(minutes=5)))
    await database.commit()
    assert await automation.run_rule(factory(database), r.id, send=noop) == 0


@pytest.mark.asyncio
async def test_a_declined_auto_renewal_starts_the_reminder_series(database):  # noqa: F811
    database.add(AutoRenewMethod(user_id=1, provider="yookassa", external_token_encrypted="x", enabled=False, status="payment_failed",
                                 failure_count=3, last_attempt_at=datetime.utcnow() - timedelta(hours=2)))
    await database.commit()
    now_rule = await rule(database, "auto_renew.failed", automation.PRESETS["renew_failed_now"]["conditions"], automation.PRESETS["renew_failed_now"]["actions"])
    day3 = await rule(database, "auto_renew.failed", automation.PRESETS["renew_failed_day3"]["conditions"], automation.PRESETS["renew_failed_day3"]["actions"])
    assert await automation.run_rule(factory(database), now_rule.id, send=noop) == 1
    assert await automation.run_rule(factory(database), day3.id, send=noop) == 0, "the discount comes on day three"
    method = await database.scalar(select(AutoRenewMethod))
    method.last_attempt_at = datetime.utcnow() - timedelta(days=3, hours=1)
    await database.commit()
    assert await automation.run_rule(factory(database), day3.id, send=noop) == 1
    assert any("промокод" in n.body.lower() or "BACK" in n.body for n in await notes(database))


def test_the_new_presets_are_valid_rules():
    for key in ("checkout_nudge", "checkout_promo", "renew_failed_now", "renew_failed_day1", "renew_failed_day3", "traffic_limited"):
        preset = automation.PRESETS[key]
        automation.validate_rule(preset["event"], preset["conditions"], preset["actions"])
