"""Versioned historical import of subscriptions/payments: preview, reconciliation, dedupe and rollback."""
import io
import json
import sqlite3
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy import func, select

from app import admin_customer_operations as operations
from app import history_import as history
from app import main as shop
from app.models import HistoryImportJob, ImportedPayment, ImportedSubscriptionLink, Payment, Subscription, User
from test_subscription_commerce import database

ADMIN = SimpleNamespace(email="admin@example.test", role="admin")
FUTURE = (datetime.utcnow() + timedelta(days=40)).replace(microsecond=0)
PAST = datetime(2024, 1, 5, 12, 0, 0)

USERS = ((7, 9001, "Anna", "0"), (8, 9002, "Boris", "0"))
PAYMENTS = (
    ("p-1", 7, "199.00", "succeeded", "2025-03-01T10:00:00Z"),
    ("p-2", 7, "499.00", "succeeded", 1740823200),
    ("p-3", 8, "199.00", "refunded", "2025-03-02 09:30:00"),
    ("p-4", 8, "199.00", "pending", "2025-03-03T00:00:00"),
)
SUBSCRIPTIONS = (
    (7, FUTURE.isoformat(), "11111111-aaaa-4bbb-8ccc-000000000001", "https://sub.example/a", "Plus"),
    (8, PAST.isoformat(), "11111111-aaaa-4bbb-8ccc-000000000002", None, "Legacy"),
)


def snapshot(tmp_path, payments=PAYMENTS, subscriptions=SUBSCRIPTIONS, users=USERS):
    path = tmp_path / "old-shop.db"
    if path.exists():
        path.unlink()
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE users(id INTEGER, telegram_id INTEGER, username TEXT, balance TEXT)")
        db.execute("CREATE TABLE payments(id TEXT, user_id INTEGER, amount TEXT, state TEXT, created TEXT)")
        db.execute("CREATE TABLE subs(user_id INTEGER, expires TEXT, uuid TEXT, url TEXT, tariff TEXT)")
        db.executemany("INSERT INTO users VALUES (?,?,?,?)", users)
        db.executemany("INSERT INTO payments VALUES (?,?,?,?,?)", payments)
        db.executemany("INSERT INTO subs VALUES (?,?,?,?,?)", subscriptions)
    return path.read_bytes()


def upload(data):
    return UploadFile(file=io.BytesIO(data), filename="old-shop.db")


def mapping(**override):
    base = {
        "namespace": "old-bot", "currency": "RUB", "default_plan_id": 1,
        "payments": {"table": "payments", "id": "id", "user": "user_id", "amount": "amount", "status": "state", "paid_at": "created"},
        "subscriptions": {"table": "subs", "user": "user_id", "expires_at": "expires", "remnawave_uuid": "uuid",
                          "subscription_url": "url", "plan": "tariff"},
        "control": {"payments_count": 3, "payments_total": "698.00", "subscriptions_count": 2},
    }
    base.update(override)
    return base


async def import_profiles(db, data):
    profile_mapping = {"namespace": "old-bot", "table": "users", "source_id": "id", "telegram_id": "telegram_id",
                       "username": "username", "balance": None, "currency": "RUB", "credit_balances": False}
    preview = await operations.import_preview(upload(data), json.dumps(profile_mapping), db, ADMIN)
    await operations.import_apply(preview["id"], operations.ApplyIn(fingerprint=preview["fingerprint"]), db, ADMIN)
    return {row.telegram_id: row for row in (await db.scalars(select(User).where(User.telegram_id.in_([9001, 9002])))).all()}


async def preview(db, data, value=None):
    return await history.preview(upload(data), json.dumps(value or mapping()), db, ADMIN)


async def apply(db, result):
    return await history.apply(result["id"], history.ApplyIn(fingerprint=result["fingerprint"]), db, ADMIN)


async def count(db, model):
    return int(await db.scalar(select(func.count()).select_from(model)))


