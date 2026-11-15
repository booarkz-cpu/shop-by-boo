"""System error log: errors of the API, workers and bot kept in the database, grouped, visible in the admin.

Alert delivery to Telegram can itself fail (that is exactly when errors matter most), so ERROR records are also
stored: a logging handler puts them in a queue, a background task writes them in batches, grouped by fingerprint
(logger + message without numbers + the last traceback frame) with a counter. Secrets are masked. Records older
than 30 days are removed. «Мониторинг → Журнал ошибок» (web) and the mobile admin card.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import traceback as tb
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import require_permission

router = APIRouter()
_queue: asyncio.Queue | None = None
RETENTION = timedelta(days=30)
SECRET = re.compile(r"(?i)(token|secret|password|passwd|api[_-]?key|authorization|bearer)([\"'=:\s]+)([^\s\"',;]{4,})")
BOT_TOKEN = re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b")
NUMBERS = re.compile(r"\d+")


def redact(text: str) -> str:
    return BOT_TOKEN.sub("***", SECRET.sub(lambda m: m.group(1) + m.group(2) + "***", text or ""))


def fingerprint(logger: str, message: str, trace: str) -> str:
    last = [line for line in trace.strip().splitlines() if line.strip().startswith("File ")][-1:] if trace else []
    return hashlib.sha256("|".join([logger, NUMBERS.sub("#", message)[:300], *last]).encode()).hexdigest()


class DatabaseHandler(logging.Handler):
    def __init__(self):
        super().__init__(logging.ERROR)

    def emit(self, record: logging.LogRecord) -> None:
        if _queue is None or record.name.startswith(("sqlalchemy", "vpnshop.error_log")):
            return
        try:
            trace = "".join(tb.format_exception(*record.exc_info)) if record.exc_info else ""
            item = {"level": record.levelname, "logger": record.name[:120], "message": redact(record.getMessage())[:4000],
                    "traceback": redact(trace)[-8000:], "process": os.environ.get("APP_PROCESS", "api")[:32],
                    "at": datetime.utcnow()}
            _queue.put_nowait(item)
        except Exception:  # noqa: BLE001 — logging must never raise
            self.handleError(record)


async def store(db: AsyncSession, items: list[dict]) -> int:
    from .models import SystemErrorLog
    for item in items:
        fp = fingerprint(item["logger"], item["message"], item["traceback"])
        row = await db.scalar(select(SystemErrorLog).where(SystemErrorLog.fingerprint == fp))
        if row:
            row.count += 1
            row.last_seen = item["at"]
            row.message = item["message"]
            row.resolved = False
        else:
            db.add(SystemErrorLog(fingerprint=fp, level=item["level"], logger=item["logger"], message=item["message"],
                                  traceback=item["traceback"], process=item["process"], first_seen=item["at"], last_seen=item["at"]))
        await db.flush()
    await db.commit()
    return len(items)


async def _writer():
    from .db import SessionLocal
    from .models import SystemErrorLog
    while True:
        item = await _queue.get()
        batch = [item]
        await asyncio.sleep(2)
        while not _queue.empty() and len(batch) < 200:
            batch.append(_queue.get_nowait())
        try:
            async with SessionLocal() as db:
                await store(db, batch)
                await db.execute(delete(SystemErrorLog).where(SystemErrorLog.last_seen < datetime.utcnow() - RETENTION))
                await db.commit()
        except Exception as exc:  # noqa: BLE001 — the database may be the failing part; keep the stderr trail
            logging.getLogger("vpnshop.error_log").warning("error log write failed: %s", exc)


def install() -> None:
    global _queue
    if _queue is not None:
        return
    _queue = asyncio.Queue(maxsize=5000)
    logging.getLogger().addHandler(DatabaseHandler())
    asyncio.create_task(_writer())


router.add_event_handler("startup", install)


@router.get("/api/admin/errors")
async def list_errors(resolved: bool = False, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("ops.diagnostics"))):
    from .models import SystemErrorLog
    rows = (await db.execute(select(SystemErrorLog).where(SystemErrorLog.resolved.is_(resolved))
                             .order_by(SystemErrorLog.last_seen.desc()).limit(200))).scalars().all()
    total = await db.scalar(select(func.count()).select_from(SystemErrorLog).where(SystemErrorLog.resolved.is_(False)))
    return {"open": int(total or 0), "items": [{"id": r.id, "level": r.level, "logger": r.logger, "message": r.message,
                                                "traceback": r.traceback, "process": r.process, "count": r.count,
                                                "first_seen": r.first_seen.isoformat(), "last_seen": r.last_seen.isoformat(),
                                                "resolved": r.resolved} for r in rows]}


@router.post("/api/admin/errors/{error_id}/resolve")
async def resolve_error(error_id: int, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("ops.diagnostics"))):
    from .models import SystemErrorLog
    row = await db.get(SystemErrorLog, error_id)
    if not row:
        raise HTTPException(404, "Ошибка не найдена")
    row.resolved = True
    await db.commit()
    return {"ok": True}


@router.post("/api/admin/errors/resolve-all")
async def resolve_all(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("ops.diagnostics"))):
    from sqlalchemy import update

    from .models import SystemErrorLog
    result = await db.execute(update(SystemErrorLog).where(SystemErrorLog.resolved.is_(False)).values(resolved=True))
    await db.commit()
    return {"resolved": result.rowcount}
