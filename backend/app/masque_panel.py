"""The shop's own panel for MASQUE: nodes, users and the subscription (owner's task of 2026-11-12).

The Remnawave panel does not know the protocol, so the shop does the panel's job itself:

* installs the MASQUE stack on a node behind its SelfSteal site (``rw_masque``, over SSH);
* decides who has access — every subscription that is paid and not paused, of the chosen plans;
* keeps the nodes in step with that list without restarting Xray (a pass every minute, SSH only when the list changed);
* hands out a subscription of its own: ``/api/masque/sub/<token>`` returns ready Xray client configs, one per node.

Nothing is stored about a user: the login and the password follow from the shop's secret and the subscription id.
What MASQUE traffic is not: it is not counted towards the plan's traffic limit (the panel does not see it) — the
page says so, and the owner chooses the plans that get the protocol.
"""
from __future__ import annotations

import hashlib
import hmac
import re
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import rw_masque
from .config import settings
from .db import get_db
from .models import Plan, Subscription
from .security import require_permission

router = APIRouter(tags=["masque"])

STATE_KEY = "masque.panel"
DEFAULT = {"enabled": False, "plan_ids": [], "port": rw_masque.DEFAULT_PORT, "nodes": {}}
LIVE = ("active", "grace", "cancel_scheduled")     # paid and not paused, frozen or expired
RESYNC = timedelta(minutes=30)                     # a node is re-checked this often even when the list did not change
TOKEN = re.compile(r"^(\d{1,12})\.([0-9a-f]{32})\Z")

__all__ = ["router", "token", "subscription_id", "eligible", "users_of", "users_hash", "tick", "sync_node"]


class SettingsIn(BaseModel):
    enabled: bool
    plan_ids: list[int] = Field(default_factory=list, max_length=200)
    port: int = Field(default=rw_masque.DEFAULT_PORT, ge=1024, le=65535)


# ---------------------------------------------------------------- pure

def token(subscription: int) -> str:
    sig = hmac.new(settings.app_secret.encode(), f"masque-sub:{int(subscription)}".encode(), hashlib.sha256).hexdigest()[:32]
    return f"{int(subscription)}.{sig}"


def subscription_id(value: str) -> int | None:
    """The subscription a link belongs to; None for a link the shop did not issue."""
    match = TOKEN.match(value or "")
    if not match or not hmac.compare_digest(token(int(match[1])), value):
        return None
    return int(match[1])


def eligible(sub, state: dict, now: datetime) -> bool:
    """A subscription has MASQUE while it is paid and running, and its plan is among the chosen ones (none chosen: all)."""
    if not state.get("enabled") or sub.expires_at is None or sub.expires_at <= now:
        return False
    if (sub.lifecycle_status or "active") not in LIVE:
        return False
    plans = state.get("plan_ids") or []
    return not plans or sub.plan_id in plans


def users_of(subs) -> list[dict]:
    out = []
    for sub in sorted(subs, key=lambda s: s.id):
        login, password = rw_masque.credentials(settings.app_secret, str(sub.id))
        out.append({"email": login, "pass": password})
    return out


def users_hash(users: list[dict], domain: str, port: int) -> str:
    text = "\n".join(sorted(u["email"] for u in users)) + f"\n{domain}:{port}"
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _naive(now: datetime | None = None) -> datetime:
    return (now or datetime.now(UTC)).replace(tzinfo=None)


def _iso(now: datetime) -> str:
    return now.replace(microsecond=0).isoformat() + "Z"


def prefix_of(server_id: int) -> str:
    return rw_masque.new_prefix(settings.app_secret, f"server-{int(server_id)}")


def configs_for(state: dict, sub) -> list[dict]:
    """The subscription itself: one whole client config per working node."""
    login, password = rw_masque.credentials(settings.app_secret, str(sub.id))
    nodes = sorted((n for n in (state.get("nodes") or {}).values() if n.get("state") == "on"), key=lambda n: n.get("name") or "")
    return [rw_masque.client_config(n["domain"], int(n["port"]), prefix_of(n["server_id"]), login, password, f"MASQUE · {n.get('name') or n['domain']}")
            for n in nodes]


# ---------------------------------------------------------------- storage and SSH

async def _state(db: AsyncSession) -> dict:
    from .node_health import _load
    state = await _load(db, STATE_KEY, DEFAULT)
    state["nodes"] = dict(state.get("nodes") or {})
    return state


async def _store(db: AsyncSession, state: dict) -> None:
    from .node_health import _save
    await _save(db, STATE_KEY, state)


