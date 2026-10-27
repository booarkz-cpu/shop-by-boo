"""Push campaigns by segment and anonymous app analytics, driven through the real queries."""
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app import app_growth as growth
from app.models import AppEvent, Base, Notification, Payment, Plan, PushDevice, Subscription, User, UserSession

NOW = datetime(2026, 10, 26, 12, 0)


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        session.add(Plan(id=1, name="Month", price=100, duration_days=30, traffic_limit_gb=0, device_limit=3))
        for uid in range(1, 8):
            session.add(User(id=uid, referral_code=f"U{uid}"))
        session.add_all([
            # 1: expires in 2 days; 2: expires in 2 days but has a long second subscription; 3: long subscription
            Subscription(user_id=1, plan_id=1, expires_at=NOW + timedelta(days=2), lifecycle_status="active", is_primary=True),
            Subscription(user_id=2, plan_id=1, expires_at=NOW + timedelta(days=2), lifecycle_status="active", is_primary=True),
            Subscription(user_id=2, plan_id=1, expires_at=NOW + timedelta(days=200), lifecycle_status="active", is_primary=False),
            Subscription(user_id=3, plan_id=1, expires_at=NOW + timedelta(days=40), lifecycle_status="active", is_primary=True),
            # 4: expired 5 days ago
            Subscription(user_id=4, plan_id=1, expires_at=NOW - timedelta(days=5), lifecycle_status="expired", is_primary=True),
        ])
        # 5, 6 never bought; 7 is deleted
        session.add(UserSession(user_id=5, jti_hash="a" * 64, expires_at=NOW + timedelta(hours=1), last_seen_at=NOW - timedelta(days=20)))
        session.add(UserSession(user_id=1, jti_hash="c" * 64, expires_at=NOW + timedelta(hours=1), last_seen_at=NOW - timedelta(days=1)))
        session.add(UserSession(user_id=6, jti_hash="b" * 64, expires_at=NOW + timedelta(hours=1), last_seen_at=NOW - timedelta(hours=2)))
        for uid in (1, 5, 6):
            session.add(PushDevice(user_id=uid, platform="android", provider="fcm", token_hash=str(uid) * 64, token_encrypted="x"))
        await session.commit()
        (await session.get(User, 7)).deleted_at = NOW
        await session.commit()
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_segments(db):
    seg = lambda name, days=3: growth.segment_users(db, name, days, NOW)
    assert await seg("all") == [1, 2, 3, 4, 5, 6], "deleted accounts never receive campaigns"
    assert await seg("expiring") == [1], "a second, longer subscription keeps the customer out"
    assert await seg("expiring", 60) == [1, 3]
    assert await seg("expired", 7) == [4]
    assert await seg("expired", 3) == []
    assert await seg("no_subscription") == [5, 6]
    assert await seg("app_users") == [1, 5, 6]
    assert await seg("inactive", 14) == [5], "only app users without a session seen in N days"
    with pytest.raises(HTTPException):
        await seg("everyone-else")


@pytest.mark.asyncio
async def test_campaign_creates_one_notification_per_recipient(db):
    payload = growth.CampaignIn(segment="no_subscription", title="  Попробуйте   бесплатно ", body="Три дня")
    row = await growth.send_campaign(db, payload, "admin@example.test", NOW)
    await db.commit()
    assert (row.recipients, row.with_push, row.title, row.status) == (2, 2, "Попробуйте бесплатно", "sent")
    notes = (await db.execute(select(Notification).order_by(Notification.user_id))).scalars().all()
    assert [(n.user_id, n.kind, n.dedupe_key) for n in notes] == [(5, "campaign", f"campaign:{row.id}"), (6, "campaign", f"campaign:{row.id}")]
    assert all(n.push_fanout_at is None for n in notes), "the push worker fans them out"
    with pytest.raises(HTTPException):
        await growth.send_campaign(db, growth.CampaignIn(segment="all", title=" ", body="x"), "admin", NOW)
    with pytest.raises(HTTPException) as twice:
        await growth.send_campaign(db, payload, "admin@example.test", NOW + timedelta(minutes=1))
    assert twice.value.status_code == 409, "a second click does not message everyone again"
    later = await growth.send_campaign(db, payload, "admin@example.test", NOW + timedelta(minutes=growth.REPEAT_GUARD_MINUTES + 1))
    assert later.recipients == 2


