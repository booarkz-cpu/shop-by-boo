"""Who in the shop calls the Remnawave API and how often: hourly sums by entry point, method and path.

Every call of ``RemnawaveClient._request`` (and every subscription fetched by the proxy) is counted in memory —
calls, errors, total time — by **source** (``customer``, ``admin``, ``subscription``, ``webhook``, ``background``…,
set per request or task through ``SOURCE``) and a **path template** (ids, UUIDs and short ids become ``{x}``). The
sums go to ``panel_api_stats`` once a minute, after the answers; nothing is written on the request path.

The same hook remembers the user fields the shop itself changed (``PATCH /api/users``, user actions) for five
minutes in Redis, so the change journal (``webhook_tee.py``) can tell the shop's own edits from someone else's.
«Мониторинг → Запросы к панели»: last 24 hours / 3 days / week, the busiest hour, error share and average time.
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import re
import time
from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import require_permission

logger = logging.getLogger("vpnshop.panel_api_stats")
router = APIRouter()
SOURCE: contextvars.ContextVar[str] = contextvars.ContextVar("panel_api_source", default="background")
_counts: dict[tuple, list] = defaultdict(lambda: [0, 0, 0.0])
ID_SEGMENT = re.compile(r"^(\d+|[0-9a-fA-F-]{32,36}|[A-Za-z0-9_-]{12,64})$")
KEEP = {"users", "nodes", "hosts", "actions", "bulk", "bulk-actions", "internal-squads", "external-squads", "hwid", "devices",
        "subscriptions", "by-id", "by-short-uuid", "by-username", "connections", "by-node", "by-user", "bandwidth-stats",
        "config-profiles", "system", "stats", "metadata", "tokens", "keygen", "sub", "stream", "restart", "restart-all",
        "extend", "enable", "disable", "reset-traffic", "revoke", "delete-all", "add-users", "remove-users", "drop",
        "subscription-settings", "subscription-templates", "inbounds", "connection-keys", "accessible-nodes"}


def template(path: str) -> str:
    path = path.split("?", 1)[0]
    parts = [p if (p in KEEP or not ID_SEGMENT.match(p)) else "{x}" for p in path.split("/")]
    return "/".join(parts)[:160]


def source_for_path(path: str) -> str:
    if path.startswith("/api/admin"):
        return "admin"
    if path.startswith("/api/webhooks"):
        return "webhook"
    if path.startswith("/sub"):
        return "subscription"
    if path.startswith(("/api/me", "/api/payments", "/api/auth", "/api/cabinet", "/api/app")):
        return "customer"
    return "api"


def record(source: str | None, method: str, path: str, status: int, ms: float) -> None:
    hour = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    row = _counts[(hour, (source or SOURCE.get())[:40], method.upper()[:8], template(path))]
    row[0] += 1
    row[1] += 1 if status >= 400 else 0
    row[2] += ms


def user_ref(method: str, path: str, kwargs: dict) -> tuple[str, list[str]] | None:
    """(panel user id, changed fields) for a call that changes a user."""
    m = re.match(r"^/api/users/([^/]+)/actions/([a-z-]+)$", path)
    if m and method.upper() == "POST":
        return m.group(1), [{"extend": "expireAt", "enable": "status", "disable": "status", "reset-traffic": "usedTrafficBytes",
                             "revoke": "shortUuid"}.get(m.group(2), m.group(2))]
    body = kwargs.get("json")
    if path == "/api/users" and method.upper() == "PATCH" and isinstance(body, dict) and body.get("id") is not None:
        return str(body["id"]), sorted(k for k in body if k not in {"id", "uuid"})
    return None


async def remember_write(ref: tuple[str, list[str]]) -> None:
    from . import main
    redis = main.redis_client
    if redis is None:
        _local_writes[ref[0]] = (time.monotonic(), ref[1])
        return
    key = f"rw:write:{ref[0]}"
    try:
        old = json.loads(await redis.get(key) or "[]")
        await redis.set(key, json.dumps(sorted(set(old) | set(ref[1]))), ex=300)
    except Exception as exc:  # noqa: BLE001 — attribution is a hint
        logger.debug("Write journal unavailable: %s", exc)


_local_writes: dict[str, tuple[float, list[str]]] = {}


async def recent_writes(panel_user: str) -> set[str]:
    from . import main
    redis = main.redis_client
    if redis is None:
        hit = _local_writes.get(panel_user)
        return set(hit[1]) if hit and time.monotonic() - hit[0] < 300 else set()
    try:
        return set(json.loads(await redis.get(f"rw:write:{panel_user}") or "[]"))
    except Exception:  # noqa: BLE001
        return set()


async def flush(db: AsyncSession) -> int:
    from .models import PanelApiStat
    items = list(_counts.items())
    _counts.clear()
    for (hour, source, method, path), (calls, errors, ms) in items:
        row = (await db.execute(select(PanelApiStat).where(PanelApiStat.hour == hour, PanelApiStat.source == source,
                                                           PanelApiStat.method == method, PanelApiStat.path == path))).scalar_one_or_none()
        if row:
            row.calls += calls
            row.errors += errors
            row.total_ms += int(ms)
        else:
            db.add(PanelApiStat(hour=hour, source=source, method=method, path=path, calls=calls, errors=errors, total_ms=int(ms)))
    await db.commit()
    return len(items)


async def report(db: AsyncSession, hours: int = 24) -> dict:
    from .models import PanelApiStat
    since = datetime.utcnow().replace(minute=0, second=0, microsecond=0) - timedelta(hours=hours)
    rows = (await db.execute(select(PanelApiStat).where(PanelApiStat.hour >= since))).scalars().all()
    by_source: dict[str, dict] = {}
    by_hour: dict[str, int] = defaultdict(int)
    for r in rows:
        s = by_source.setdefault(r.source, {"source": r.source, "calls": 0, "errors": 0, "ms": 0, "paths": {}})
        s["calls"] += r.calls
        s["errors"] += r.errors
        s["ms"] += r.total_ms
        p = s["paths"].setdefault(f"{r.method} {r.path}", {"path": f"{r.method} {r.path}", "calls": 0, "errors": 0, "ms": 0})
        p["calls"] += r.calls
        p["errors"] += r.errors
        p["ms"] += r.total_ms
        by_hour[r.hour.isoformat(timespec="minutes")] += r.calls
    sources = []
    for s in sorted(by_source.values(), key=lambda x: -x["calls"]):
        paths = sorted(s.pop("paths").values(), key=lambda x: -x["calls"])
        for p in paths:
            p["avg_ms"] = round(p.pop("ms") / p["calls"]) if p["calls"] else 0
        s["avg_ms"] = round(s.pop("ms") / s["calls"]) if s["calls"] else 0
        s["paths"] = paths[:30]
        sources.append(s)
    total = sum(s["calls"] for s in sources)
    peak = max(by_hour.items(), key=lambda kv: kv[1]) if by_hour else ("", 0)
    return {"hours": hours, "total": total, "errors": sum(s["errors"] for s in sources), "peak_hour": peak[0], "peak_calls": peak[1],
            "by_hour": [{"hour": h, "calls": n} for h, n in sorted(by_hour.items())], "sources": sources}


@router.get("/api/admin/panel-api-stats")
async def get_stats(hours: int = 24, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("ops.diagnostics"))):
    await flush(db)
    return await report(db, min(max(hours, 1), 24 * 7))


async def _loop() -> None:
    from .db import SessionLocal
    from .models import PanelApiStat
    from sqlalchemy import delete
    rounds = 0
    while True:
        await asyncio.sleep(60)
        try:
            async with SessionLocal() as db:
                await flush(db)
                rounds += 1
                if rounds % 60 == 0:
                    await db.execute(delete(PanelApiStat).where(PanelApiStat.hour < datetime.utcnow() - timedelta(days=30)))
                    await db.commit()
        except Exception as exc:  # noqa: BLE001 — counts wait for the next minute
            logger.warning("Panel API stats flush failed: %s", exc)


async def _start() -> None:
    from . import main
    main._track_task(_loop())


router.add_event_handler("startup", _start)

