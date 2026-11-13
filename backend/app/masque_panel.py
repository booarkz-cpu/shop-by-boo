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
TRAFFIC_KEY = "masque.traffic"
# Owner's decision of 2026-11-12: whether MASQUE traffic counts towards the plan's limit is a switch, on by default.
DEFAULT = {"enabled": False, "plan_ids": [], "port": rw_masque.DEFAULT_PORT, "nodes": {}, "epochs": {}, "reissued_at": {},
           "count_in_limit": True}
STACK = 2                                          # the layout of a node's stack; an older one is reinstalled by the worker
COLLECT = timedelta(minutes=5)                     # how often a node is asked for traffic
RECHECK = timedelta(minutes=15)                    # how often the panel is asked about one subscription's usage
PANEL_CALLS = 30                                   # at most this many panel questions per pass
GB = 1024 ** 3
ALERT_AFTER = timedelta(minutes=10)               # a node failing this long is reported to the administrator
CERT_WARN = timedelta(days=14)                    # a certificate that ends sooner is reported
LIVE = ("active", "grace", "cancel_scheduled")     # paid and not paused, frozen or expired
RESYNC = timedelta(minutes=30)                     # a node is re-checked this often even when the list did not change
TOKEN = re.compile(r"^(\d{1,12})\.([0-9a-f]{32})\Z")

__all__ = ["router", "token", "subscription_id", "eligible", "users_of", "users_hash", "tick", "sync_node"]


class SettingsIn(BaseModel):
    enabled: bool
    plan_ids: list[int] = Field(default_factory=list, max_length=200)
    port: int = Field(default=rw_masque.DEFAULT_PORT, ge=1024, le=65535)
    count_in_limit: bool = True


class ShieldIn(BaseModel):
    strict_sni: bool = True
    tls_like_site: bool = True
    probe_ban: bool = True
    ban_after: int = Field(default=rw_masque.SHIELD_DEFAULT["ban_after"], ge=5, le=500)
    ban_minutes: int = Field(default=rw_masque.SHIELD_DEFAULT["ban_minutes"], ge=1, le=1440)


class InstallIn(BaseModel):
    shield: ShieldIn = Field(default_factory=ShieldIn)


# ---------------------------------------------------------------- pure

def epoch_of(state: dict, subscription: int) -> int:
    """How many times the link of a subscription was reissued (0: never)."""
    return int((state.get("epochs") or {}).get(str(int(subscription))) or 0)


def key_of(state: dict, subscription: int) -> str:
    """What the login, the password and the link of a subscription follow from; a reissue changes it."""
    epoch = epoch_of(state, subscription)
    return f"{int(subscription)}:{epoch}" if epoch else str(int(subscription))


def token(subscription: int, state: dict | None = None) -> str:
    key = key_of(state or {}, subscription)
    sig = hmac.new(settings.app_secret.encode(), f"masque-sub:{key}".encode(), hashlib.sha256).hexdigest()[:32]
    return f"{int(subscription)}.{sig}"


def subscription_id(value: str, state: dict | None = None) -> int | None:
    """The subscription a link belongs to; None for a link the shop did not issue or has reissued since."""
    match = TOKEN.match(value or "")
    if not match or not hmac.compare_digest(token(int(match[1]), state), value):
        return None
    return int(match[1])


def eligible(sub, state: dict, now: datetime, over: frozenset | set = frozenset()) -> bool:
    """A subscription has MASQUE while it is paid and running, its plan is among the chosen ones (none chosen: all)
    and — when MASQUE counts towards the plan's limit — the limit is not used up (``over``: those that used it up)."""
    if not state.get("enabled") or sub.expires_at is None or sub.expires_at <= now:
        return False
    if state.get("count_in_limit", True) and sub.id in over:
        return False
    if (sub.lifecycle_status or "active") not in LIVE:
        return False
    plans = state.get("plan_ids") or []
    return not plans or sub.plan_id in plans


def creds(state: dict, subscription: int) -> tuple[str, str]:
    return rw_masque.credentials(settings.app_secret, key_of(state, subscription))


