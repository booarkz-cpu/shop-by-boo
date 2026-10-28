"""VPN sessions and anomalies: who was online, from which IP and provider, on which node — with history.

The panel shows who is online right now but keeps no history. When «Сессии» is on, the shop asks the panel every
few minutes for the IPs of the users on each connected node (``POST /api/connections/by-node/{node}`` → job →
``GET /api/connections/by-node/{job}``, Remnawave 3.4; checked live in CI) and glues the snapshots into sessions:
customer, node, IP, provider (ASN) and country from RIPEstat through the network intel cache, first and last seen.

**Anomalies** are the owner's rules over the current snapshot of a customer: more than N IPs, providers (ASN) or
countries at once, optionally «× the device limit». Each rule is yellow or red. A match opens an anomaly (a mark in
the list and an event in the customer's timeline); when it no longer matches it closes but stays in the history.
The customer card also has «Сейчас онлайн» (a live request to the panel) and «Сбросить соединения».

Off by default; sessions are kept 30 days. Only IPs the panel reports; nothing is sent to anyone but RIPEstat
(ASN/country of public IPs, limited and cached for a week).
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import require_permission

logger = logging.getLogger("vpnshop.vpn_sessions")
router = APIRouter()
CONFIG_KEY = "sessions.config"
STATE_KEY = "sessions.anomalies"
DEFAULT = {"enabled": False, "interval_min": 5, "keep_days": 30, "rules": []}
TYPICAL_RULES = [
    {"name": "Много адресов", "metric": "ips", "value": 2, "per_device": True, "level": "yellow"},
    {"name": "Несколько провайдеров", "metric": "asns", "value": 3, "per_device": False, "level": "yellow"},
    {"name": "Разные страны", "metric": "countries", "value": 2, "per_device": False, "level": "red"},
]
METRICS = {"ips": "IP сейчас", "asns": "Провайдеров сейчас", "countries": "Стран сейчас"}


async def _load(db, key, default):
    from .node_health import _load as load
    return await load(db, key, default)


async def _save(db, key, value):
    from .node_health import _save as save
    await save(db, key, value)


async def run_job(panel, kind: str, ref: str, timeout: float = 25.0) -> dict | None:
    """Start a panel connections job (by-node / by-user) and wait for its result."""
    started = await panel._request("POST", f"/api/connections/{kind}/{ref}")
    job = (started or {}).get("jobId")
    if not job:
        return None
    waited = 0.0
    while waited < timeout:
        await asyncio.sleep(1.0 if waited < 5 else 2.0)
        waited += 1.0 if waited < 5 else 2.0
        state = await panel._request("GET", f"/api/connections/{kind}/{job}")
        if state.get("isFailed"):
            return None
        if state.get("isCompleted"):
            return state.get("result") if isinstance(state.get("result"), dict) else None
    return None


def _ips(items) -> list[str]:
    out = []
    for item in items or []:
        ip = item.get("ip") if isinstance(item, dict) else item
        if isinstance(ip, str) and ip:
            out.append(ip[:64])
    return out


async def snapshot(panel) -> dict[str, list[tuple[str, str]]]:
    """panel user id → [(node name, ip)] for every connected node."""
    from .node_health import fetch_nodes
    seen: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for node in await fetch_nodes(panel):
        if node.get("status") not in (None, "online", "unknown") or not node.get("uuid"):
            continue  # a disabled or disconnected node has nobody online
        try:
            result = await run_job(panel, "by-node", node["uuid"])
        except Exception as exc:  # noqa: BLE001 — one node does not stop the others
            logger.info("Sessions of node %s are unknown: %s", node.get("name"), exc)
            continue
        for user in (result or {}).get("users") or []:
            uid = str(user.get("userId") or user.get("userUuid") or "")
            for ip in _ips(user.get("ips")):
                seen[uid].append((str(node.get("name") or node["uuid"])[:120], ip))
    return seen


async def _geo(db: AsyncSession, ip: str, budget: list[int]) -> tuple[str, str, str]:
    from .models import NetworkIntel
    from .network_intel import public_ip, refresh_one
    if not public_ip(ip):
        return "", "", ""
    row = await db.scalar(select(NetworkIntel).where(NetworkIntel.ip == ip, NetworkIntel.source == "ripestat"))
    if (row is None or not row.data) and budget[0] > 0:
        budget[0] -= 1
        if await refresh_one(db, ip, "ripestat") == "fetched":
            row = await db.scalar(select(NetworkIntel).where(NetworkIntel.ip == ip, NetworkIntel.source == "ripestat")
                                  .execution_options(populate_existing=True))
    data = (row.data if row else None) or {}
    return (str(data.get("asn") or ""), str(data.get("holder") or "")[:120], str(data.get("country") or "")[:2])


def evaluate(rules: list[dict], rows: list[dict], device_limit: int) -> list[dict]:
    values = {"ips": len({r["ip"] for r in rows}), "asns": len({r["asn"] or r["ip"].rsplit(".", 1)[0] for r in rows}),
              "countries": len({r["country"] for r in rows if r["country"]})}
    hits = []
    for rule in rules:
        metric = rule.get("metric")
        if metric not in values:
            continue
        limit = int(rule.get("value") or 0) * (max(1, device_limit) if rule.get("per_device") else 1)
        if values[metric] > limit:
            hits.append({"name": rule.get("name") or METRICS[metric], "level": rule.get("level", "yellow"),
                         "metric": metric, "value": values[metric], "limit": limit})
    return hits


async def collect(db: AsyncSession, panel=None, now: datetime | None = None) -> dict:
    from .activity_log import record
    from .models import Subscription, VpnSession
    cfg = await _load(db, CONFIG_KEY, DEFAULT)
    now = now or datetime.utcnow()
    if panel is None:
        from .remnawave import RemnawaveClient
        panel = RemnawaveClient()
    seen = await snapshot(panel)
    window = now - timedelta(minutes=2 * int(cfg.get("interval_min") or 5) + 1)
    budget = [20]
    anomalies = await _load(db, STATE_KEY, {})
    opened = closed = 0
    still: set[str] = set()
    for panel_user, pairs in seen.items():
        sub = await db.scalar(select(Subscription).where(Subscription.remnawave_uuid == panel_user).order_by(Subscription.id.desc()).limit(1))
        current = []
        for node, ip in set(pairs):
            row = await db.scalar(select(VpnSession).where(VpnSession.panel_user == panel_user, VpnSession.node == node,
                                                           VpnSession.ip == ip, VpnSession.last_seen >= window))
            if row:
                row.last_seen = now
                if not row.asn:
                    row.asn, row.isp, row.country = await _geo(db, ip, budget)
            else:
                asn, isp, country = await _geo(db, ip, budget)
                row = VpnSession(panel_user=panel_user, user_id=sub.user_id if sub else None, node=node, ip=ip,
                                 asn=asn, isp=isp, country=country, first_seen=now, last_seen=now)
                db.add(row)
            current.append({"ip": ip, "asn": row.asn, "isp": row.isp, "country": row.country, "node": node})
        hits = evaluate(cfg.get("rules") or [], current, int(getattr(sub, "device_limit_snapshot", 0) or 0)) if sub else []
        key = str(sub.user_id) if sub else f"panel:{panel_user}"
        if hits and key not in anomalies:
            opened += 1
            if sub:
                record(db, sub.user_id, "system", "sessions.anomaly", {"rules": [h["name"] for h in hits], "ips": [c["ip"] for c in current][:20]})
        if hits:
            still.add(key)
            anomalies[key] = {"user_id": sub.user_id if sub else None, "panel_user": panel_user, "hits": hits, "since":
                              (anomalies.get(key) or {}).get("since") or now.isoformat(timespec="seconds"),
                              "level": "red" if any(h["level"] == "red" for h in hits) else "yellow", "now": current[:20]}
    for key in [k for k in anomalies if k not in still]:
        item = anomalies.pop(key)
        closed += 1
        if item.get("user_id"):
            record(db, item["user_id"], "system", "sessions.anomaly_closed", {"since": item.get("since")})
    await _save(db, STATE_KEY, anomalies)
    await db.commit()
    return {"users": len(seen), "anomalies": len(anomalies), "opened": opened, "closed": closed}


async def cleanup(db: AsyncSession, keep_days: int) -> None:
    from .models import VpnSession
    await db.execute(delete(VpnSession).where(VpnSession.last_seen < datetime.utcnow() - timedelta(days=max(7, keep_days))))
    await db.commit()


async def _loop() -> None:
    from .db import SessionLocal
    from .main import redis_client
    rounds = 0
    while True:
        try:
            async with SessionLocal() as db:
                cfg = await _load(db, CONFIG_KEY, DEFAULT)
                interval = max(2, int(cfg.get("interval_min") or 5))
                if cfg.get("enabled") and (redis_client is None or await redis_client.set("lock:sessions", "1", nx=True, ex=interval * 60 - 10)):
                    await collect(db)
                    rounds += 1
                    if rounds % 50 == 1:
                        await cleanup(db, int(cfg.get("keep_days") or 30))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Sessions pass failed: %s", exc)
            interval = 5
        await asyncio.sleep(interval * 60)


def _start() -> None:
    from .main import _track_task
    _track_task(_loop())


router.add_event_handler("startup", _start)


# ---------------------------------------------------------------- admin


class RuleIn(BaseModel):
    name: str = Field("", max_length=60)
    metric: str = Field(..., pattern=r"^(ips|asns|countries)$")
    value: int = Field(..., ge=0, le=100)
    per_device: bool = False
    level: str = Field("yellow", pattern=r"^(yellow|red)$")


class SessionsIn(BaseModel):
    enabled: bool = False
    interval_min: int = Field(5, ge=2, le=60)
    keep_days: int = Field(30, ge=7, le=30)
    rules: list[RuleIn] = Field(default_factory=list, max_length=20)


@router.get("/api/admin/sessions/config")
async def get_config(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("ops.diagnostics"))):
    return {"config": await _load(db, CONFIG_KEY, DEFAULT), "typical_rules": TYPICAL_RULES, "metrics": METRICS}


@router.put("/api/admin/sessions/config")
async def put_config(payload: SessionsIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("settings.runtime.write"))):
    await _save(db, CONFIG_KEY, payload.model_dump())
    await db.commit()
    return {"ok": True}


@router.get("/api/admin/sessions/anomalies")
async def get_anomalies(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("users.read"))):
    items = list((await _load(db, STATE_KEY, {})).values())
    return {"anomalies": sorted(items, key=lambda x: (x.get("level") != "red", x.get("since") or ""))}


async def _sub_of(db: AsyncSession, user_id: int):
    from .models import Subscription
    sub = await db.scalar(select(Subscription).where(Subscription.user_id == user_id, Subscription.remnawave_uuid.is_not(None))
                          .order_by(Subscription.is_primary.desc(), Subscription.id.desc()).limit(1))
    if not sub:
        raise HTTPException(404, "У клиента нет подписки в панели")
    return sub


@router.get("/api/admin/users/{user_id}/sessions")
async def user_sessions(user_id: int, days: int = 30, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("users.read"))):
    from .models import VpnSession
    since = datetime.utcnow() - timedelta(days=min(max(days, 1), 30))
    rows = (await db.execute(select(VpnSession).where(VpnSession.user_id == user_id, VpnSession.last_seen >= since)
                             .order_by(VpnSession.last_seen.desc()).limit(500))).scalars().all()
    groups: dict[tuple, dict] = {}
    for r in rows:
        g = groups.setdefault((r.isp or r.asn or "—", r.country), {"isp": r.isp or (f"AS{r.asn}" if r.asn else "—"), "country": r.country,
                                                                   "ips": set(), "nodes": set(), "first": r.first_seen, "last": r.last_seen})
        g["ips"].add(r.ip)
        g["nodes"].add(r.node)
        g["first"], g["last"] = min(g["first"], r.first_seen), max(g["last"], r.last_seen)
    week = datetime.utcnow() - timedelta(days=7)
    return {"groups": [{**{k: v for k, v in g.items() if k not in {"ips", "nodes", "first", "last"}}, "ips": sorted(g["ips"])[:20],
                        "nodes": sorted(g["nodes"]), "first": g["first"].isoformat(timespec="minutes"), "last": g["last"].isoformat(timespec="minutes")}
                       for g in sorted(groups.values(), key=lambda x: x["last"], reverse=True)],
            "week": {"ips": len({r.ip for r in rows if r.last_seen >= week}), "providers": len({r.asn or r.isp for r in rows if r.last_seen >= week}),
                     "countries": len({r.country for r in rows if r.last_seen >= week and r.country})}}


@router.get("/api/admin/users/{user_id}/online")
async def online_now(user_id: int, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("users.read"))):
    from .remnawave import RemnawaveClient
    sub = await _sub_of(db, user_id)
    result = await run_job(RemnawaveClient(), "by-user", sub.remnawave_uuid)
    nodes = [{"node": n.get("nodeName") or n.get("nodeUuid"), "country": n.get("countryCode") or "", "ips": _ips(n.get("ips"))}
             for n in (result or {}).get("nodes") or []]
    return {"online": nodes, "answered": result is not None}


@router.post("/api/admin/users/{user_id}/drop-connections")
async def drop_connections(user_id: int, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("users.write"))):
    from .remnawave import RemnawaveClient
    sub = await _sub_of(db, user_id)
    return {"ok": True, "dropped": await drop(RemnawaveClient(), sub.remnawave_uuid)}


async def drop(panel, panel_user: str) -> bool:
    """Drop the user's connections on every node; False when no node is connected (panel error A219)."""
    from .remnawave import RemnawaveError
    ref = int(panel_user) if str(panel_user).isdigit() else panel_user
    by = {"by": "userIds", "userIds": [ref]} if isinstance(ref, int) else {"by": "userUuids", "userUuids": [ref]}
    try:
        await panel._request("POST", "/api/connections/drop", json={"dropBy": by, "targetNodes": {"target": "allNodes"}})
    except RemnawaveError as exc:
        if "A219" in str(exc):
            return False
        raise
    return True


@router.get("/api/admin/sessions/geo")
async def geography(days: int = 7, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("analytics.read"))):
    """«География клиентов»: customers by country and by provider over the sessions of the period (no IPs)."""
    from sqlalchemy import func
    from .models import VpnSession
    since = datetime.utcnow() - timedelta(days=min(max(days, 1), 30))
    by_country = (await db.execute(select(VpnSession.country, func.count(func.distinct(VpnSession.panel_user)))
                                   .where(VpnSession.last_seen >= since).group_by(VpnSession.country))).all()
    by_isp = (await db.execute(select(VpnSession.isp, VpnSession.country, func.count(func.distinct(VpnSession.panel_user)))
                               .where(VpnSession.last_seen >= since).group_by(VpnSession.isp, VpnSession.country))).all()
    total = sum(n for _, n in by_country) or 1
    return {"days": days,
            "countries": sorted(({"country": c or "—", "users": n, "share": round(n * 100 / total, 1)} for c, n in by_country), key=lambda x: -x["users"]),
            "providers": sorted(({"isp": i or "—", "country": c or "", "users": n} for i, c, n in by_isp), key=lambda x: -x["users"])[:30]}
