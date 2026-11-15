"""Restore check of a backup: checksum, safe archive, restore into a throwaway PostgreSQL
database and a comparison of the restored data with the shop (v28.29.0).

A copy passes only when the restored database holds at least the customers, subscriptions
and payments the shop had when the copy was started (rows are never deleted from these
tables; anonymised accounts stay). The weekly scheduler checks the latest copy by itself
and a failed check becomes an operator alert."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import pathlib
import secrets
import shutil
import tempfile
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import BackupJob, BackupVerification, Payment, Subscription, User

logger = logging.getLogger(__name__)

TABLES = (("users", User), ("subscriptions", Subscription), ("payments", Payment))  # tables compared after restore
WEEK = timedelta(days=7)
DONE = ("completed", "done", "succeeded", "ok")


async def expected_counts(db: AsyncSession, at: datetime) -> dict[str, int]:
    """Rows the shop already had when the copy started."""
    users = await db.scalar(select(func.count()).select_from(User).where(User.created_at <= at))
    payments = await db.scalar(select(func.count()).select_from(Payment).where(Payment.created_at <= at))
    # Subscriptions carry no creation time: count those a payment made before the copy points at.
    subscriptions = await db.scalar(select(func.count(func.distinct(Payment.subscription_id))).where(
        Payment.created_at <= at, Payment.subscription_id.is_not(None)))
    return {"users": int(users or 0), "subscriptions": int(subscriptions or 0), "payments": int(payments or 0)}


def judge(expected: dict[str, int], restored: dict[str, int]) -> list[str]:
    """Problems found when the restored counts are compared with the shop; empty means passed."""
    problems = []
    for name, _ in TABLES:
        if name not in restored:
            problems.append(f"в копии нет таблицы {name}")
        elif restored[name] < expected.get(name, 0):
            problems.append(f"{name}: в копии {restored[name]}, а в магазине на момент копии было {expected[name]}")
    return problems


async def _psql(cli: dict, database: str, *args: str) -> tuple[int, str, str]:
    env = {**os.environ, "PGPASSWORD": cli["password"]}
    proc = await asyncio.create_subprocess_exec("psql", "-h", cli["host"], "-p", cli["port"], "-U", cli["user"], "-d", database,
                                                "-v", "ON_ERROR_STOP=1", *args, env=env,
                                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, err = await proc.communicate()
    return proc.returncode, out.decode(errors="ignore"), err.decode(errors="ignore")


async def restored_counts(cli: dict, database: str) -> dict[str, int]:
    out = {}
    for name, _ in TABLES:
        code, text, _err = await _psql(cli, database, "-tAc", f"SELECT count(*) FROM {name}")
        if code == 0 and text.strip().isdigit():
            out[name] = int(text.strip())
    return out


async def verify(db: AsyncSession, backup_id: int, actor: str) -> dict:
    """Run the full check of one copy and store the result in backup_verifications."""
    from . import main as shop
    backup = await db.get(BackupJob, backup_id)
    if not backup or not backup.filename:
        from fastapi import HTTPException
        raise HTTPException(404, "Backup не найден")
    record = BackupVerification(backup_id=backup_id, status="running", checksum_ok=None, archive_safe=None, restore_tested=False)
    db.add(record)
    await db.commit()
    await db.refresh(record)
    temp_db = f"vpnshop_restore_test_{secrets.token_hex(6)}"
    work = pathlib.Path(tempfile.mkdtemp(prefix="backup-test-"))
    cli = None
    result: dict = {"status": "failed", "backup_id": backup_id}
    try:
        path = shop._backup_path(backup.filename)
        if not path.is_file():
            raise FileNotFoundError("Файл копии не найден")
        digest = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                digest.update(chunk)
        record.checksum_ok = not backup.sha256 or digest.hexdigest() == backup.sha256
        if not record.checksum_ok:
            raise ValueError("Контрольная сумма копии не совпадает")
        source = path
        if backup.encrypted:
            password_enc = await shop.setting_value(db, "backup_password", "")
            if not password_enc:
                raise ValueError("Пароль резервных копий не настроен")
            from .security import decrypt_secret
            source = work / "backup.tar.gz"
            proc = await asyncio.create_subprocess_exec("openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2", "-in", str(path), "-out", str(source),
                                                        "-pass", "stdin", stdin=asyncio.subprocess.PIPE,
                                                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            await proc.communicate((decrypt_secret(password_enc) + "\n").encode())
            if proc.returncode != 0:
                raise ValueError("Не удалось расшифровать копию")
        import tarfile
        with tarfile.open(source, "r:gz") as tf:
            shop._validate_tar_safety(tf)
            member = next((m for m in tf.getmembers() if m.name == "database.sql"), None)
            if not member or not member.isfile():
                raise ValueError("В копии нет файла database.sql")
            shop._safe_extract_members(tf, {"database.sql"}, work)
        record.archive_safe = True
        await db.commit()
        # Restore into a disposable database, never into the shop's own one.
        cli = shop._database_cli_config()
        code, _out, err = await _psql(cli, cli["database"], "-c", f'CREATE DATABASE "{temp_db}"')
        if code != 0:
            raise RuntimeError("Не удалось создать временную базу: " + err[-300:])
        code, _out, err = await _psql(cli, temp_db, "-q", "-f", str(work / "database.sql"))
        if code != 0:
            raise RuntimeError("Восстановление завершилось ошибкой: " + err[-500:])
        expected = await expected_counts(db, backup.created_at)
        restored = await restored_counts(cli, temp_db)
        problems = judge(expected, restored)
        result = {"backup_id": backup_id, "expected": expected, "restored": restored, "problems": problems,
                  "checksum_ok": True, "archive_safe": True, "isolated_database": True}
        if problems:
            raise ValueError("; ".join(problems))
        record.restore_tested = True
        record.status = "passed"
        result["status"] = "passed"
        result["restore_tested"] = True
    except Exception as exc:
        logger.warning("Backup restore check failed for %s: %s", backup_id, exc)
        record.status = "failed"
        record.error = str(exc)[:1000]
        result.update({"status": "failed", "restore_tested": False, "error": str(exc)[:300],
                       "checksum_ok": record.checksum_ok, "archive_safe": record.archive_safe})
    finally:
        record.finished_at = datetime.utcnow()
        await shop.audit(db, "backup.test_restore", actor, str(backup_id), {"status": result["status"]})
        await db.commit()
        if cli:
            await _psql(cli, cli["database"], "-c", f'DROP DATABASE IF EXISTS "{temp_db}"')
        shutil.rmtree(work, ignore_errors=True)
    return result


async def due_backup(db: AsyncSession, now: datetime) -> BackupJob | None:
    """The latest finished copy, if no copy was checked during the last week."""
    recent = await db.scalar(select(BackupVerification.id).where(BackupVerification.created_at >= now - WEEK).limit(1))
    if recent:
        return None
    return await db.scalar(select(BackupJob).where(BackupJob.status.in_(DONE), BackupJob.filename.is_not(None))
                           .order_by(BackupJob.id.desc()).limit(1))


async def restore_check_scheduler(session_factory=None):
    from sqlalchemy.ext.asyncio import AsyncSession as Session
    from .db import engine
    factory = session_factory or (lambda: Session(engine, expire_on_commit=False))
    await asyncio.sleep(600)
    while True:
        try:
            async with factory() as db:
                backup = await due_backup(db, datetime.utcnow())
                if backup:
                    await verify(db, backup.id, "system:weekly-restore-check")
        except Exception:
            logger.exception("weekly restore check failed")
        await asyncio.sleep(3600)
