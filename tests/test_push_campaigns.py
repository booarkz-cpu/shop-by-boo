"""Push campaigns sent later (Moscow time) and A/B tests of two texts, through the real queries."""
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app import push_campaigns as pc
from app.models import Base, Notification, Payment, Plan, PushCampaign, PushCampaignRecipient, User

NOW = datetime(2026, 10, 26, 12, 0)  # 15:00 in Moscow


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        session.add(Plan(id=1, name="Month", price=100, duration_days=30, traffic_limit_gb=0, device_limit=3))
        session.add_all([User(id=uid, referral_code=f"U{uid}") for uid in range(1, 401)])
        await session.commit()
        yield session
    await engine.dispose()


def payload(**kw):
    base = dict(segment="no_subscription", title="Попробуйте", body="Три дня бесплатно")
    base.update(kw)
    return pc.CampaignIn(**base)


def test_moscow_time_is_stored_in_utc():
    assert pc.moscow_to_utc("2026-11-01T10:00") == datetime(2026, 11, 1, 7, 0)
    assert pc.utc_to_moscow(datetime(2026, 11, 1, 7, 0)) == "2026-11-01T10:00"


def test_variant_b_needs_both_texts():
    with pytest.raises(ValidationError):
        payload(title_b="Только заголовок")
    with pytest.raises(ValidationError):
        payload(b_percent=95, title_b="B", body_b="B")


@pytest.mark.asyncio
async def test_a_scheduled_campaign_waits_and_is_sent_once(db):
    row = await pc.send_campaign(db, payload(send_at="2026-10-26T18:30"), "admin", NOW)
    await db.commit()
    assert (row.status, row.scheduled_at, row.recipients) == ("scheduled", datetime(2026, 10, 26, 15, 30), 400)
    assert await db.scalar(select(func.count(Notification.id))) == 0, "nothing is sent before its time"
    assert await pc.send_due(db, NOW + timedelta(hours=3)) == 0
    # Meanwhile a customer bought a subscription: the segment is computed at sending.
    from app.models import Subscription
    db.add(Subscription(user_id=7, plan_id=1, expires_at=NOW + timedelta(days=30), lifecycle_status="active", is_primary=True))
    await db.commit()
    assert await pc.send_due(db, NOW + timedelta(hours=3, minutes=31)) == 1
    assert (row.status, row.sent_at, row.recipients) == ("sent", NOW + timedelta(hours=3, minutes=31), 399)
    assert await pc.send_due(db, NOW + timedelta(hours=4)) == 0, "sent exactly once"
    assert await db.scalar(select(func.count(Notification.id))) == 399


@pytest.mark.asyncio
async def test_past_or_far_times_and_cancel(db):
    now_row = await pc.send_campaign(db, payload(send_at="2026-10-26T14:00"), "admin", NOW)
    assert now_row.status == "sent", "a Moscow time that has passed means «now»"
    with pytest.raises(HTTPException):
        await pc.send_campaign(db, payload(title="Другое", send_at="2027-06-01T10:00"), "admin", NOW)
    later = await pc.send_campaign(db, payload(title="Позже", send_at="2026-10-27T10:00"), "admin", NOW)
    await db.commit()
    later.status = "cancelled"  # what the cancel endpoint does
    await db.commit()
    assert await pc.send_due(db, NOW + timedelta(days=2)) == 0, "a cancelled campaign never goes out"


@pytest.mark.asyncio
async def test_ab_split_is_stable_and_follows_the_share(db):
    row = await pc.send_campaign(db, payload(title_b="Скидка 20%", body_b="Только сегодня", b_percent=30), "admin", NOW)
    await db.commit()
    rows = (await db.execute(select(PushCampaignRecipient.user_id, PushCampaignRecipient.variant))).all()
    share_b = sum(1 for _, v in rows if v == "b") / len(rows)
    assert len(rows) == 400 and 0.22 < share_b < 0.38
    assert all(pc.variant_of(row.id, uid, 30) == v for uid, v in rows), "the same customer always gets the same text"
    notes = dict((await db.execute(select(Notification.user_id, Notification.title))).all())
    assert all(notes[uid] == ("Скидка 20%" if v == "b" else "Попробуйте") for uid, v in rows)


@pytest.mark.asyncio
async def test_results_count_payments_in_the_window_and_name_a_winner(db):
    row = await pc.send_campaign(db, payload(title_b="Скидка 20%", body_b="Только сегодня", b_percent=50, conversion_days=7), "admin", NOW)
    await db.commit()
    variants = dict((await db.execute(select(PushCampaignRecipient.user_id, PushCampaignRecipient.variant))).all())
    a_users = [u for u, v in variants.items() if v == "a"]
    b_users = [u for u, v in variants.items() if v == "b"]
    n = 0

    def paid(uid, at, status="paid"):
        nonlocal n
        n += 1
        return Payment(user_id=uid, plan_id=1, provider="sandbox", order_id=f"o{n}", amount=Decimal("100"), currency="RUB",
                       status=status, idempotency_key=f"k{n}", created_at=at, paid_at=at)
    db.add_all([paid(u, NOW + timedelta(days=1)) for u in b_users[:60]])          # B: 60 buy within the week
    db.add_all([paid(u, NOW + timedelta(days=2)) for u in a_users[:10]])          # A: 10 buy
    db.add_all([paid(u, NOW + timedelta(days=9)) for u in a_users[10:60]])        # after the window: not counted
    db.add_all([paid(u, NOW - timedelta(days=1)) for u in a_users[60:90]])        # before the campaign: not counted
    db.add_all([paid(u, NOW + timedelta(days=1), status="pending") for u in a_users[90:120]])
    await db.commit()
    result = await pc.campaign_results(db, row, NOW + timedelta(days=8))
    by = {v["variant"]: v for v in result["variants"]}
    assert (by["a"]["paid"], by["b"]["paid"]) == (10, 60)
    assert by["b"]["revenue"] == "6000.00" and by["a"]["recipients"] + by["b"]["recipients"] == 400
    assert result["winner"] == "b" and result["p_value"] < 0.05 and result["complete"] is True


@pytest.mark.asyncio
async def test_small_or_equal_tests_have_no_winner(db):
    row = await pc.send_campaign(db, payload(segment="no_subscription", title_b="B", body_b="B текст"), "admin", NOW)
    await db.commit()
    result = await pc.campaign_results(db, row, NOW + timedelta(days=1))
    assert result["winner"] is None and result["complete"] is False
    plain = await pc.send_campaign(db, payload(title="Без теста"), "admin", NOW)
    assert [v["variant"] for v in (await pc.campaign_results(db, plain, NOW))["variants"]] == ["a"]


@pytest.mark.asyncio
async def test_repeat_guard_covers_scheduled_campaigns(db):
    await pc.send_campaign(db, payload(send_at="2026-10-27T10:00"), "admin", NOW)
    with pytest.raises(HTTPException) as twice:
        await pc.send_campaign(db, payload(send_at="2026-10-27T10:00"), "admin", NOW + timedelta(minutes=1))
    assert twice.value.status_code == 409
    assert await db.scalar(select(func.count(PushCampaign.id))) == 1