async def _live_subs(db: AsyncSession, state: dict, now: datetime) -> list:
    if not state.get("enabled"):
        return []
    rows = (await db.execute(select(Subscription).where(Subscription.expires_at.is_not(None), Subscription.expires_at > now,
                                                        Subscription.lifecycle_status.in_(LIVE)))).scalars().all()
    return [s for s in rows if eligible(s, state, now)]


async def _ssh(db: AsyncSession, server_id: int, action: str, *args: str, stdin: bytes | None = None):
    """Runs the node script; raises HTTPException with the script's own last words."""
    from . import rw_jobs, rw_ssh, rw_steps
    from .models import RemnawaveServer
    row = await db.get(RemnawaveServer, server_id)
    if not row:
        raise HTTPException(404, "Сервер не найден")
    server = rw_jobs.server_dict(row)
    try:
        result = await rw_steps._run(rw_ssh._ctx(server), server_id, rw_masque.NODE, action, *args, stdin=stdin, timeout=600)
    except rw_steps.StepError as exc:
        raise HTTPException(502, f"SSH: {exc}") from exc
    return result


REASONS = {"nodocker": "На сервере нет Docker", "noselfsteal": "На ноде не запущен сайт SelfSteal: MASQUE прячется за ним",
           "nocert": "У сайта SelfSteal ещё нет сертификата", "not installed": "MASQUE на этой ноде не установлен",
           "bad archive": "Файлы дошли до сервера повреждёнными", "users differ after sync": "Нода не приняла список пользователей"}


def _why(result) -> str:
    lines = ((result.out or "") + "\n" + (result.err or "")).strip().splitlines()
    last = lines[-1].strip() if lines else ""
    for key, text in REASONS.items():
        if key in "\n".join(lines[-25:]):
            return text
    return f"Скрипт завершился с кодом {result.code}: {last[:200]}" if last else f"Скрипт завершился с кодом {result.code}"


async def sync_node(db: AsyncSession, node: dict, users: list[dict], action: str = "sync") -> dict:
    """Sends the stack's files and the user list to one node; returns the node record with the result."""
    data = rw_masque.bundle(node["domain"], int(node["port"]), prefix_of(node["server_id"]), users)
    now = _naive()
    try:
        result = await _ssh(db, node["server_id"], action, node["domain"], str(node["port"]), hashlib.sha256(data).hexdigest(), stdin=data)
        error = None if result.code == 0 else _why(result)
    except HTTPException as exc:
        error = str(exc.detail)[:300]
    if error:
        return {**node, "error": error, "checked_at": _iso(now)}
    return {**node, "state": "on", "error": None, "users": len(users), "hash": users_hash(users, node["domain"], int(node["port"])),
            "synced_at": _iso(now), "checked_at": _iso(now)}


def due(node: dict, wanted: str, now: datetime) -> bool:
    if node.get("state") != "on":
        return False
    if node.get("hash") != wanted:
        return True
    try:
        last = datetime.fromisoformat((node.get("checked_at") or "").rstrip("Z"))
    except ValueError:
        return True
    return now - last >= RESYNC


async def tick(db: AsyncSession, now: datetime | None = None) -> int:
    """Called by the worker every minute. Returns how many nodes were contacted."""
    state = await _state(db)
    if not state["nodes"]:
        return 0
    now = _naive(now)
    users = users_of(await _live_subs(db, state, now))
    touched = 0
    for key, node in list(state["nodes"].items()):
        if due(node, users_hash(users, node["domain"], int(node["port"])), now):
            state["nodes"][key] = await sync_node(db, node, users)
            touched += 1
    if touched:
        await _store(db, state)
        await db.commit()
    return touched


# ---------------------------------------------------------------- admin

