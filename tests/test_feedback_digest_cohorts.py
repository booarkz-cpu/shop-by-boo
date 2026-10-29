"""v28.52: support ratings per operator and NPS waves, the weekly digest with its one piece of advice, and the cohort
table of first payments."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import cohorts, feedback as fb, weekly_digest as wd
from app.models import AuditLog, Payment, PaymentProviderHealth, Subscription, SupportTicket, User
from test_subscription_commerce import database  # noqa: F401

ADMIN = SimpleNamespace(email="owner@example.com")


async def _pay(db, n, user_id, amount, paid_at, provider="yookassa"):
    db.add(Payment(user_id=user_id, subscription_id=None, plan_id=1, provider=provider, order_id=f"o-{n}", amount=Decimal(str(amount)),
                   original_amount=Decimal(str(amount)), discount_amount=Decimal("0"), currency="RUB", status="paid", fulfillment_status="completed",
                   idempotency_key=f"o-{n}", purpose="subscription", bonus_days=0, paid_at=paid_at))
    await db.commit()


def test_nps_and_waves():
    assert fb.nps_of([10, 9, 8, 3]) == 25
    assert fb.nps_of([]) is None
    assert fb.period(datetime(2026, 11, 2), 90) == "2026Q4"
    rows = fb.nps_rows("2026Q4")
    assert len(rows) == 2 and rows[0][0] == ("0", "nps:2026Q4:0") and rows[1][-1] == ("10", "nps:2026Q4:10")
    assert fb.csat_rows(7)[0][4] == ("5⭐", "csat:7:5")


@pytest.mark.asyncio
async def test_csat_asked_once_rated_by_operator_and_low_score_alert(database):  # noqa: F811
    db = database
    await fb.admin_feedback_config(fb.FeedbackConfigIn(csat_enabled=True, csat_delay_minutes=10), db, ADMIN)
    user = await db.get(User, 1)
    user.telegram_id = 501
    now = datetime.utcnow()
    db.add(SupportTicket(id=10, user_id=1, subject="Не подключается", message="?", status="resolved", created_at=now - timedelta(hours=1),
                         updated_at=now - timedelta(minutes=20)))
    db.add(AuditLog(action="support.ticket.replied", actor="anna@example.com", target="10"))
    await db.commit()
    sent = []

    async def send(chat, text, rows):
        sent.append((chat, rows))
        return True
    assert (await fb.ask_pass(db, now, send))["csat"] == 1
    assert (await fb.ask_pass(db, now, send))["csat"] == 0  # asked once
    assert sent[0][0] == 501 and sent[0][1][0][0][1] == "csat:10:1"
    alerts = []

    async def alert(text):
        alerts.append(text)
    await fb.record(db, 1, "csat", 2, ticket_id=10, comment="долго", alert=alert)
    await fb.record(db, 1, "csat", 5, ticket_id=10, alert=alert)  # a second tap changes the score
    assert len(alerts) == 1 and "anna@example.com" in alerts[0]
    with pytest.raises(HTTPException):
        await fb.record(db, 2, "csat", 5, ticket_id=10)  # not the customer's ticket
    r = await fb.report(db, 90)
    assert r["csat"]["count"] == 1 and r["csat"]["average"] == 5 and r["csat"]["operators"][0]["operator"] == "anna@example.com"
    mine = await fb.my_feedback(SimpleNamespace(), db)
    assert mine["tickets"] == []


@pytest.mark.asyncio
async def test_nps_wave_for_paying_customers(database):  # noqa: F811
    db = database
    await fb.admin_feedback_config(fb.FeedbackConfigIn(nps_enabled=True, nps_min_days=30), db, ADMIN)
    now = datetime.utcnow()
    await _pay(db, 1, 1, 300, now - timedelta(days=40))
    await _pay(db, 2, 2, 300, now - timedelta(days=5))  # too new
    sent = []

    async def send(chat, text, rows):
        sent.append(chat)
        return True
    assert (await fb.ask_pass(db, now, send))["nps"] == 1
    assert (await fb.ask_pass(db, now, send))["nps"] == 0
    mine = await fb.my_feedback(SimpleNamespace(), db)
    assert mine["nps"]["wave"] == fb.period(now, 90)
    await fb.rate_shop(fb.RatingIn(score=9), SimpleNamespace(), db)
    assert (await fb.my_feedback(SimpleNamespace(), db))["nps"] is None
    assert (await fb.report(db, 90))["nps"]["score"] == 100


@pytest.mark.asyncio
async def test_cohorts_retention_and_revenue(database):  # noqa: F811
    db = database
    now = datetime(2026, 10, 29)
    db.add(User(id=3, referral_code="THIRD", acquisition_source="ads"))
    await db.commit()
    await _pay(db, 1, 1, 300, datetime(2026, 5, 3))
    await _pay(db, 2, 1, 300, datetime(2026, 6, 3))
    await _pay(db, 3, 3, 300, datetime(2026, 5, 10))
    sub = await db.get(Subscription, 1)
    sub.expires_at = datetime(2026, 12, 1)  # customer 1 is still with us
    db.add(Subscription(user_id=3, plan_id=1, is_primary=True, lifecycle_status="expired", expires_at=datetime(2026, 6, 9)))
    await db.commit()
    data = await cohorts.build(db, 12, now=now)
    may = next(c for c in data["cohorts"] if c["month"] == "2026-05")
    assert may["size"] == 2 and may["m1"] == 100 and may["m3"] == 50 and may["m12"] is None and may["revenue"] == "900.00"
    split = await cohorts.build(db, 12, by_source=True, now=now)
    assert {c["source"] for c in split["cohorts"]} == {"—", "ads"}


@pytest.mark.asyncio
async def test_weekly_digest_text_advice_and_schedule(database):  # noqa: F811
    db = database
    now = datetime.utcnow()
    await _pay(db, 1, 1, 1000, now - timedelta(days=10))
    await _pay(db, 2, 1, 500, now - timedelta(days=2))
    await _pay(db, 3, 1, 999, now - timedelta(days=1), provider="wallet")  # a wallet purchase is not new money
    text = await wd.render(db, now, nodes=[{"name": "NL-1", "status": "online"}])
    assert "Выручка: 500.00 ₽ (-50% к прошлой неделе)" in text and "Ноды: все в сети" in text
    assert "Совет: Выручка упала на 50%" in text
    db.add(PaymentProviderHealth(provider="lava", enabled=True, priority=1, circuit_open_until=now + timedelta(hours=1)))
    await db.commit()
    text = await wd.render(db, now, nodes=[{"name": "DE-2", "status": "offline"}])
    assert "Совет: Касса lava" in text and "не в сети DE-2" in text
    sent = []

    async def send(message):
        sent.append(message)
        return True
    monday = datetime(2026, 11, 2, 7, 0, tzinfo=timezone.utc)  # 10:00 Moscow
    assert not await wd.tick(db, monday, send, [])  # off by default
    await wd.put_digest(wd.DigestIn(enabled=True, weekday=0, time="09:00"), db, ADMIN)
    assert await wd.tick(db, monday, send, []) and len(sent) == 1
    assert not await wd.tick(db, monday + timedelta(hours=1), send, [])  # once a day
    assert not await wd.tick(db, monday + timedelta(days=1), send, [])  # Tuesday
