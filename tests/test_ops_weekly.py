"""v28.29.0: weekly owner summary and the restore check of backups."""
import io
import os
import tarfile
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from urllib.parse import urlparse

import pytest

from app import backup_verify, ops_alerts
from app import main as shop
from app.models import AppSetting, BackupJob, BackupVerification, Payment, RefundRequest, Subscription, User
from test_subscription_commerce import database  # noqa: F401


def _paid(order, amount, paid_at, user_id=1, provider="yookassa", currency="RUB"):
    return Payment(user_id=user_id, subscription_id=1, plan_id=1, provider=provider, order_id=order, amount=amount, currency=currency,
                   status="paid", fulfillment_status="completed", paid_at=paid_at, purpose="subscription", duration_days_snapshot=30)


@pytest.mark.asyncio
async def test_weekly_summary_counts_the_last_seven_days(database):
    db = database
    now = datetime(2026, 11, 2, 7, 0)  # Monday 10:00 Moscow
    db.add_all([_paid("w-1", 199, now - timedelta(days=1)), _paid("w-2", 299, now - timedelta(days=3), user_id=2),
                _paid("old-1", 999, now - timedelta(days=12)),
                _paid("wallet-1", 50, now - timedelta(days=1), provider="wallet")])  # wallet spend is not new money
    await db.flush()
    db.add(RefundRequest(payment_id=(await db.scalar(shop.select(Payment.id).where(Payment.order_id == "w-2"))), user_id=2, amount=Decimal("299"),
                         status="refunded", updated_at=now - timedelta(days=1)))
    sub = await db.get(Subscription, 1)
    sub.expires_at = now - timedelta(days=2)
    await db.commit()
    s = await ops_alerts.weekly_summary(db, now)
    assert s["revenue"] == {"RUB": "498.00"} or s["revenue"] == {"RUB": "498"}
    assert s["payments"] == 2 and s["new_paying"] == 1  # user 1 first paid 12 days ago
    assert s["ended"] == 1 and s["refunds"]["count"] == 1
    text = ops_alerts.summary_text(s)
    assert text.startswith("📊 Неделя 26.10–02.11") and "оплат: 2" in text and "Возвраты: 1" in text


def test_summary_goes_out_on_monday_morning_once_a_week():
    monday = datetime(2026, 11, 2, 6, 5)
    assert ops_alerts.summary_due(monday, None)
    assert not ops_alerts.summary_due(monday, "2026-45")
    assert not ops_alerts.summary_due(monday.replace(hour=5), None)
    assert not ops_alerts.summary_due(monday + timedelta(days=1), None)


@pytest.mark.asyncio
async def test_summary_is_sent_once_and_retried_after_a_failed_send(database):
    sent = []

    async def ok(text):
        sent.append(text)
        return True

    async def down(text):
        return False
    monday = datetime(2026, 11, 2, 6, 30)
    assert not await ops_alerts.send_weekly_summary(database, monday, down)
    assert await database.get(AppSetting, ops_alerts.SUMMARY_KEY) is None
    assert await ops_alerts.send_weekly_summary(database, monday, ok)
    assert not await ops_alerts.send_weekly_summary(database, monday + timedelta(hours=3), ok)
    assert len(sent) == 1


def test_restore_judge_compares_with_the_shop():
    expected = {"users": 10, "subscriptions": 4, "payments": 7}
    assert backup_verify.judge(expected, {"users": 12, "subscriptions": 4, "payments": 9}) == []
    problems = backup_verify.judge(expected, {"users": 10, "payments": 3})
    assert any("subscriptions" in p for p in problems) and any("payments: в копии 3" in p for p in problems)


@pytest.mark.asyncio
async def test_a_failed_restore_check_becomes_an_alert_and_is_checked_weekly(database):
    db = database
    now = datetime.utcnow()
    db.add(BackupJob(id=5, status="completed", filename="b.tar.gz", created_at=now - timedelta(days=1)))
    await db.commit()
    assert (await backup_verify.due_backup(db, now)).id == 5
    db.add(BackupVerification(backup_id=5, status="failed", error="users: в копии 0", created_at=now - timedelta(hours=1)))
    await db.commit()
    assert await backup_verify.due_backup(db, now) is None  # checked this week
    keys = [p.key for p in await ops_alerts.collect(db, now)]
    assert any(k.startswith("restore:") for k in keys)


def _archive(tmp_path, sql: str) -> tuple[str, str]:
    data = sql.encode()
    path = tmp_path / "backup.tar.gz"
    with tarfile.open(path, "w:gz") as tf:
        info = tarfile.TarInfo("database.sql")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    import hashlib
    return str(path), hashlib.sha256(path.read_bytes()).hexdigest()


def _cli():
    url = os.environ.get("AUDIT_TEST_DATABASE_URL")
    if not url:
        pytest.skip("restore into PostgreSQL runs where AUDIT_TEST_DATABASE_URL is set")
    u = urlparse(url.replace("postgresql+asyncpg://", "postgresql://"))
    return {"host": u.hostname, "port": str(u.port or 5432), "user": u.username, "password": u.password, "database": u.path.lstrip("/")}


@pytest.mark.asyncio
@pytest.mark.parametrize("users,passes", [(3, True), (1, False)])
async def test_restore_check_restores_into_a_throwaway_database(database, tmp_path, monkeypatch, users, passes):
    cli = _cli()
    db = database
    rows = ",".join(f"({i})" for i in range(users))
    sql = ("CREATE TABLE users (id int); CREATE TABLE subscriptions (id int); CREATE TABLE payments (id int);\n"
           f"INSERT INTO users VALUES {rows}; INSERT INTO subscriptions VALUES (1);\n")
    path, digest = _archive(tmp_path, sql)
    db.add(BackupJob(id=9, status="completed", filename="backup.tar.gz", sha256=digest, created_at=datetime.utcnow() + timedelta(seconds=5)))
    await db.commit()
    monkeypatch.setattr(shop, "_backup_path", lambda name: tmp_path / name)
    monkeypatch.setattr(shop, "_database_cli_config", lambda: cli)
    out = await backup_verify.verify(db, 9, "test")
    assert (out["status"] == "passed") is passes, out
    assert out["expected"] == {"users": 2, "subscriptions": 0, "payments": 0} and out["restored"]["users"] == users
    record = await db.scalar(shop.select(BackupVerification).where(BackupVerification.backup_id == 9))
    assert record.status == ("passed" if passes else "failed") and record.restore_tested is passes
    code, text, _ = await backup_verify._psql(cli, cli["database"], "-tAc", "SELECT count(*) FROM pg_database WHERE datname LIKE 'vpnshop_restore_test_%'")
    assert text.strip() == "0"  # the throwaway database is always dropped