def users_of(subs, state: dict | None = None) -> list[dict]:
    out = []
    for sub in sorted(subs, key=lambda s: s.id):
        login, password = creds(state or {}, sub.id)
        # Owner's decision of 2026-11-12: as many tunnels at once as the plan allows devices (none set: no limit).
        out.append({"email": login, "pass": password, "limit": int(getattr(sub, "device_limit_snapshot", None) or 0)})
    return out


def users_hash(users: list[dict], domain: str, port: int) -> str:
    text = "\n".join(sorted(f"{u['email']}:{int(u.get('limit') or 0)}" for u in users)) + f"\n{domain}:{port}"
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _naive(now: datetime | None = None) -> datetime:
    return (now or datetime.now(UTC)).replace(tzinfo=None)


def _iso(now: datetime) -> str:
    return now.replace(microsecond=0).isoformat() + "Z"


def prefix_of(server_id: int) -> str:
    return rw_masque.new_prefix(settings.app_secret, f"server-{int(server_id)}")


def configs_for(state: dict, sub) -> list[dict]:
    """The subscription itself: one whole client config per working node."""
    login, password = creds(state, sub.id)
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


async def _traffic(db: AsyncSession) -> dict:
    from .node_health import _load
    data = await _load(db, TRAFFIC_KEY, {"subs": {}, "over": []})
    data["subs"], data["over"] = dict(data.get("subs") or {}), list(data.get("over") or [])
    return data


async def _live_subs(db: AsyncSession, state: dict, now: datetime, limited: bool = True) -> list:
    """Subscriptions that have MASQUE now. ``limited=False``: without the traffic-limit rule (who would have it)."""
    if not state.get("enabled"):
        return []
    rows = (await db.execute(select(Subscription).where(Subscription.expires_at.is_not(None), Subscription.expires_at > now,
                                                        Subscription.lifecycle_status.in_(LIVE)))).scalars().all()
    over = frozenset((await _traffic(db))["over"]) if limited and state.get("count_in_limit", True) else frozenset()
    return [s for s in rows if eligible(s, state, now, over)]


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


