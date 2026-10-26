"""v28.29.0 load test of the payment path on PostgreSQL and Redis.

Hundreds of concurrent confirmations (duplicate webhooks, reconciliation and provider
retries) for many payments must give each payment exactly one paid transition, one ledger
credit and one extension in Remnawave. Runs where AUDIT_TEST_DATABASE_URL and REDIS_URL
point at real servers (CI); LOAD_PAYMENTS / LOAD_DUPLICATES scale it up locally."""
import asyncio
import os
import uuid
from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app import main as shop
from app.models import Base, FinancialLedger, Payment, Plan, Subscription, User

PAYMENTS = int(os.environ.get("LOAD_PAYMENTS", "40"))
DUPLICATES = int(os.environ.get("LOAD_DUPLICATES", "6"))


class Panel:
    """Remnawave stand-in that records every write and keeps expiry per user."""

    def __init__(self):
        self.extends = Counter()
        self.expiry = {}

    async def get_user(self, uid):
        return {"status": "ACTIVE"}

    async def get_expiry(self, uid):
        return self.expiry.get(uid)

    async def update_entitlements(self, *a, **k):
        await asyncio.sleep(0)

    async def extend_idempotent(self, uid, days, before, after):
        current = self.expiry.get(uid)
        if current and current >= after:
            return {"already_applied": True, "expires_at": current}
        await asyncio.sleep(0.01)  # a slow panel widens every race window
        self.extends[uid] += 1
        self.expiry[uid] = after
        return {"expires_at": after}

    async def enable_user(self, uid):
        pass

    async def get_subscription(self, uid):
        return {"subscriptionUrl": f"https://sub.example/{uid}"}


@pytest_asyncio.fixture
async def stack(monkeypatch):
    url, redis_url = os.environ.get("AUDIT_TEST_DATABASE_URL"), os.environ.get("REDIS_URL")
    if not url or not redis_url:
        pytest.skip("load test needs PostgreSQL and Redis")
    from redis.asyncio import Redis
    schema = "load_" + uuid.uuid4().hex
    root = create_async_engine(url)
    async with root.begin() as conn:
        await conn.execute(text(f"CREATE SCHEMA {schema}"))
    engine = create_async_engine(url, pool_size=20, max_overflow=20,
                                 connect_args={"server_settings": {"search_path": schema, "statement_timeout": "20000"}})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    redis = Redis.from_url(redis_url, decode_responses=True)
    now = datetime.utcnow()
    async with AsyncSession(engine, expire_on_commit=False) as db:
        db.add(Plan(id=1, name="Basic", price=100, duration_days=30, traffic_limit_gb=100, device_limit=2))
        for i in range(1, PAYMENTS + 1):
            db.add(User(id=i, referral_code=f"LOAD{i}"))
            db.add(Subscription(id=i, user_id=i, plan_id=1, expires_at=now + timedelta(days=5), lifecycle_status="active",
                                remnawave_uuid=f"remote-{i}", traffic_limit_gb_snapshot=100, device_limit_snapshot=2))
            db.add(Payment(id=i, user_id=i, subscription_id=i, plan_id=1, provider="yookassa", order_id=f"load-{schema}-{i}", amount=100,
                           currency="RUB", status="pending", fulfillment_status="pending", purpose="subscription",
                           duration_days_snapshot=30, traffic_limit_gb_snapshot=100, device_limit_snapshot=2))
        await db.commit()
    panel = Panel()
    monkeypatch.setattr(shop, "redis_client", redis)
    monkeypatch.setattr(shop, "RemnawaveClient", lambda: panel)
    yield engine, panel
    await redis.aclose()
    await engine.dispose()
    async with root.begin() as conn:
        await conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
    await root.dispose()


async def _deliver(engine, payment_id, stats):
    """One webhook delivery; like a provider, retry while another delivery holds the lock."""
    for attempt in range(200):
        try:
            async with AsyncSession(engine, expire_on_commit=False) as db:
                await shop._confirm_and_fulfill_payment(payment_id, db)
            stats["ok"] += 1
            return
        except (HTTPException, RuntimeError) as exc:
            if "in progress" not in str(getattr(exc, "detail", exc)):
                raise
            stats["conflicts"] += 1
            await asyncio.sleep(0.02)
    raise AssertionError(f"payment {payment_id} never got its lock")


@pytest.mark.asyncio
async def test_concurrent_duplicate_confirmations_fulfil_each_payment_once(stack):
    engine, panel = stack
    stats = Counter()
    jobs = [_deliver(engine, pid, stats) for pid in range(1, PAYMENTS + 1) for _ in range(DUPLICATES)]
    started = datetime.utcnow()
    await asyncio.gather(*jobs)
    elapsed = (datetime.utcnow() - started).total_seconds()
    assert stats["ok"] == PAYMENTS * DUPLICATES
    async with AsyncSession(engine) as db:
        states = Counter((await db.execute(select(Payment.status, Payment.fulfillment_status))).all())
        credits = await db.scalar(select(func.count()).select_from(FinancialLedger).where(FinancialLedger.kind == "payment"))
        expiries = (await db.execute(select(Subscription.id, Subscription.expires_at))).all()
    assert states == {("paid", "completed"): PAYMENTS}
    assert credits == PAYMENTS
    assert set(panel.extends.values()) == {1} and len(panel.extends) == PAYMENTS
    for _sid, expires in expiries:  # 5 days left + 30 bought, once
        assert timedelta(days=34, hours=23) < expires - datetime.utcnow() < timedelta(days=35, minutes=5)
    print(f"\n{PAYMENTS * DUPLICATES} deliveries for {PAYMENTS} payments in {elapsed:.1f}s, {stats['conflicts']} lock conflicts retried")
