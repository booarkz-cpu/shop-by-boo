"""v28.53 «Прогноз нагрузки нод»: «at the present growth this node reaches its limit in about N days».

Every 30 minutes the shop keeps the day's peak of users online per node (from the panel, ``node_snapshot``), 60 days
back (``forecast.samples``). A straight line through the last ``window_days`` daily peaks gives the growth per day;
with the node's capacity (``capacities[uuid]`` or ``default_capacity`` users online) that is the number of days left.
A node with fewer than ``warn_days`` left, or already at ``busy_percent`` of its limit, is flagged and the owner is told
once a day per node. It complements «Автомасштабирование нод» (which reacts to the load of now).

Admin: «Ноды → Прогноз нагрузки» (capacity per node) and the mobile card; ``GET``/``PUT /api/admin/nodes/forecast``.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import require_permission

logger = logging.getLogger("vpnshop.node_forecast")
router = APIRouter()
CONFIG_KEY = "forecast.config"
SAMPLES_KEY = "forecast.samples"
DEFAULT = {"enabled": True, "default_capacity": 300, "capacities": {}, "window_days": 28, "warn_days": 14, "busy_percent": 85, "alerted": {}}
KEEP_DAYS = 60


class ForecastIn(BaseModel):
    enabled: bool = True
    default_capacity: int = Field(300, ge=1, le=100000)
    capacities: dict[str, int] = Field(default_factory=dict)
    window_days: int = Field(28, ge=7, le=60)
    warn_days: int = Field(14, ge=1, le=90)
    busy_percent: int = Field(85, ge=10, le=100)


async def _load(db, key, default):
    from .node_health import _load as load
    return await load(db, key, default)


async def _save(db, key, value):
    from .node_health import _save as save
    await save(db, key, value)


def trend(points: list[tuple[int, int]]) -> float:
    """Least-squares slope (users per day) through ``(day_index, peak)``."""
    if len(points) < 2:
        return 0.0
    n = len(points)
    mx = sum(x for x, _ in points) / n
    my = sum(y for _, y in points) / n
    den = sum((x - mx) ** 2 for x, _ in points)
    return 0.0 if den == 0 else sum((x - mx) * (y - my) for x, y in points) / den


def forecast_node(series: dict[str, int], capacity: int, cfg: dict, today: datetime) -> dict:
    days = sorted(series)[-int(cfg["window_days"]):]
    base = datetime.fromisoformat(days[0]) if days else today
    points = [((datetime.fromisoformat(d) - base).days, int(series[d])) for d in days]
    slope = trend(points)
    current = int(series[days[-1]]) if days else 0
    left = None
    if slope > 0.01 and current < capacity:
        left = int((capacity - current) / slope)
    load = round(current * 100 / capacity) if capacity else 0
    flagged = (left is not None and left <= int(cfg["warn_days"]) and len(points) >= 7) or load >= int(cfg["busy_percent"])
    return {"peak": current, "capacity": capacity, "load_percent": load, "per_day": round(slope, 2), "days_left": left,
            "samples": len(points), "flagged": bool(flagged)}


async def sample(db: AsyncSession, nodes: list[dict], now: datetime | None = None) -> dict:
    """Keep the peak of users online per node for today (Moscow day)."""
    now = now or datetime.utcnow()
    day = (now + timedelta(hours=3)).date().isoformat()
    data = await _load(db, SAMPLES_KEY, {})
    for node in nodes:
        uuid = str(node.get("uuid") or "")
        if not uuid or node.get("status") == "disabled":
            continue
        entry = data.setdefault(uuid, {"name": node.get("name") or uuid[:8], "days": {}})
        entry["name"] = node.get("name") or entry.get("name")
        entry["days"][day] = max(int(entry["days"].get(day, 0)), int(node.get("users_online") or 0))
        cutoff = (now - timedelta(days=KEEP_DAYS)).date().isoformat()
        entry["days"] = {d: v for d, v in entry["days"].items() if d >= cutoff}
    await _save(db, SAMPLES_KEY, data)
    await db.commit()
    return data


async def report(db: AsyncSession, now: datetime | None = None) -> dict:
    now = now or datetime.utcnow()
    cfg = {**DEFAULT, **await _load(db, CONFIG_KEY, DEFAULT)}
    data = await _load(db, SAMPLES_KEY, {})
    nodes = []
    for uuid, entry in data.items():
        capacity = int((cfg.get("capacities") or {}).get(uuid) or cfg["default_capacity"])
        nodes.append({"uuid": uuid, "name": entry.get("name"), **forecast_node(entry.get("days") or {}, capacity, cfg, now)})
    nodes.sort(key=lambda x: (not x["flagged"], x["days_left"] if x["days_left"] is not None else 10**6, -x["load_percent"]))
    return {"config": {k: v for k, v in cfg.items() if k != "alerted"}, "nodes": nodes}


async def tick(db: AsyncSession, nodes: list[dict] | None = None, now: datetime | None = None, send=None) -> list[str]:
    now = now or datetime.utcnow()
    cfg = {**DEFAULT, **await _load(db, CONFIG_KEY, DEFAULT)}
    if not cfg["enabled"]:
        return []
    if nodes is None:
        from .node_health import node_snapshot
        snap = await node_snapshot()
        if snap.get("error"):
            return []
        nodes = snap.get("nodes") or []
    await sample(db, nodes, now)
    day = (now + timedelta(hours=3)).date().isoformat()
    flagged = [n for n in (await report(db, now))["nodes"] if n["flagged"] and (cfg.get("alerted") or {}).get(n["uuid"]) != day]
    if not flagged:
        return []
    if send is None:
        from .ops_alerts import send
    lines = ["Прогноз нагрузки нод"]
    for n in flagged[:8]:
        when = f"лимит примерно через {n['days_left']} дн." if n["days_left"] is not None else "рост не виден"
        lines.append(f"{n['name']}: пик {n['peak']} из {n['capacity']} ({n['load_percent']}%), {when}")
    lines.append("Раздел: Ноды → Прогноз нагрузки")
    await send("\n".join(lines))
    alerted = dict(cfg.get("alerted") or {})
    alerted.update({n["uuid"]: day for n in flagged})
    await _save(db, CONFIG_KEY, {**cfg, "alerted": alerted})
    await db.commit()
    return [n["uuid"] for n in flagged]


async def _loop():
    from .db import SessionLocal
    from .main import redis_client
    while True:
        await asyncio.sleep(1800)
        try:
            if redis_client is not None and not await redis_client.set("lock:node_forecast", "1", nx=True, ex=1700):
                continue
            async with SessionLocal() as db:
                await tick(db)
        except Exception as exc:  # noqa: BLE001
            logger.warning("node forecast pass failed: %s", exc)


def _start():
    from .main import _track_task
    _track_task(_loop())


router.add_event_handler("startup", _start)


@router.get("/api/admin/nodes/forecast")
async def get_forecast(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("ops.diagnostics"))):
    return await report(db)


@router.put("/api/admin/nodes/forecast")
async def put_forecast(payload: ForecastIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("provision_nodes"))):
    from .main import audit
    cfg = {**DEFAULT, **await _load(db, CONFIG_KEY, DEFAULT)}
    await _save(db, CONFIG_KEY, {**cfg, **payload.model_dump()})
    await audit(db, "forecast.config", admin.email, None, payload.model_dump())
    await db.commit()
    return await report(db)