async def _view(db: AsyncSession, state: dict) -> dict:
    from .rw_selfsteal import known_nodes
    now = _naive()
    subs = await _live_subs(db, state, now)
    candidates = []
    for item in await known_nodes(db):
        record = state["nodes"].get(str(item["server_id"]))
        candidates.append({"server_id": item["server_id"], "name": item["name"], "address": item["address"], "domain": item["domain"],
                           "ready": bool(item["domain"]), "installed": bool(record and record.get("state") == "on"),
                           "port": (record or {}).get("port"), "users": (record or {}).get("users"), "synced_at": (record or {}).get("synced_at"),
                           "error": (record or {}).get("error")})
    known = {c["server_id"] for c in candidates}
    for record in state["nodes"].values():          # a node whose installation record is gone still has to be removable
        if record["server_id"] not in known:
            candidates.append({"server_id": record["server_id"], "name": record.get("name") or f"#{record['server_id']}", "address": "",
                               "domain": record["domain"], "ready": True, "installed": record.get("state") == "on", "port": record.get("port"),
                               "users": record.get("users"), "synced_at": record.get("synced_at"), "error": record.get("error")})
    plans = (await db.execute(select(Plan).order_by(Plan.id))).scalars().all()
    return {"enabled": bool(state.get("enabled")), "plan_ids": list(state.get("plan_ids") or []), "port": int(state.get("port") or rw_masque.DEFAULT_PORT),
            "plans": [{"id": p.id, "name": p.name, "enabled": bool(p.enabled), "traffic_limit_gb": p.traffic_limit_gb} for p in plans],
            "nodes": candidates, "users": len(subs), "images": {"xray": rw_masque.XRAY_IMAGE.split("@")[0], "haproxy": rw_masque.HAPROXY_IMAGE.split("@")[0]},
            "notes": ["Трафик MASQUE не входит в лимит трафика тарифа: панель Remnawave его не видит.",
                      "Работает по HTTP/2 (TCP). HTTP/3 спрятать за сайтом нельзя, поэтому он не используется.",
                      "Клиенту нужна поддержка MASQUE в Xray 26.9.30 или новее и подписка в формате JSON."]}


@router.get("/api/admin/masque/panel")
async def panel(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("read"))):
    return await _view(db, await _state(db))


@router.put("/api/admin/masque/panel/settings")
async def save_settings(payload: SettingsIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("provision_nodes"))):
    from .main import audit
    state = await _state(db)
    known = {p.id for p in (await db.execute(select(Plan))).scalars().all()}
    if any(pid not in known for pid in payload.plan_ids):
        raise HTTPException(422, "Выбран тариф, которого нет")
    before = {k: state.get(k) for k in ("enabled", "plan_ids", "port")}
    state.update(enabled=payload.enabled, plan_ids=sorted(set(payload.plan_ids)), port=payload.port)
    await _store(db, state)
    await audit(db, "masque.settings", admin.email, STATE_KEY, {"before": before, "after": {k: state[k] for k in before}})
    await db.commit()
    return await _view(db, state)


@router.post("/api/admin/masque/panel/nodes/{server_id}/install")
async def install(server_id: int, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("provision_nodes"))):
    from .main import audit
    from .rw_api import _busy
    from .rw_selfsteal import known_nodes
    state = await _state(db)
    item = next((n for n in await known_nodes(db) if n["server_id"] == server_id), None)
    if not item:
        raise HTTPException(404, "Это не нода, установленная магазином")
    if not item["domain"]:
        raise HTTPException(409, "У ноды нет сайта SelfSteal: MASQUE прячется за ним. Установите ноду с SelfSteal")
    if await _busy(db, [server_id]):
        raise HTTPException(409, "На сервере идёт установка: дождитесь её окончания")
    node = {"server_id": server_id, "name": item["name"], "domain": item["domain"], "port": int(state.get("port") or rw_masque.DEFAULT_PORT)}
    users = users_of(await _live_subs(db, state, _naive()))
    record = await sync_node(db, node, users, action="on")
    if record.get("error"):
        raise HTTPException(502, record["error"])
    state["nodes"][str(server_id)] = record
    await _store(db, state)
    await audit(db, "masque.node.installed", admin.email, str(server_id), {"domain": node["domain"], "port": node["port"], "users": len(users)})
    await db.commit()
    return await _view(db, state)


@router.post("/api/admin/masque/panel/nodes/{server_id}/remove")
async def remove(server_id: int, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("provision_nodes"))):
    from .main import audit
    state = await _state(db)
    if str(server_id) not in state["nodes"]:
        raise HTTPException(404, "MASQUE на этой ноде не установлен")
    result = await _ssh(db, server_id, "off")
    if result.code != 0:
        raise HTTPException(502, _why(result))
    record = state["nodes"].pop(str(server_id))
    await _store(db, state)
    await audit(db, "masque.node.removed", admin.email, str(server_id), {"domain": record.get("domain")})
    await db.commit()
    return await _view(db, state)


def parse_status(out: str) -> dict:
    """``traffic <login> uplink|downlink <bytes>`` lines and the result line of the node script."""
    traffic: dict[str, dict] = {}
    for line in (out or "").splitlines():
        parts = line.split()
        if len(parts) == 4 and parts[0] == "traffic" and parts[2] in ("uplink", "downlink") and parts[3].isdigit():
            traffic.setdefault(parts[1], {"uplink": 0, "downlink": 0})[parts[2]] = int(parts[3])
    return {"summary": rw_masque.parse_result(out), "traffic": traffic}