REASONS = {"port busy": "Порт MASQUE на сервере занят другой программой: выберите другой порт в настройках",
           "nodocker": "На сервере нет Docker", "noselfsteal": "На ноде не запущен сайт SelfSteal: MASQUE прячется за ним",
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
    data = rw_masque.bundle(node["domain"], int(node["port"]), prefix_of(node["server_id"]), users, node.get("shield"))
    now = _naive()
    try:
        result = await _ssh(db, node["server_id"], action, node["domain"], str(node["port"]), hashlib.sha256(data).hexdigest(), stdin=data)
        error = None if result.code == 0 else _why(result)
    except HTTPException as exc:
        error = str(exc.detail)[:300]
    if error:
        return {**node, "error": error, "checked_at": _iso(now), "failing_since": node.get("failing_since") or _iso(now)}
    node = {k: v for k, v in node.items() if k not in ("failing_since", "alerted_failure")}
    return {**node, "state": "on", "error": None, "users": len(users), "hash": users_hash(users, node["domain"], int(node["port"])),
            "synced_at": _iso(now), "checked_at": _iso(now), **({"stack": STACK} if action == "on" else {})}


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
    if await collect(db, state, now):
        await _store(db, state)
        await db.commit()
    users = users_of(await _live_subs(db, state, now), state)
    touched = 0
    for key, node in list(state["nodes"].items()):
        if node.get("state") == "on" and int(node.get("stack") or 1) != STACK:
            # Installed by an older release: the stack is recreated once (its tunnels reconnect).
            state["nodes"][key] = await sync_node(db, node, users, action="on")
            touched += 1
        elif due(node, users_hash(users, node["domain"], int(node["port"])), now):
            state["nodes"][key] = await sync_node(db, node, users)
            touched += 1
    messages = alerts(state, now)
    if messages:
        from .rw_autoupdate import _notify
        await _notify("\n".join(messages) + "\nПодробности: «Смена протокола» → «MASQUE: ноды и подписка».")
    if touched or messages:
        await _store(db, state)
        await db.commit()
    return touched


# ---------------------------------------------------------------- alerts

def cert_until(text: str | None) -> datetime | None:
    """``Nov_13_17:28:00_2026_GMT`` (what the node script prints) → a naive UTC time."""
    try:
        return datetime.strptime(" ".join(str(text or "").replace("_", " ").split()), "%b %d %H:%M:%S %Y GMT")
    except ValueError:
        return None


def alerts(state: dict, now: datetime) -> list[str]:
    """What to tell the administrator now (once per problem): a node failing for 10 minutes, a certificate ending
    within 14 days. Marks what it reported in the node records."""
    out = []
    for node in state["nodes"].values():
        if node.get("state") != "on":
            continue
        since = _since(node.get("failing_since"))
        if since and now - since >= ALERT_AFTER and not node.get("alerted_failure"):
            out.append(f"MASQUE на ноде «{node.get('name') or node['domain']}» не сверяется с {node['failing_since'][11:16]} UTC: {node.get('error')}")
            node["alerted_failure"] = True
        until = cert_until(node.get("cert_until"))
        if until and until - now <= CERT_WARN and node.get("alerted_cert") != node.get("cert_until"):
            days = max(0, (until - now).days)
            out.append(f"Сертификат MASQUE на ноде «{node.get('name') or node['domain']}» истекает через {days} дн. ({until:%d.%m.%Y}). "
                       "Его выпускает сайт SelfSteal ноды: проверьте DNS домена и порт 80.")
            node["alerted_cert"] = node.get("cert_until")
    return out


# ---------------------------------------------------------------- traffic and the plan's limit

def _since(text: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00")).astimezone(UTC).replace(tzinfo=None) if text else None
    except ValueError:
        return None


def add_traffic(entry: dict | None, delta: int, now: datetime) -> dict:
    """One subscription's MASQUE counter. Without word from the panel it starts anew every calendar month."""
    entry = dict(entry or {})
    since = _since(entry.get("since"))
    if since is None or (since.year, since.month) != (now.year, now.month) and not entry.get("panel_reset"):
        entry.update(bytes=0, since=_iso(now))
    entry["bytes"] = int(entry.get("bytes") or 0) + max(0, int(delta))
    return entry


def judge(entry: dict, limit_bytes: int | None, panel: dict | None, now: datetime) -> dict:
    """Whether the plan's limit is used up, counting MASQUE together with what the panel has counted.

    ``panel``: the panel's user (``usedTrafficBytes``, ``trafficLimitBytes``, ``lastTrafficResetAt``) or None when the
    panel did not answer — then MASQUE alone is compared with the plan's limit."""
    entry = dict(entry)
    panel = panel or {}
    traffic = panel.get("userTraffic") or {}
    reset = _since(panel.get("lastTrafficResetAt") or traffic.get("lastTrafficResetAt"))
    since = _since(entry.get("since"))
    if reset and (since is None or reset > since):          # the panel started a new period: so does MASQUE
        entry.update(bytes=0, since=_iso(reset), panel_reset=True)
    used = panel.get("usedTrafficBytes", traffic.get("usedTrafficBytes", panel.get("trafficUsedBytes")))
    remote_limit = panel.get("trafficLimitBytes")
    limit = int(remote_limit) if remote_limit else int(limit_bytes or 0)
    entry["panel_used"] = int(used) if used is not None else None
    entry["limit"] = limit or None
    entry["over"] = bool(limit) and int(entry.get("bytes") or 0) + int(used or 0) >= limit
    entry["checked_at"] = _iso(now)
    return entry


async def collect(db: AsyncSession, state: dict, now: datetime) -> bool:
    """Asks the nodes what each login moved, adds it to the subscriptions' counters and decides who used up the limit.
    Returns True when a node record changed (its ``traffic_at``)."""
    from .node_health import _save
    nodes = [n for n in state["nodes"].values() if n.get("state") == "on" and int(n.get("stack") or 1) == STACK
             and ((_since(n.get("traffic_at")) or datetime.min) + COLLECT <= now)]
    data = await _traffic(db)
    subs = {s.id: s for s in await _live_subs(db, state, now, limited=False)}
    logins = {creds(state, sid)[0]: sid for sid in subs}
    changed = False
    for node in nodes:
        node["traffic_at"] = _iso(now)
        changed = True
        try:
            result = await _ssh(db, node["server_id"], "traffic")
        except HTTPException:
            continue
        if result.code != 0:
            continue
        parsed = parse_status(result.out)
        if parsed["cert"]:
            node["cert_until"] = parsed["cert"]
        for login, value in parsed["traffic"].items():
            sid = logins.get(login)
            if sid is not None:
                data["subs"][str(sid)] = add_traffic(data["subs"].get(str(sid)), value["uplink"] + value["downlink"], now)
    asked = 0
    for key, entry in list(data["subs"].items()):
        sub = subs.get(int(key))
        if sub is None:
            continue
        limit = int(sub.traffic_limit_gb_snapshot) * GB if getattr(sub, "traffic_limit_gb_snapshot", None) else None
        if not limit or not state.get("count_in_limit", True):
            entry["over"] = False
            continue
        last = _since(entry.get("checked_at"))
        if last and now - last < RECHECK or asked >= PANEL_CALLS:
            continue
        asked += 1
        data["subs"][key] = judge(entry, limit, await _panel_user(sub), now)
    data["over"] = sorted(int(k) for k, e in data["subs"].items() if e.get("over"))
    if nodes or asked:
        await _save(db, TRAFFIC_KEY, data)
    return changed


async def _panel_user(sub) -> dict | None:
    if not getattr(sub, "remnawave_uuid", None):
        return None
    try:
        from .main import RemnawaveClient
        data = await RemnawaveClient().get_user(sub.remnawave_uuid)
    except Exception:                                  # noqa: BLE001 — the panel is down: MASQUE alone is compared
        return None
    return data if isinstance(data, dict) else None


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
                           "error": (record or {}).get("error"), "shield": rw_masque.shield((record or {}).get("shield")) if record else None})
    known = {c["server_id"] for c in candidates}
    for record in state["nodes"].values():          # a node whose installation record is gone still has to be removable
        if record["server_id"] not in known:
            candidates.append({"server_id": record["server_id"], "name": record.get("name") or f"#{record['server_id']}", "address": "",
                               "domain": record["domain"], "ready": True, "installed": record.get("state") == "on", "port": record.get("port"),
                               "users": record.get("users"), "synced_at": record.get("synced_at"), "error": record.get("error"),
                               "shield": rw_masque.shield(record.get("shield"))})
    plans = (await db.execute(select(Plan).order_by(Plan.id))).scalars().all()
    over = len((await _traffic(db))["over"]) if state.get("count_in_limit", True) else 0
    return {"enabled": bool(state.get("enabled")), "plan_ids": list(state.get("plan_ids") or []), "port": int(state.get("port") or rw_masque.DEFAULT_PORT),
            "count_in_limit": bool(state.get("count_in_limit", True)), "over_limit": over,
            "plans": [{"id": p.id, "name": p.name, "enabled": bool(p.enabled), "traffic_limit_gb": p.traffic_limit_gb} for p in plans],
            "nodes": candidates, "users": len(subs), "images": {"xray": rw_masque.XRAY_IMAGE.split("@")[0], "haproxy": rw_masque.HAPROXY_IMAGE.split("@")[0]},
            "shield_default": dict(rw_masque.SHIELD_DEFAULT),
            "notes": ["Трафик MASQUE считает магазин: панель Remnawave его не видит. При включённой настройке он складывается с трафиком "
                      "панели, и когда лимит тарифа исчерпан, доступ MASQUE снимается до нового периода.",
                      "Одновременных туннелей у подписки — столько, сколько устройств разрешает тариф.",
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
    before = {k: state.get(k) for k in ("enabled", "plan_ids", "port", "count_in_limit")}
    state.update(enabled=payload.enabled, plan_ids=sorted(set(payload.plan_ids)), port=payload.port, count_in_limit=payload.count_in_limit)
    await _store(db, state)
    await audit(db, "masque.settings", admin.email, STATE_KEY, {"before": before, "after": {k: state[k] for k in before}})
    await db.commit()
    return await _view(db, state)


@router.post("/api/admin/masque/panel/nodes/{server_id}/install")
async def install(server_id: int, payload: InstallIn | None = None, db: AsyncSession = Depends(get_db),
                  admin=Depends(require_permission("provision_nodes"))):
    """Installs MASQUE on a node with the protections chosen for it; on an installed node — changes the protections
    (the stack is recreated, open tunnels reconnect)."""
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
    previous = state["nodes"].get(str(server_id)) or {}
    chosen = rw_masque.shield((payload or InstallIn()).shield.model_dump())
    node = {"server_id": server_id, "name": item["name"], "domain": item["domain"], "shield": chosen,
            "port": int(previous.get("port") or state.get("port") or rw_masque.DEFAULT_PORT)}
    users = users_of(await _live_subs(db, state, _naive()), state)
    record = await sync_node(db, node, users, action="on")
    if record.get("error"):
        raise HTTPException(502, record["error"])
    state["nodes"][str(server_id)] = record
    await _store(db, state)
    await audit(db, "masque.node.installed", admin.email, str(server_id), {"domain": node["domain"], "port": node["port"], "users": len(users), "shield": chosen,
                                                                         "reinstall": bool(previous)})
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


def compare(reference: dict, candidate: dict) -> list[str]:
    """How the MASQUE port's answer differs from the site's own answer on port 443 (an empty list: no difference)."""
    out = []
    if reference["status"] != candidate["status"]:
        out.append(f"код ответа {candidate['status']} вместо {reference['status']}")
    if reference["body"] != candidate["body"]:
        out.append("другое содержимое страницы")
    for name in sorted(set(reference["headers"]) | set(candidate["headers"])):
        if name in ("date", "alt-svc", "age"):          # the time of the answer; the site's own HTTP/3 advert
            continue
        a, b = reference["headers"].get(name), candidate["headers"].get(name)
        if a != b:
            out.append(f"заголовок {name}: " + ("лишний" if a is None else "отсутствует" if b is None else "другое значение"))
    return out


async def _fetch(url: str) -> dict:
    import httpx
    async with httpx.AsyncClient(http2=False, timeout=10, follow_redirects=False) as client:
        response = await client.get(url, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"})
    return {"status": response.status_code, "body": hashlib.sha256(response.content).hexdigest(),
            "headers": {k.lower(): v for k, v in response.headers.items()}}


@router.post("/api/admin/masque/panel/nodes/{server_id}/probe")
async def probe(server_id: int, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("read"))):
    """Looks at the node from outside, as a censor's scanner would: the MASQUE port must answer exactly as the site
    does on port 443 — on the home page, on a missing page and on the secret path itself."""
    import secrets

    import httpx
    state = await _state(db)
    node = state["nodes"].get(str(server_id))
    if not node:
        raise HTTPException(404, "MASQUE на этой ноде не установлен")
    site, masked = f"https://{node['domain']}", f"https://{node['domain']}:{int(node['port'])}"
    missing = "/" + secrets.token_hex(6) + ".html"
    checks = [("Главная страница", "/", "/"), ("Несуществующая страница", missing, missing),
              ("Секретный путь без туннеля", missing, f"/{prefix_of(server_id)}/1/2/")]
    rows = []
    for title, reference_path, masked_path in checks:
        try:
            reference, candidate = await _fetch(site + reference_path), await _fetch(masked + masked_path)
        except httpx.HTTPError as exc:                 # the node or the port is not reachable from the shop
            rows.append({"check": title, "same": False, "differences": [f"нет ответа: {type(exc).__name__}"]})
            continue
        differences = compare(reference, candidate)
        rows.append({"check": title, "same": not differences, "differences": differences})
    return {"domain": node["domain"], "port": int(node["port"]), "same": all(r["same"] for r in rows), "checks": rows,
            "limits": ["Порт не 443: сайт на нестандартном порту сам по себе необычен.",
                       "Отпечаток TLS у порта MASQUE и у сайта разный: параметры приближены, но серверы разные.",
                       "Долгое соединение HTTP/2 с большим объёмом данных заметно при анализе трафика."]}


def parse_status(out: str) -> dict:
    """``traffic <login> uplink|downlink <bytes>`` lines and the result line of the node script."""
    traffic: dict[str, dict] = {}
    cert = None
    for line in (out or "").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] == "cert":
            cert = parts[1]
        if len(parts) == 4 and parts[0] == "traffic" and parts[2] in ("uplink", "downlink") and parts[3].isdigit():
            traffic.setdefault(parts[1], {"uplink": 0, "downlink": 0})[parts[2]] = int(parts[3])
    return {"summary": rw_masque.parse_result(out), "traffic": traffic, "cert": cert}


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
    logins = {creds(state, s.id)[0]: s for s in await _live_subs(db, state, _naive())}
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
    users = users_of(await _live_subs(db, state, _naive()), state)
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
    subs = sorted(await _live_subs(db, state, _naive(), limited=False), key=lambda s: s.id)
    limit, offset = max(1, min(int(limit), 200)), max(0, int(offset))
    traffic = await _traffic(db)
    counted = bool(state.get("count_in_limit", True))
    return {"total": len(subs), "items": [{"subscription_id": s.id, "user_id": s.user_id, "plan_id": s.plan_id,
                                           "traffic_bytes": int((traffic["subs"].get(str(s.id)) or {}).get("bytes") or 0),
                                           "over_limit": counted and s.id in traffic["over"], "tunnels": int(s.device_limit_snapshot or 0),
                                           "login": creds(state, s.id)[0], "reissued": epoch_of(state, s.id),
                                           "expires_at": s.expires_at.isoformat() + "Z", "url": link(s.id, state)} for s in subs[offset:offset + limit]]}


# ---------------------------------------------------------------- the subscription

def link(subscription: int, state: dict | None = None) -> str:
    return f"{settings.public_base_url.rstrip('/')}/api/masque/sub/{token(subscription, state)}"


async def _reissue(db: AsyncSession, state: dict, sub) -> None:
    """A new login, password and link for one subscription; the old ones stop working at once on every node."""
    epochs = dict(state.get("epochs") or {})
    epochs[str(sub.id)] = epoch_of(state, sub.id) + 1
    state["epochs"] = epochs
    users = users_of(await _live_subs(db, state, _naive()), state)
    for key, node in list(state["nodes"].items()):
        if node.get("state") == "on":
            state["nodes"][key] = await sync_node(db, node, users)
    await _store(db, state)


@router.post("/api/admin/masque/panel/users/{subscription}/reissue")
async def reissue(subscription: int, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("provision_nodes"))):
    from .main import audit
    sub = await db.get(Subscription, subscription)
    if sub is None:
        raise HTTPException(404, "Подписка не найдена")
    state = await _state(db)
    await _reissue(db, state, sub)
    await audit(db, "masque.link.reissued", admin.email, str(sub.id), {"user_id": sub.user_id, "by": "admin"})
    await db.commit()
    return {"subscription_id": sub.id, "url": link(sub.id, state), "login": creds(state, sub.id)[0]}


