"""Tamper evidence for the audit log: «Журнал действий» → «Целостность журнала».

Every ten minutes the worker seals the audit records written since the previous seal: it stores the range of record
ids, their number and an HMAC-SHA256 over the previous seal and the records themselves. The key is APP_SECRET, which
is not in the database. A record that was changed or deleted afterwards — by anyone who can write to the database but
does not hold the server's secret — breaks the seal of its range, and every later check says which range.

Limits, said plainly: records younger than the last seal (up to ten minutes) are not protected yet; whoever holds the
server's secret can re-seal; the check finds the range, not the single record.

The seals live in ``app_settings`` (``audit.seals``): no schema change.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import get_db
from .security import require_permission

router = APIRouter(prefix="/api/admin/audit-seal")
STATE_KEY = "audit.seals"
DEFAULT = {"seals": [], "verified_at": None, "broken": []}
EVERY_SECONDS = 600
BATCH = 5000       # records in one seal at most
KEEP = 1000        # seals kept apart; older ones are joined

__all__ = ["router", "canonical", "digest", "seal_rows", "check_seal", "join_oldest", "tick"]


def canonical(row) -> str:
    """One audit record as text: the same for the same record, whatever the database driver returns."""
    created = row.created_at.replace(tzinfo=None).isoformat(timespec="microseconds") if row.created_at else ""
    return json.dumps([row.id, row.action, row.actor, row.target, row.details, row.request_id, created], ensure_ascii=False, separators=(",", ":"))


def _keys() -> list[bytes]:
    previous = getattr(settings, "app_secret_previous", None)
    return [s.encode() for s in (settings.app_secret, previous) if s]


def digest(previous: str, rows: list, key: bytes | None = None) -> str:
    mac = hmac.new(key or _keys()[0], b"audit-seal-v1\n" + previous.encode(), hashlib.sha256)
    for row in rows:
        mac.update(b"\n" + hashlib.sha256(canonical(row).encode()).digest())
    return mac.hexdigest()


def _tail(seal: dict) -> str:
    """What the next seal is chained to: the seal's digest, or for a joined seal the digest of its last part."""
    return seal.get("tail") or seal["digest"]


def seal_rows(seals: list[dict], rows: list, now: datetime | None = None) -> dict:
    """The seal for ``rows`` (ordered by id), chained to the last one."""
    previous = _tail(seals[-1]) if seals else ""
    return {"from": rows[0].id, "to": rows[-1].id, "count": len(rows), "prev": previous, "digest": digest(previous, rows),
            "at": (now or datetime.now(UTC)).isoformat(timespec="seconds")}


def check_seal(previous: str, seal: dict, rows: list) -> bool:
    """Whether the records of the seal's range are exactly the ones that were sealed (the previous key is accepted too)."""
    return len(rows) == seal["count"] and any(hmac.compare_digest(digest(previous, rows, key), seal["digest"]) for key in _keys())


async def _rows(db: AsyncSession, after: int, upto: int | None, limit: int | None = None) -> list:
    from .models import AuditLog

    query = select(AuditLog).where(AuditLog.id > after).order_by(AuditLog.id)
    if upto is not None:
        query = query.where(AuditLog.id <= upto)
    return list((await db.scalars(query.limit(limit) if limit else query)).all())


async def seal_new(db: AsyncSession, now: datetime | None = None) -> int:
    """Seals the records written since the last seal; returns how many."""
    from .node_health import _load, _save

    state = await _load(db, STATE_KEY, DEFAULT)
    seals = list(state.get("seals") or [])
    rows = await _rows(db, seals[-1]["to"] if seals else 0, None, BATCH)
    if not rows:
        return 0
    seals.append(seal_rows(seals, rows, now))
    if len(seals) > KEEP:
        seals = await join_oldest(db, seals, KEEP // 2)
    await _save(db, STATE_KEY, {**state, "seals": seals})
    await db.commit()
    return len(rows)


async def join_oldest(db: AsyncSession, seals: list[dict], number: int) -> list[dict]:
    """Replaces the oldest ``number`` seals with one, so that the list does not grow for ever.

    Only seals that still hold are joined: a broken range must stay visible as it is.
    """
    head, edge, rows_all = seals[:number], 0, []
    for seal in head:
        rows = await _rows(db, edge, seal["to"])
        if not check_seal(seal.get("prev", ""), seal, rows):
            return seals
        rows_all.extend(rows)
        edge = seal["to"]
    joined = {"from": head[0]["from"], "to": head[-1]["to"], "count": len(rows_all), "prev": head[0].get("prev", ""),
              "digest": digest(head[0].get("prev", ""), rows_all), "tail": _tail(head[-1]), "at": head[-1]["at"], "joined": len(head)}
    return [joined, *seals[number:]]


async def verify(db: AsyncSession, now: datetime | None = None) -> dict:
    """Recomputes every seal from the records as they are now and remembers the answer."""
    from .models import AuditLog
    from .node_health import _load, _save

    state = await _load(db, STATE_KEY, DEFAULT)
    seals = list(state.get("seals") or [])
    broken, previous, edge = [], "", 0
    for seal in seals:
        rows = await _rows(db, edge, seal["to"])
        # The chain: every seal starts from the one before it, so a removed or replaced seal is seen too.
        if seal.get("prev", "") != previous or not check_seal(previous, seal, rows):
            broken.append({"from": seal["from"], "to": seal["to"], "sealed": seal["count"], "found": len(rows), "sealed_at": seal["at"]})
        previous, edge = _tail(seal), seal["to"]
    unsealed = int(await db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.id > edge)) or 0)
    stamp = (now or datetime.now(UTC)).isoformat(timespec="seconds")
    await _save(db, STATE_KEY, {**state, "seals": seals, "verified_at": stamp, "broken": broken})
    await db.commit()
    return _view({"seals": seals, "verified_at": stamp, "broken": broken}, unsealed)


def _view(state: dict, unsealed: int | None) -> dict:
    seals = state.get("seals") or []
    return {"sealed_records": sum(s["count"] for s in seals), "seals": len(seals), "sealed_upto": seals[-1]["to"] if seals else None,
            "last_seal_at": seals[-1]["at"] if seals else None, "unsealed_records": unsealed,
            "verified_at": state.get("verified_at"), "broken": state.get("broken") or [],
            "intact": bool(state.get("verified_at")) and not state.get("broken"), "every_minutes": EVERY_SECONDS // 60}


_last_tick: datetime | None = None


async def tick(db: AsyncSession, now: datetime | None = None) -> int | None:
    """Called by the worker every minute; seals every ten."""
    global _last_tick
    now = now or datetime.now(UTC)
    if _last_tick is not None and (now - _last_tick).total_seconds() < EVERY_SECONDS:
        return None
    _last_tick = now
    return await seal_new(db, now)


@router.get("")
async def get_state(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("read"))):
    """The seals and the last check, without recomputing."""
    from .models import AuditLog
    from .node_health import _load

    state = await _load(db, STATE_KEY, DEFAULT)
    seals = state.get("seals") or []
    edge = seals[-1]["to"] if seals else 0
    unsealed = int(await db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.id > edge)) or 0)
    return _view(state, unsealed)


@router.post("/verify")
async def post_verify(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("read"))):
    return await verify(db)
