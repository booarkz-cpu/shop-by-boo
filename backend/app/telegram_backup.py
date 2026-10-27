"""Daily database dump to the owner's private Telegram chat.

At the Moscow time set in «Резервные копии → Копия в Telegram» one worker makes a PostgreSQL dump
(pg_dump -Fc), encrypts it with the backup password (AES-256, openssl, the same as full backups) and sends
it to the chat with sendDocument. Files over Telegram's 50 MB bot limit go in 45 MB parts. Nothing is ever
sent unencrypted: without a backup password the job refuses and tells the owner.

Restore: cat parts > dump.enc; openssl enc -d -aes-256-cbc -pbkdf2 -in dump.enc -out dump.pgc; pg_restore …
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import require_permission

logger = logging.getLogger("vpnshop.telegram_backup")
MSK = ZoneInfo("Europe/Moscow")
CONFIG_KEY = "backup_telegram"
PART_BYTES = 45 * 1024 * 1024
DEFAULT = {"enabled": False, "chat_id": "", "time": "03:30", "last_day": None, "last_result": None, "last_at": None}
router = APIRouter()


class TelegramBackupIn(BaseModel):
    enabled: bool
    chat_id: str = Field(default="", max_length=32, pattern=r"^(-?\d{5,20})?$")
    time: str = Field(default="03:30", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


async def load(db: AsyncSession) -> dict:
    from .main import setting_value
    try:
        value = json.loads(await setting_value(db, CONFIG_KEY, "{}") or "{}")
    except ValueError:
        value = {}
    return {**DEFAULT, **value} if isinstance(value, dict) else dict(DEFAULT)


async def save(db: AsyncSession, value: dict) -> None:
    from .main import set_setting
    await set_setting(db, CONFIG_KEY, json.dumps(value, ensure_ascii=False))


async def pg_dump(target: Path) -> None:
    from .main import _database_cli_config
    cli = _database_cli_config()
    proc = await asyncio.create_subprocess_exec(
        "pg_dump", "-Fc", "-Z", "6", "-h", cli["host"], "-p", cli["port"], "-U", cli["user"], "-d", cli["database"],
        "--no-owner", "--no-privileges", "-f", str(target),
        stderr=asyncio.subprocess.PIPE, env={**os.environ, "PGPASSWORD": cli["password"]})
    _, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"pg_dump failed: {err.decode(errors='ignore')[-500:]}")


async def encrypt(source: Path, target: Path, password: str) -> None:
    proc = await asyncio.create_subprocess_exec("openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-salt", "-in", str(source), "-out", str(target),
                                                "-pass", "stdin", stdin=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    _, err = await proc.communicate((password + "\n").encode())
    if proc.returncode != 0:
        raise RuntimeError(f"Encryption failed: {err.decode(errors='ignore')[-300:]}")


def split(path: Path, part_bytes: int | None = None) -> list[Path]:
    part_bytes = part_bytes or PART_BYTES
    if path.stat().st_size <= part_bytes:
        return [path]
    parts = []
    with path.open("rb") as fh:
        index = 1
        while chunk := fh.read(part_bytes):
            part = path.with_name(f"{path.name}.part{index:02d}")
            part.write_bytes(chunk)
            parts.append(part)
            index += 1
    return parts


async def send_document(client, token: str, chat_id: str, path: Path, caption: str) -> None:
    with path.open("rb") as fh:
        response = await client.post(f"https://api.telegram.org/bot{token}/sendDocument",
                                     data={"chat_id": chat_id, "caption": caption[:1024]},
                                     files={"document": (path.name, fh, "application/octet-stream")})
    if response.status_code >= 400:
        raise RuntimeError(f"Telegram refused the file: HTTP {response.status_code}")


async def run_backup(db: AsyncSession, *, client=None, dump=pg_dump, now: datetime | None = None) -> dict:
    """Dump, encrypt, send. Returns {"parts", "bytes", "sha256"}; raises with a readable reason."""
    import httpx

    from .main import setting_value, settings
    from .security import decrypt_secret
    cfg = await load(db)
    if not cfg["chat_id"] or not settings.bot_token:
        raise RuntimeError("Не задан чат для копий или BOT_TOKEN")
    password_enc = await setting_value(db, "backup_password", "")
    if not password_enc:
        raise RuntimeError("Задайте пароль шифрования копий: без него база в Telegram не отправляется")
    now = now or datetime.now(timezone.utc)
    stamp = now.astimezone(MSK).strftime("%Y%m%d-%H%M")
    with tempfile.TemporaryDirectory(prefix="tg-backup-") as work:
        raw, enc = Path(work) / f"corgi-db-{stamp}.pgc", Path(work) / f"corgi-db-{stamp}.pgc.enc"
        await dump(raw)
        await encrypt(raw, enc, decrypt_secret(password_enc))
        raw.unlink(missing_ok=True)
        digest = hashlib.sha256(enc.read_bytes()).hexdigest()
        size = enc.stat().st_size
        parts = split(enc)
        own = client is None
        client = client or httpx.AsyncClient(timeout=300, trust_env=False)
        try:
            for index, part in enumerate(parts, 1):
                caption = (f"🗄 База Корги Люси {now.astimezone(MSK):%d.%m.%Y %H:%M} МСК, {size / 1024 / 1024:.1f} МБ, зашифрована.\n"
                           f"Часть {index} из {len(parts)}. SHA-256: {digest}") if len(parts) > 1 else (
                           f"🗄 База Корги Люси {now.astimezone(MSK):%d.%m.%Y %H:%M} МСК, {size / 1024 / 1024:.1f} МБ, зашифрована.\nSHA-256: {digest}")
                await send_document(client, settings.bot_token, cfg["chat_id"], part, caption)
        finally:
            if own:
                await client.aclose()
    return {"parts": len(parts), "bytes": size, "sha256": digest}


def due(now: datetime, cfg: dict) -> bool:
    local = now.astimezone(MSK)
    hour, minute = map(int, cfg["time"].split(":"))
    return cfg["enabled"] and (local.hour, local.minute) >= (hour, minute) and cfg.get("last_day") != local.date().isoformat()


async def tick(db: AsyncSession, now: datetime | None = None, **kw) -> str | None:
    """One scheduler check: run once a Moscow day; record the result and alert on failure."""
    from .ops_alerts import send as alert
    now = now or datetime.now(timezone.utc)
    cfg = await load(db)
    if not due(now, cfg):
        return None
    cfg["last_day"] = now.astimezone(MSK).date().isoformat()
    try:
        out = await run_backup(db, now=now, **kw)
        cfg["last_result"] = f"Отправлено: {out['parts']} файл(ов), {out['bytes'] / 1024 / 1024:.1f} МБ"
    except Exception as exc:  # noqa: BLE001
        cfg["last_result"] = f"Ошибка: {str(exc)[:300]}"
        await alert(f"⚠️ Ежедневная копия базы в Telegram не отправлена: {str(exc)[:300]}")
    cfg["last_at"] = now.isoformat()
    await save(db, cfg)
    await db.commit()
    return cfg["last_result"]


async def telegram_backup_scheduler():
    from . import main
    from .db import SessionLocal
    while True:
        try:
            lock = await main.redis_client.set("lock:telegram-backup", "1", nx=True, ex=240) if main.redis_client else True
            if lock:
                async with SessionLocal() as db:
                    await tick(db)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Telegram backup check failed: %s", exc)
        await asyncio.sleep(300)


@router.get("/api/admin/backups/telegram")
async def get_telegram_backup(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("backups.read"))):
    from .main import setting_value
    return {**await load(db), "password_configured": bool(await setting_value(db, "backup_password", ""))}


@router.put("/api/admin/backups/telegram")
async def put_telegram_backup(payload: TelegramBackupIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("backups.write"))):
    from .main import audit
    if payload.enabled and not payload.chat_id:
        raise HTTPException(400, "Укажите ID чата для копий")
    cfg = {**await load(db), **payload.model_dump()}
    await save(db, cfg)
    await audit(db, "backups.telegram.settings", admin.email, None, {"enabled": payload.enabled, "time": payload.time})
    await db.commit()
    return cfg


@router.post("/api/admin/backups/telegram/send-now")
async def send_now(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("backups.write"))):
    from .main import audit
    try:
        out = await run_backup(db)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    await audit(db, "backups.telegram.sent", admin.email, None, out)
    await db.commit()
    return out