@pytest.mark.asyncio
async def test_preview_reconciles_without_touching_customer_data(database, tmp_path):
    data = snapshot(tmp_path)
    await import_profiles(database, data)
    before = (await count(database, Subscription), await count(database, ImportedPayment), await count(database, Payment))

    result = await preview(database, data)

    assert result["reconciliation"]["ok"] is True
    assert result["reconciliation"]["skipped_payments"] == 1
    assert result["reconciliation"]["refunded_payments"] == 1
    assert result["payments"]["counts"]["new"] == 3
    assert result["subscriptions"]["counts"]["new"] == 2
    assert result["can_apply"] is True
    assert (await count(database, Subscription), await count(database, ImportedPayment), await count(database, Payment)) == before
    job = await database.get(HistoryImportJob, result["id"])
    assert job.status == "preview" and job.adapter == "generic-sqlite-v1" and '"p-1"' not in job.payload_encrypted  # quoted JSON value; base64 ciphertext never contains quotes


@pytest.mark.asyncio
async def test_control_total_mismatch_blocks_apply(database, tmp_path):
    data = snapshot(tmp_path)
    await import_profiles(database, data)
    result = await preview(database, data, mapping(control={"payments_count": 3, "payments_total": "697.99", "subscriptions_count": 2}))
    assert result["reconciliation"]["ok"] is False
    assert result["can_apply"] is False
    with pytest.raises(HTTPException) as error:
        await apply(database, result)
    assert error.value.status_code == 409
    assert await count(database, ImportedPayment) == 0


@pytest.mark.asyncio
async def test_apply_creates_history_and_subscriptions_without_revenue(database, tmp_path):
    data = snapshot(tmp_path)
    users = await import_profiles(database, data)
    payments_before = await count(database, Payment)

    result = await apply(database, await preview(database, data))

    assert result["payments_created"] == 3 and result["subscriptions_created"] == 2
    assert result["paid_total"] == "698.00"
    assert await count(database, Payment) == payments_before
    anna = users[9001]
    active = await database.scalar(select(Subscription).where(Subscription.remnawave_uuid == "11111111-aaaa-4bbb-8ccc-000000000001"))
    assert active.user_id == anna.id and active.is_primary is True and active.lifecycle_status == "active"
    assert active.plan_id == 2 and active.traffic_limit_gb_snapshot == 200 and active.subscription_url == "https://sub.example/a"
    expired = await database.scalar(select(Subscription).where(Subscription.remnawave_uuid == "11111111-aaaa-4bbb-8ccc-000000000002"))
    assert expired.lifecycle_status == "expired" and expired.plan_id == 1  # unknown tariff -> default plan
    paid = await database.scalar(select(ImportedPayment).where(ImportedPayment.source_payment_id == "p-2"))
    assert paid.paid_at == datetime(2025, 3, 1, 10, 0, 0) and paid.amount == Decimal("499.00")
    history_rows = await history.customer_imported_payments(database, anna.id)
    assert [row["amount"] for row in history_rows] == ["499.00", "199.00"] or {r["amount"] for r in history_rows} == {"499.00", "199.00"}


@pytest.mark.asyncio
async def test_repeat_snapshot_never_duplicates_and_changed_rows_conflict(database, tmp_path):
    data = snapshot(tmp_path)
    await import_profiles(database, data)
    await apply(database, await preview(database, data))

    again = await preview(database, data)
    assert again["payments"]["counts"]["already_imported"] == 3
    assert again["subscriptions"]["counts"]["already_imported"] == 2
    second = await apply(database, again)
    assert second["payments_created"] == 0 and second["subscriptions_created"] == 0
    assert await count(database, ImportedPayment) == 3
    assert await count(database, ImportedSubscriptionLink) == 2

    changed = snapshot(tmp_path, payments=(("p-1", 7, "299.00", "succeeded", "2025-03-01T10:00:00Z"),) + PAYMENTS[1:])
    conflict = await preview(database, changed, mapping(control={"payments_count": 3, "payments_total": "798.00", "subscriptions_count": 2}))
    assert conflict["payments"]["counts"]["conflict"] == 1 and conflict["can_apply"] is False
    with pytest.raises(HTTPException):
        await apply(database, conflict)


@pytest.mark.asyncio
async def test_unknown_customers_and_occupied_remnawave_profiles_block(database, tmp_path):
    data = snapshot(tmp_path, subscriptions=SUBSCRIPTIONS + ((99, FUTURE.isoformat(), "11111111-aaaa-4bbb-8ccc-0000000000ff", None, "Plus"),))
    await import_profiles(database, data)
    database.add(Subscription(user_id=2, plan_id=1, is_primary=True, remnawave_uuid="11111111-AAAA-4bbb-8ccc-000000000002"))
    await database.commit()
    result = await preview(database, data, mapping(control={"payments_count": 3, "payments_total": "698.00", "subscriptions_count": 3}))
    reasons = {row["remnawave_uuid"]: row["reason"] for row in result["subscriptions"]["rows"] if row["status_import"] == "blocked"}
    assert "Клиент не найден" in reasons["11111111-aaaa-4bbb-8ccc-0000000000ff"]
    assert "уже привязан" in reasons["11111111-aaaa-4bbb-8ccc-000000000002"]
    assert result["can_apply"] is False


