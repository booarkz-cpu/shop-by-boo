"""1.0.0 integrity contracts, checked by running the code (was: code lines searched in main.py, models.py and a migration)."""
import asyncio
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

from app import main as shop
from app.models import Payment
from app_contract import tables
from test_behaviour_payments_v2 import FakeRedis
from test_subscription_commerce import database  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]


def test_release_version_and_migration_head():
    assert '"version": "1.0.0-realise"' in (ROOT / 'release-manifest.template.json').read_text()


@pytest.mark.asyncio
async def test_payment_idempotency_is_database_enforced(database):
    unique = {tuple(c.name for c in con.columns) for con in tables()["payments"].constraints if con.__class__.__name__ == "UniqueConstraint"}
    assert ("user_id", "idempotency_key") in unique
    row = dict(user_id=1, plan_id=1, provider="yookassa", amount=Decimal("100"), currency="RUB", status="pending", idempotency_key="same-key")
    database.add_all([Payment(order_id="o-a", **row), Payment(order_id="o-b", **row)])
    with pytest.raises(IntegrityError):
        await database.commit()


@pytest.mark.asyncio
async def test_a_distributed_lock_is_exclusive_and_released_by_its_owner(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(shop, "redis_client", redis)
    key, token = await shop._acquire_redis_lock("lock:backup", ttl=3600, conflict_message="A backup is already running")
    with pytest.raises(RuntimeError, match="A backup is already running"):
        await shop._acquire_redis_lock("lock:backup", ttl=3600, conflict_message="A backup is already running")
    assert token in shop._LOCK_RENEW_TASKS, "a long operation keeps renewing its lease"
    await shop._release_payment_side_effect_lock(key, "someone-else")
    assert "lock:backup" in redis.keys, "only the owner releases"
    await shop._release_payment_side_effect_lock(key, token)
    assert "lock:backup" not in redis.keys and token not in shop._LOCK_RENEW_TASKS
    await asyncio.sleep(0)
    key, token = await shop._acquire_redis_lock("lock:backup", ttl=3600, conflict_message="busy")
    await shop._release_payment_side_effect_lock(key, token)


@pytest.mark.asyncio
async def test_without_redis_locks_refuse_instead_of_running_unprotected(monkeypatch):
    monkeypatch.setattr(shop, "redis_client", None)
    with pytest.raises(RuntimeError, match="Redis is required"):
        await shop._acquire_redis_lock("lock:maintenance", ttl=1800, conflict_message="busy")


@pytest.mark.asyncio
async def test_advisory_locks_serialise_on_postgresql_only(database):
    await shop._advisory_lock(database, 1300000001)  # SQLite: a no-op; PostgreSQL: pg_advisory_xact_lock
    await database.commit()