def events(install="install-0000000001", platform="android", *items):
    return growth.EventsIn(install_id=install, platform=platform, app_version="3.1.0",
                           events=[growth.EventIn(event=e, screen=s) for e, s in items])


@pytest.mark.asyncio
async def test_events_and_funnel(db):
    assert await growth.record_events(db, events("install-0000000001", "android", ("install", ""), ("open", ""), ("screen", "premium"),
                                                 ("connect_tap", ""), ("checkout_start", ""), ("hack", "")), None, NOW) == 5
    assert await growth.record_events(db, events("install-0000000001", "android", ("install", "")), None, NOW) == 0, "install counts once"
    await growth.record_events(db, events("install-0000000002", "ios", ("install", ""), ("sign_in", ""), ("screen", "vpn")), 1, NOW)
    await db.commit()
    stored = (await db.execute(select(AppEvent.install_hash).distinct())).scalars().all()
    assert len(stored) == 2 and all(len(h) == 64 and "install-" not in h for h in stored), "only a keyed hash is stored"
    db.add(Payment(user_id=1, plan_id=1, provider="sandbox", order_id="o1", amount=Decimal("100"), currency="RUB", status="paid",
                   idempotency_key="k1", created_at=NOW))
    await db.commit()
    data = await growth.summary(db, 30, now=NOW + timedelta(hours=1))
    funnel = {f["step"]: f["count"] for f in data["funnel"]}
    assert funnel == {"install": 2, "sign_in": 1, "connect_tap": 1, "checkout_start": 1, "paid": 1}
    assert data["active_installs"] == 2 and data["platforms"] == {"android": 1, "ios": 1}
    screens = {s["screen"]: s for s in data["screens"]}
    assert screens["premium"]["to_checkout"] == 100.0 and screens["vpn"]["to_checkout"] == 0.0
    ios = await growth.summary(db, 30, "ios", now=NOW + timedelta(hours=1))
    assert {f["step"]: f["count"] for f in ios["funnel"]}["install"] == 1
    old = await growth.summary(db, 1, now=NOW + timedelta(days=3))
    assert old["active_installs"] == 0


@pytest.mark.asyncio
async def test_disabled_analytics_drops_events(db, monkeypatch):
    async def off(session):
        return False
    monkeypatch.setattr(growth, "analytics_enabled", off)
    from starlette.requests import Request
    from fastapi import Response
    request = Request({"type": "http", "method": "POST", "path": "/api/mobile/events", "headers": [], "query_string": b""})
    answer = await growth.collect_events(events("install-0000000003", "android", ("install", "")), request, Response(), db)
    assert answer == {"accepted": 0, "enabled": False}
    assert await db.scalar(select(func.count(AppEvent.id))) == 0


@pytest.mark.asyncio
async def test_cleanup_keeps_180_days(db):
    db.add_all([AppEvent(install_hash="h" * 64, platform="ios", event="open", created_at=NOW - timedelta(days=200)),
                AppEvent(install_hash="h" * 64, platform="ios", event="open", created_at=NOW - timedelta(days=10))])
    await db.commit()
    assert await growth.cleanup(db, NOW) == 1


@pytest.mark.asyncio
async def test_expiry_reminder_reaches_every_customer_once(db, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "notification_expiry_days", 3)
    assert await growth.enqueue_expiry_notifications(db, NOW) == 2, "users 1 and 2: a profile expires in 2 days, no Telegram needed"
    assert await growth.enqueue_expiry_notifications(db, NOW) == 0, "once per subscription and date"
    row = (await db.execute(select(Notification).where(Notification.kind == "subscription_expiring", Notification.user_id == 1))).scalar_one()
    assert row.user_id == 1 and "осталось 2 дн." in row.body and row.push_fanout_at is None


@pytest.mark.asyncio
async def test_one_installation_cannot_flood_the_events(db, monkeypatch):
    monkeypatch.setattr(growth, "DAILY_LIMIT", 3)
    batch = events("install-0000000009", "android", *[("open", "")] * 5)
    assert await growth.record_events(db, batch, None, NOW) == 3
    await db.commit()
    assert await growth.record_events(db, batch, None, NOW + timedelta(hours=1)) == 0
    await db.commit()
    assert await growth.record_events(db, batch, None, NOW + timedelta(days=2)) == 3, "the limit is per day"