@pytest.mark.asyncio
async def test_stale_preview_is_rejected(database, tmp_path):
    data = snapshot(tmp_path)
    users = await import_profiles(database, data)
    result = await preview(database, data)
    users[9001].deleted_at = datetime.utcnow()
    await database.commit()
    with pytest.raises(HTTPException) as error:
        await apply(database, result)
    assert error.value.status_code == 409
    assert await count(database, ImportedPayment) == 0


@pytest.mark.asyncio
async def test_rollback_removes_job_rows_and_is_idempotent(database, tmp_path):
    data = snapshot(tmp_path)
    await import_profiles(database, data)
    result = await preview(database, data)
    await apply(database, result)

    rolled = await history.rollback(result["id"], history.RollbackIn(reason="wrong source file"), database, ADMIN)
    assert rolled["payments_removed"] == 3 and rolled["subscriptions_removed"] == 2
    assert await count(database, ImportedPayment) == 0
    assert await count(database, ImportedSubscriptionLink) == 0
    assert await database.scalar(select(Subscription).where(Subscription.remnawave_uuid.like("11111111-%"))) is None
    assert (await history.rollback(result["id"], history.RollbackIn(reason="again"), database, ADMIN))["rolled_back"] is True
    # The same snapshot can be imported again after a rollback.
    reimport = await preview(database, data)
    assert reimport["payments"]["counts"]["new"] == 3


@pytest.mark.asyncio
async def test_rollback_refuses_changed_or_used_subscriptions(database, tmp_path):
    data = snapshot(tmp_path)
    await import_profiles(database, data)
    result = await preview(database, data)
    await apply(database, result)
    active = await database.scalar(select(Subscription).where(Subscription.remnawave_uuid == "11111111-aaaa-4bbb-8ccc-000000000001"))
    active.expires_at = active.expires_at + timedelta(days=30)
    await database.commit()
    with pytest.raises(HTTPException) as error:
        await history.rollback(result["id"], history.RollbackIn(reason="undo"), database, ADMIN)
    assert error.value.status_code == 409 and f"#{active.id}" in error.value.detail
    assert await count(database, ImportedPayment) == 3


@pytest.mark.parametrize("payments,subscriptions", [
    ((("p-1", 7, "1.001", "succeeded", None),), ()),
    ((("p-1", 7, "-5", "succeeded", None),), ()),
    ((("p-1", 7, "10", "succeeded", "yesterday"),), ()),
    ((("p-1", 7, "10", "succeeded", None), ("p-1", 7, "10", "succeeded", None)), ()),
    ((), ((7, "2031-01-01", "11111111-aaaa-4bbb-8ccc-000000000009", "http://insecure", None),)),
    ((), ((7, "2031-01-01", "x'; DROP", None, None),)),
    ((), ((7, "2031-01-01", "11111111-aaaa-4bbb-8ccc-000000000009", None, None), (8, "2031-01-01", "11111111-AAAA-4bbb-8ccc-000000000009", None, None))),
])
def test_invalid_rows_reject_the_whole_snapshot(tmp_path, payments, subscriptions):
    data = snapshot(tmp_path, payments=payments, subscriptions=subscriptions)
    with pytest.raises(HTTPException) as error:
        history.extract(data, history.HistoryMappingIn(**mapping()))
    assert error.value.status_code == 422


def test_mapping_requires_control_totals_and_one_section():
    with pytest.raises(ValueError):
        history.HistoryMappingIn(**mapping(payments=None, subscriptions=None))
    with pytest.raises(ValueError):
        history.HistoryMappingIn(**mapping(control={"subscriptions_count": 2}))
    with pytest.raises(ValueError):
        history.HistoryMappingIn(**mapping(adapter="generic-sqlite-v0"))


def test_migration_chain_points_to_runtime_settings():
    from test_matrix_extension_migrations import migration
    module = migration("0065_history_import")
    assert module.down_revision == "0064_runtime_settings"
