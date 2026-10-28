"""Remnawave node status: a short Redis cache shared by every backend and worker process, and node monitoring.

``node_snapshot()`` asks Remnawave at most once per ``CACHE_TTL`` seconds for all processes together; the admin
panel, the apps' server list and the monitor read the same snapshot. Without Redis it asks Remnawave directly.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger("vpnshop.nodes")
CACHE_KEY = "nodes:status:v1"
CACHE_TTL = 30


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def node_row(node: dict) -> dict:
    """One node as the shop keeps it (admin view: the address is included, customers get ``public_node``)."""
    from .tariff_api import public_node

    shown = public_node(node)
    return {
        "uuid": str(node.get("uuid") or node.get("id") or "")[:64],
        "name": shown.get("name"),
        "country": shown.get("country") or None,
        "status": shown.get("status"),
        "users_online": shown.get("users_online"),
        "address": str(node.get("address") or node.get("host") or "")[:255],
        "xray_version": str(node.get("xrayVersion") or "")[:32] or None,
        "node_version": str(node.get("nodeVersion") or node.get("version") or "")[:32] or None,
        "last_status_message": str(node.get("lastStatusMessage") or "")[:300] or None,
    }


async def fetch_nodes(client=None) -> list[dict]:
    from .remnawave import RemnawaveClient
    from .tariff_api import _iter_nodes

    raw = await (client or RemnawaveClient()).list_nodes(start=0, size=500)
    return [node_row(n) for n in _iter_nodes(raw)]


def _redis():
    try:
        from . import main
        return main.redis_client
    except Exception:  # noqa: BLE001 — imported outside the app (scripts, tests)
        return None


async def node_snapshot(*, force: bool = False, redis=None, fetch=None) -> dict:
    """``{"nodes": [...], "fetched_at": iso, "cached": bool, "error": str|None}``."""
    redis = redis if redis is not None else _redis()
    if redis is not None and not force:
        try:
            raw = await redis.get(CACHE_KEY)
            if raw:
                return {**json.loads(raw), "cached": True}
        except Exception as exc:  # noqa: BLE001 — a cache error falls back to Remnawave
            logger.warning("Node cache read failed: %s", exc)
    try:
        nodes = await (fetch or fetch_nodes)()
        snap = {"nodes": nodes, "fetched_at": _now().isoformat(), "error": None}
    except Exception as exc:  # noqa: BLE001
        return {"nodes": [], "fetched_at": _now().isoformat(), "error": f"Remnawave недоступен: {str(exc)[:200]}", "cached": False}
    if redis is not None:
        try:
            await redis.set(CACHE_KEY, json.dumps(snap, ensure_ascii=False), ex=CACHE_TTL)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Node cache write failed: %s", exc)
    return {**snap, "cached": False}


# ------------------------------------------------------------------ monitoring
# Remnawave nodes are watched once a minute by one worker (Redis lock): a node that stays offline is
# restarted through the panel, the owner gets a Telegram alert when it stays down past the alert time,
# a node agent that stops reporting is reported too, and an optional daily restart and node update run
# at the Moscow time set in «Ноды → Мониторинг».
from datetime import timedelta  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402

from fastapi import APIRouter, Depends, HTTPException  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from .db import get_db  # noqa: E402
from .security import require_permission  # noqa: E402

MSK = ZoneInfo("Europe/Moscow")
CONFIG_KEY = "nodes.monitor.config"
STATE_KEY = "nodes.monitor.state"
TIME_PATTERN = r"^([01]\d|2[0-3]):[0-5]\d$"
DEFAULT_CONFIG = {"enabled": True, "auto_restart": True, "restart_after_minutes": 3, "restart_cooldown_minutes": 15,
                  "alert_after_minutes": 10, "agent_silence_minutes": 10,
                  "scheduled_restart": False, "restart_time": "04:30", "auto_update": False, "update_time": "05:00"}
router = APIRouter()


class MonitorConfigIn(BaseModel):
    enabled: bool = True
    auto_restart: bool = True
    restart_after_minutes: int = Field(default=3, ge=1, le=120)
    restart_cooldown_minutes: int = Field(default=15, ge=5, le=1440)
    alert_after_minutes: int = Field(default=10, ge=1, le=1440)
    agent_silence_minutes: int = Field(default=10, ge=2, le=1440)
    scheduled_restart: bool = False
    restart_time: str = Field(default="04:30", pattern=TIME_PATTERN)
    auto_update: bool = False
    update_time: str = Field(default="05:00", pattern=TIME_PATTERN)


async def _load(db: AsyncSession, key: str, default: dict) -> dict:
    from .models import AppSetting
    row = await db.get(AppSetting, key)
    try:
        value = json.loads(row.value) if row and row.value else {}
    except ValueError:
        value = {}
    return {**default, **value} if isinstance(value, dict) else dict(default)


async def _save(db: AsyncSession, key: str, value: dict) -> None:
    from .models import AppSetting
    row = await db.get(AppSetting, key)
    text = json.dumps(value, ensure_ascii=False, default=str)
    if row:
        row.value = text
    else:
        db.add(AppSetting(key=key, value=text))


def _iso(moment: datetime) -> str:
    return moment.replace(microsecond=0).isoformat()


def _parse(value) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _due(now: datetime, hhmm: str, last_day: str | None) -> bool:
    """Once a Moscow day, at or after HH:MM."""
    local = now.astimezone(MSK)
    hour, minute = map(int, hhmm.split(":"))
    return (local.hour, local.minute) >= (hour, minute) and last_day != local.date().isoformat()


async def monitor_pass(db: AsyncSession, now: datetime | None = None, *, panel=None, sender=None) -> dict:
    """One check of every node. Returns what was done (for the panel and the tests)."""
    from .models import AgentAction, NodeAgent
    from .remnawave import RemnawaveClient
    now = now or _now()
    config = await _load(db, CONFIG_KEY, DEFAULT_CONFIG)
    state = await _load(db, STATE_KEY, {"nodes": {}, "agents": {}})
    done = {"restarted": [], "alerts": [], "recovered": [], "scheduled_restart": False, "update_queued": 0}
    if not config["enabled"]:
        return done
    if sender is None:
        from .ops_alerts import send as sender
    panel = panel or RemnawaveClient()
    snap = await node_snapshot(force=True, fetch=lambda: fetch_nodes(panel))
    if snap.get("error"):
        done["error"] = snap["error"]
        return done
    nodes_state = state.setdefault("nodes", {})
    seen = set()
    for node in snap["nodes"]:
        uuid, name = node["uuid"], node["name"] or node["uuid"]
        if not uuid or node["status"] == "disabled":
            continue
        seen.add(uuid)
        item = nodes_state.setdefault(uuid, {"name": name})
        item["name"] = name
        if node["status"] == "online":
            if item.get("alerted_at"):
                down = _parse(item.get("down_since"))
                minutes = int((now - down).total_seconds() // 60) if down else 0
                await sender(f"✅ Нода «{name}» снова в сети (не работала {minutes} мин).")
                done["recovered"].append(uuid)
            for key in ("down_since", "alerted_at", "restart_count"):
                item.pop(key, None)
            continue
        down = _parse(item.get("down_since"))
        if down is None:
            item["down_since"] = _iso(now)
            continue
        offline = now - down
        restarted = _parse(item.get("restarted_at"))
        if (config["auto_restart"] and offline >= timedelta(minutes=config["restart_after_minutes"])
                and (restarted is None or now - restarted >= timedelta(minutes=config["restart_cooldown_minutes"]))):
            try:
                await panel.restart_node(uuid)
                item["restarted_at"] = _iso(now)
                item["restart_count"] = int(item.get("restart_count") or 0) + 1
                done["restarted"].append(uuid)
            except Exception as exc:  # noqa: BLE001 — the alert below still goes out
                item["last_error"] = str(exc)[:200]
        if offline >= timedelta(minutes=config["alert_after_minutes"]) and not item.get("alerted_at"):
            tried = f" Перезапуск через панель: {item.get('restart_count', 0)} раз." if config["auto_restart"] else ""
            await sender(f"🚨 Нода «{name}» не в сети {int(offline.total_seconds() // 60)} мин.{tried} "
                         f"Проверьте сервер ноды: Ноды → Мониторинг.")
            item["alerted_at"] = _iso(now)
            done["alerts"].append(uuid)
    for gone in set(nodes_state) - seen:
        nodes_state.pop(gone, None)
    # Node agents (scripts/node-agent.py) that stop reporting.
    agents_state = state.setdefault("agents", {})
    silence = timedelta(minutes=config["agent_silence_minutes"])
    agents = (await db.execute(select(NodeAgent).where(NodeAgent.enabled.is_(True)))).scalars().all()
    for agent in agents:
        seen_at = agent.last_seen_at.replace(tzinfo=timezone.utc) if agent.last_seen_at else None
        key = str(agent.id)
        if seen_at and now - seen_at > silence:
            if not agents_state.get(key):
                await sender(f"🚨 Агент ноды «{agent.name}» молчит {int((now - seen_at).total_seconds() // 60)} мин: "
                             "нет данных о нагрузке и Xray. Проверьте службу corgi-node-agent на сервере ноды.")
                agents_state[key] = _iso(now)
                done["alerts"].append(f"agent:{agent.name}")
        elif agents_state.pop(key, None):
            await sender(f"✅ Агент ноды «{agent.name}» снова на связи.")
    # Planned restart of all nodes and node updates, once a Moscow day.
    if config["scheduled_restart"] and _due(now, config["restart_time"], state.get("restart_day")):
        try:
            await panel.restart_all_nodes()
            done["scheduled_restart"] = True
        except Exception as exc:  # noqa: BLE001
            await sender(f"⚠️ Плановый перезапуск нод не выполнен: {str(exc)[:200]}")
        state["restart_day"] = now.astimezone(MSK).date().isoformat()
    if config["auto_update"] and _due(now, config["update_time"], state.get("update_day")):
        for agent in agents:
            db.add(AgentAction(agent_id=agent.id, kind="update_node", payload={"requested_at": _iso(now)}, status="queued"))
            done["update_queued"] += 1
        state["update_day"] = now.astimezone(MSK).date().isoformat()
    state["checked_at"] = _iso(now)
    await _save(db, STATE_KEY, state)
    await db.commit()
    return done


async def node_monitor_scheduler(session_factory=None):
    """Every minute in one worker process at a time (Redis lock with a 55 s lease)."""
    import asyncio

    from . import main
    while True:
        try:
            lock = None
            if main.redis_client is not None:
                lock = await main.redis_client.set("lock:node-monitor", "1", nx=True, ex=55)
            if lock or main.redis_client is None:
                from .db import SessionLocal
                async with (session_factory or SessionLocal)() as db:
                    await monitor_pass(db)
                async with (session_factory or SessionLocal)() as db:
                    from .node_autoscale import tick as autoscale_tick
                    await autoscale_tick(db)
                from .config import settings as cfg
                if cfg.remnawave_url and cfg.remnawave_token:
                    async with (session_factory or SessionLocal)() as db:
                        from .panel_guard import tick as guard_tick
                        await guard_tick(db, not (await node_snapshot()).get("error"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Node monitor failed: %s", exc)
        await asyncio.sleep(60)


@router.get("/api/admin/nodes/health")
async def nodes_health(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("ops.diagnostics"))):
    from .models import NodeAgent
    snap = await node_snapshot()
    state = await _load(db, STATE_KEY, {"nodes": {}, "agents": {}})
    now = _now()
    nodes = []
    for node in snap["nodes"]:
        item = state["nodes"].get(node["uuid"], {})
        down = _parse(item.get("down_since"))
        nodes.append({**node, "down_minutes": int((now - down).total_seconds() // 60) if down else 0,
                      "restarted_at": item.get("restarted_at"), "restart_count": item.get("restart_count", 0),
                      "alerted": bool(item.get("alerted_at"))})
    agents = (await db.execute(select(NodeAgent).order_by(NodeAgent.id))).scalars().all()
    return {"config": await _load(db, CONFIG_KEY, DEFAULT_CONFIG), "nodes": nodes, "error": snap.get("error"),
            "fetched_at": snap.get("fetched_at"), "checked_at": state.get("checked_at"),
            "agents": [{"id": a.id, "name": a.name, "version": a.version, "xray_ok": a.xray_ok, "last_seen_at": a.last_seen_at,
                        "silent": bool(state["agents"].get(str(a.id)))} for a in agents]}


@router.put("/api/admin/nodes/health/config")
async def nodes_health_config(payload: MonitorConfigIn, db: AsyncSession = Depends(get_db),
                              admin=Depends(require_permission("settings.runtime.write"))):
    from .main import audit
    await _save(db, CONFIG_KEY, payload.model_dump())
    await audit(db, "nodes.monitor.config", admin.email, None, payload.model_dump())
    await db.commit()
    return payload.model_dump()


@router.post("/api/admin/nodes/{node_uuid}/restart")
async def restart_node(node_uuid: str, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("provision_nodes"))):
    import re

    from .main import audit
    from .remnawave import RemnawaveClient
    if not re.fullmatch(r"[A-Za-z0-9-]{1,64}", node_uuid):
        raise HTTPException(400, "Некорректный идентификатор ноды")
    try:
        await RemnawaveClient().restart_node(node_uuid)
    except Exception as exc:
        raise HTTPException(502, "Remnawave не перезапустил ноду") from exc
    await audit(db, "nodes.restart", admin.email, node_uuid)
    await db.commit()
    return {"ok": True}


@router.post("/api/admin/nodes/update")
async def update_nodes(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("provision_nodes"))):
    """Queue «update_node» for every node agent: the agent pulls the newest remnawave/node image and recreates it."""
    from .main import audit
    from .models import AgentAction, NodeAgent
    agents = (await db.execute(select(NodeAgent).where(NodeAgent.enabled.is_(True)))).scalars().all()
    for agent in agents:
        db.add(AgentAction(agent_id=agent.id, kind="update_node", payload={"requested_by": admin.email}, status="queued"))
    await audit(db, "nodes.update.queued", admin.email, None, {"agents": len(agents)})
    await db.commit()
    return {"queued": len(agents)}