SUB_LIMIT, SUB_WINDOW = 60, 600       # requests per address and per link in ten minutes (clients refresh about hourly)


async def _sub_allowed(request: Request | None, value: str) -> bool:
    """A link guesser or a leaked link pulled by a crowd runs into this before the database is asked."""
    from .main import _client_ip, redis_client
    from .runtime_security import rate_allowed
    ip = _client_ip(request) if request is not None else "-"
    key = hashlib.sha256(value.encode()).hexdigest()[:16]
    return (await rate_allowed(redis_client, f"rl:masque-sub:ip:{ip}", SUB_LIMIT, SUB_WINDOW)
            and await rate_allowed(redis_client, f"rl:masque-sub:link:{key}", SUB_LIMIT, SUB_WINDOW))


@router.get("/api/masque/sub/{value}")
async def subscription(value: str, db: AsyncSession = Depends(get_db), request: Request = None):
    """The MASQUE subscription: a JSON array of whole Xray client configs. The token is the only credential."""
    if not await _sub_allowed(request, value):
        raise HTTPException(429, "Слишком много запросов: повторите позже", headers={"Retry-After": str(SUB_WINDOW)})
    state = await _state(db)
    sid = subscription_id(value, state)
    sub = await db.get(Subscription, sid) if sid is not None else None
    if sub is None:
        raise HTTPException(404, "Подписка не найдена")
    if not eligible(sub, state, _naive()):
        raise HTTPException(403, "Подписка не активна или MASQUE для неё не включён")
    if state.get("count_in_limit", True) and sub.id in (await _traffic(db))["over"]:
        raise HTTPException(403, "Лимит трафика тарифа исчерпан: MASQUE вернётся с началом нового периода")
    configs = configs_for(state, sub)
    if not configs:
        raise HTTPException(503, "MASQUE пока не установлен ни на одной ноде")
    return JSONResponse(configs, headers={"Cache-Control": "no-store", "Profile-Update-Interval": "1",
                                          "Content-Disposition": 'attachment; filename="masque.json"'})