@router.post("/api/admin/masque/panel/nodes/{server_id}/status")
async def status(server_id: int, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("read"))):
    """What the node itself says: users in Xray, the certificate, traffic since Xray started (by subscription)."""
    state = await _state(db)
    if str(server_id) not in state["nodes"]:
        raise HTTPException(404, "MASQUE на этой ноде не установлен")
    result = await _ssh(db, server_id, "status")
    if result.code != 0:
        raise HTTPException(502, _why(result))
    parsed = parse_status(result.out)
    logins = {rw_masque.credentials(settings.app_secret, str(s.id))[0]: s for s in await _live_subs(db, state, _naive())}
    rows = [{"subscription_id": logins[login].id if login in logins else None, "user_id": logins[login].user_id if login in logins else None,
             "login": login, **value} for login, value in parsed["traffic"].items()]
    rows.sort(key=lambda r: -(r["uplink"] + r["downlink"]))
    summary = parsed["summary"]
    return {"users": int(summary.get("users") or 0), "port": int(summary.get("port") or 0), "certificate_until": (summary.get("cert") or "").replace("_", " "),
            "traffic": rows[:200]}


@router.post("/api/admin/masque/panel/sync")
async def sync(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("provision_nodes"))):
    from .main import audit
    state = await _state(db)
    users = users_of(await _live_subs(db, state, _naive()))
    for key, node in list(state["nodes"].items()):
        if node.get("state") == "on":
            state["nodes"][key] = await sync_node(db, node, users)
    await _store(db, state)
    await audit(db, "masque.sync", admin.email, STATE_KEY, {"users": len(users), "nodes": len(state["nodes"]),
                                                           "failed": [k for k, n in state["nodes"].items() if n.get("error")]})
    await db.commit()
    return await _view(db, state)


@router.get("/api/admin/masque/panel/users")
async def users(limit: int = 50, offset: int = 0, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("provision_nodes"))):
    """Who has MASQUE now, with the subscription link (a link is a secret: the same right as managing nodes)."""
    state = await _state(db)
    subs = sorted(await _live_subs(db, state, _naive()), key=lambda s: s.id)
    limit, offset = max(1, min(int(limit), 200)), max(0, int(offset))
    return {"total": len(subs), "items": [{"subscription_id": s.id, "user_id": s.user_id, "plan_id": s.plan_id,
                                           "login": rw_masque.credentials(settings.app_secret, str(s.id))[0],
                                           "expires_at": s.expires_at.isoformat() + "Z", "url": link(s.id)} for s in subs[offset:offset + limit]]}


# ---------------------------------------------------------------- the subscription

def link(subscription: int) -> str:
    return f"{settings.public_base_url.rstrip('/')}/api/masque/sub/{token(subscription)}"


@router.get("/api/masque/sub/{value}")
async def subscription(value: str, db: AsyncSession = Depends(get_db)):
    """The MASQUE subscription: a JSON array of whole Xray client configs. The token is the only credential."""
    sid = subscription_id(value)
    sub = await db.get(Subscription, sid) if sid is not None else None
    if sub is None:
        raise HTTPException(404, "Подписка не найдена")
    state = await _state(db)
    if not eligible(sub, state, _naive()):
        raise HTTPException(403, "Подписка не активна или MASQUE для неё не включён")
    configs = configs_for(state, sub)
    if not configs:
        raise HTTPException(503, "MASQUE пока не установлен ни на одной ноде")
    return JSONResponse(configs, headers={"Cache-Control": "no-store", "Profile-Update-Interval": "1",
                                          "Content-Disposition": 'attachment; filename="masque.json"'})


@router.get("/api/me/masque")
async def my_masque(request: Request, db: AsyncSession = Depends(get_db)):
    """The signed-in customer's MASQUE links, one per subscription that has the protocol."""
    from .main import user_from_token
    user = await user_from_token(request, db)
    state = await _state(db)
    now = _naive()
    working = any(n.get("state") == "on" for n in state["nodes"].values())
    subs = (await db.execute(select(Subscription).where(Subscription.user_id == user.id).order_by(Subscription.id))).scalars().all()
    items = [{"subscription_id": s.id, "name": s.name, "url": link(s.id)} for s in subs if working and eligible(s, state, now)]
    return {"available": bool(items), "items": items, "format": "xray-json", "transport": "MASQUE (HTTP/2)"}
