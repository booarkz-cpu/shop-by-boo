"""Daily snapshots of the servers (v28.92.0, stage 20, N7 «Настроить автобекапы»).

At the Moscow time set in «Установка → Снапшоты серверов» the worker queues the «snapshot» action of every installation
still in place (the same plan an administrator starts by hand: a copy of the panel's database and the files of the
components, encrypted in the shop; the newest 10 copies of the database and 5 of the files are kept). When a run has
finished and «в Telegram» is on, its files are re-encrypted with the backup password (as the shop's own copies) and
sent to the backup chat of «Резервные копии → Копия в Telegram». Nothing is sent without the password.
"""
from __future__ import annotations

import logging
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .models import RemnawaveInstallation
from .security import require_permission

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin/install/snapshots-schedule")
KEY, STATE_KEY = "rw.snapshots", "rw.snapshots.state"
DEFAULT = {"enabled": False, "time": "04:00", "telegram": False}
MSK = ZoneInfo("Europe/Moscow")
WINDOW = timedelta(hours=2)
ACTOR = "snapshots"
FINAL = ("succeeded", "failed", "cancelled")


class ScheduleIn(BaseModel):
    enabled: bool
    time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    telegram: bool = False


async def _load(db: AsyncSession, key: str, default: dict) -> dict:
    from .node_health import _load as load
    return await load(db, key, default)


async def _save(db: AsyncSession, key: str, value: dict) -> None:
    from .node_health import _save as save
    await save(db, key, value)


def due(cfg: dict, state: dict, now: datetime) -> bool:
    local = now.astimezone(MSK)
    hh, mm = (int(x) for x in cfg["time"].split(":"))
    start = local.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return cfg["enabled"] and start <= local < start + WINDOW and state.get("last_run_date") != local.date().isoformat()


async def send_files(db: AsyncSession, row: RemnawaveInstallation, *, client=None) -> int:
    """The files of a finished snapshot to the backup chat, encrypted with the backup password."""
    from . import telegram_backup
    from .main import setting_value, settings
    from .rw_steps import panel_copies_dir, unseal
    from .security import decrypt_secret
    cfg = await telegram_backup.load(db)
    password = await setting_value(db, "backup_password", "")
    if not cfg["chat_id"] or not settings.bot_token or not password:
        raise RuntimeError("Для отправки в Telegram нужны чат копий, BOT_TOKEN и пароль шифрования копий")
    state = (row.result or {}).get("state") or {}
    names = list((state.get("snapshots") or {}).values()) + ([state["last_panel_copy"]["file"]] if (state.get("last_panel_copy") or {}).get("file") else [])
    import httpx
    own = client is None
    client = client or httpx.AsyncClient(timeout=300, trust_env=False)
    sent = 0
    try:
        with tempfile.TemporaryDirectory(prefix="rw-snapshot-") as work:
            for name in names:
                source = panel_copies_dir() / name
                if not source.is_file():
                    continue
                raw = Path(work) / name.removesuffix(".enc")
                raw.write_bytes(unseal(source.read_bytes()))
                enc = raw.with_name(raw.name + ".enc")
                await telegram_backup.encrypt(raw, enc, decrypt_secret(password))
                raw.unlink(missing_ok=True)
                for part in telegram_backup.split(enc):
                    await telegram_backup.send_document(client, settings.bot_token, cfg["chat_id"], part,
                                                        f"🖥 Снапшот сервера: {name.removesuffix('.enc')}, зашифрован паролем копий")
                    sent += 1
    finally:
        if own:
            await client.aclose()
    return sent


async def tick(db: AsyncSession, now: datetime | None = None, *, client=None) -> dict:
    from .rw_autoupdate import installations, schedule_update
    now = now or datetime.now(timezone.utc)
    cfg = await _load(db, KEY, DEFAULT)
    state = await _load(db, STATE_KEY, {"last_run_date": None, "watch": [], "last": None})
    report = {"queued": [], "sent": 0, "errors": []}
    if due(cfg, state, now):
        state["last_run_date"] = now.astimezone(MSK).date().isoformat()
        for item in await installations(db):
            if item["busy"]:
                report["errors"].append(f"#{item['id']}: занята другой операцией")
                continue
            try:
                row = await schedule_update(db, item["id"], ACTOR, action="snapshot")
            except HTTPException as exc:
                report["errors"].append(f"#{item['id']}: {exc.detail}")
                continue
            state["watch"].append(row.id)
            report["queued"].append(row.id)
    still = []
    for rid in state.get("watch") or []:
        row = await db.get(RemnawaveInstallation, rid)
        if row is None:
            continue
        if row.status not in FINAL:
            still.append(rid)
            continue
        if row.status == "succeeded" and cfg["telegram"]:
            try:
                report["sent"] += await send_files(db, row, client=client)
            except Exception as exc:  # noqa: BLE001 — the reason goes to the section, the copies stay in the shop
                report["errors"].append(f"#{row.id}: {exc}")
    state["watch"] = still
    if report["queued"] or report["sent"] or report["errors"]:
        state["last"] = {"at": now.replace(microsecond=0).isoformat(), **report}
    await _save(db, STATE_KEY, state)
    await db.commit()
    return report


@router.get("")
async def get_schedule(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("backups.read"))):
    return {**await _load(db, KEY, DEFAULT), "state": await _load(db, STATE_KEY, {"last_run_date": None, "watch": [], "last": None})}


@router.put("")
async def put_schedule(payload: ScheduleIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("backups.write"))):
    from .main import audit
    await _save(db, KEY, payload.model_dump())
    await audit(db, "install.snapshots.schedule", admin.email, None, payload.model_dump())
    await db.commit()
    return await get_schedule(db, admin)