async def customer_items(db: AsyncSession, user_id: int) -> tuple[list[dict], dict]:
    """A customer's MASQUE links, one per subscription that has the protocol now (shared by the cabinet and the bot)."""
    state = await _state(db)
    now = _naive()
    working = any(n.get("state") == "on" for n in state["nodes"].values())
    subs = (await db.execute(select(Subscription).where(Subscription.user_id == user_id).order_by(Subscription.id))).scalars().all()
    traffic = await _traffic(db)
    over = frozenset(traffic["over"]) if state.get("count_in_limit", True) else frozenset()
    items = [{"subscription_id": s.id, "name": s.name, "url": link(s.id, state), "over_limit": s.id in over,
              "traffic_bytes": int((traffic["subs"].get(str(s.id)) or {}).get("bytes") or 0), "tunnels": int(s.device_limit_snapshot or 0)}
             for s in subs if working and eligible(s, state, now)]
    return items, state


@router.get("/api/me/masque")
async def my_masque(request: Request, db: AsyncSession = Depends(get_db)):
    """The signed-in customer's MASQUE links, one per subscription that has the protocol."""
    from .main import user_from_token
    user = await user_from_token(request, db)
    items, state = await customer_items(db, user.id)
    return {"available": bool(items), "items": items, "format": "xray-json", "transport": "MASQUE (HTTP/2)",
            "counts_in_limit": bool(state.get("count_in_limit", True))}


@router.get("/api/me/masque/{subscription}/qr")
async def my_masque_qr(subscription: int, request: Request, db: AsyncSession = Depends(get_db)):
    """A QR code of the customer's own MASQUE link (for a client on another device)."""
    from .main import user_from_token
    from .wg_pool import qr_data_url
    user = await user_from_token(request, db)
    sub = await db.get(Subscription, subscription)
    state = await _state(db)
    if sub is None or sub.user_id != user.id or not eligible(sub, state, _naive()):
        raise HTTPException(404, "Подписка MASQUE недоступна")
    return JSONResponse({"png": qr_data_url(link(sub.id, state)), "name": sub.name}, headers={"Cache-Control": "private, no-store"})


@router.post("/api/me/masque/{subscription}/reissue")
async def my_masque_reissue(subscription: int, request: Request, db: AsyncSession = Depends(get_db)):
    """The customer replaces a leaked link: a new one is issued and the old one stops working."""
    from .main import audit, user_from_token
    user = await user_from_token(request, db)
    sub = await db.get(Subscription, subscription)
    state = await _state(db)
    if sub is None or sub.user_id != user.id or not eligible(sub, state, _naive()):
        raise HTTPException(404, "Подписка MASQUE недоступна")
    last = (state.get("reissued_at") or {}).get(str(sub.id))
    now = _naive()
    if last and now - datetime.fromisoformat(last.rstrip("Z")) < timedelta(minutes=10):
        raise HTTPException(429, "Ссылку можно менять не чаще раза в 10 минут")
    state["reissued_at"] = {**(state.get("reissued_at") or {}), str(sub.id): _iso(now)}
    await _reissue(db, state, sub)
    await audit(db, "masque.link.reissued", f"user:{user.id}", str(sub.id), {"user_id": user.id, "by": "customer"})
    await db.commit()
    return {"subscription_id": sub.id, "name": sub.name, "url": link(sub.id, state)}
