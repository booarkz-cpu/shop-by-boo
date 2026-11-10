"""Auto-selection pool («Пул автовыбора»): one «⚡ Автовыбор» tile in the customer's server list that picks a node itself.

How it works (Remnawave «Xray JSON – Advanced», directive ``remnawave.injectHosts``; Xray ``routing.balancers``):

* the shop keeps one XRAY_JSON subscription template; the chosen hosts are injected into it as outbounds
  ``proxy``, ``proxy-2``, … and a balancer picks one of them by the chosen algorithm;
* the tile is a host bound to that template (``xrayJsonTemplateUuid``): the customer sees one entry;
* «hide the pool nodes» sets ``isHidden`` on the chosen hosts — they leave the list and stay in the pool
  (``selectFrom: "ALL"``); switching it off brings them back after the customer refreshes the subscription.

Who chooses the node: the Xray core inside the customer's app, by the algorithm the owner set here on the panel.
This is the panel pool; «Автовыбор в приложении» of «Корги Люси» is a different thing (the app pings by itself).

What is honest to promise: a real balancer exists only in the Xray JSON format. Clash, Mihomo, sing-box and Base64
clients have no such balancer in a subscription, so the tile is kept out of those formats while the nodes are
visible, and when the nodes are hidden it is left there as a plain entry leading to the first node of the pool
(otherwise those customers would get an empty list). The admin page says so.

Statistics are the panel's own data (hosts and nodes); nothing is invented when the panel does not answer.
"""
from __future__ import annotations

import copy
import re
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import require_permission

router = APIRouter(prefix="/api/admin/rw/autoselect", tags=["remnawave-autoselect"])

CONFIG_KEY = "rw.autoselect"
UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
TEMPLATE_NAME = "CorgiAutoselect"  # the panel accepts latin names only; the customer sees the tile name instead
DEFAULT_NAME = "⚡ Автовыбор"
ALGORITHMS = {
    "leastPing": "По задержке — узел с наименьшим временем ответа",
    "leastLoad": "По нагрузке — узел с самым стабильным ответом за последние замеры",
    "roundRobin": "По кругу — узлы по очереди",
    "random": "Случайно — любой доступный узел",
}
NON_JSON_TYPES = ["XRAY_BASE64", "MIHOMO", "STASH", "CLASH", "SINGBOX"]
PROBE_URL = "https://www.gstatic.com/generate_204"
DEFAULT = {"enabled": False, "name": DEFAULT_NAME, "algorithm": "leastPing", "hide_nodes": False, "hosts": [],
           "template_uuid": "", "tile_uuid": "", "hidden_by_us": [], "applied_at": ""}


class PoolIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(default=DEFAULT_NAME, min_length=1, max_length=40)
    algorithm: str = "leastPing"
    hide_nodes: bool = False
    hosts: list[str] = Field(min_length=1, max_length=200)

    @field_validator("algorithm")
    @classmethod
    def algorithm_ok(cls, value: str) -> str:
        if value not in ALGORITHMS:
            raise ValueError("Алгоритм: leastPing, leastLoad, roundRobin или random")
        return value

    @field_validator("hosts")
    @classmethod
    def hosts_ok(cls, value: list[str]) -> list[str]:
        if not all(UUID.match(v) for v in value):
            raise ValueError("Неверный UUID хоста")
        return list(dict.fromkeys(value))

    @field_validator("name")
    @classmethod
    def name_ok(cls, value: str) -> str:
        value = value.strip()
        if not value or any(ord(ch) < 32 for ch in value):
            raise ValueError("Имя плитки пустое или содержит служебные символы")
        return value


def build_template(base: dict, hosts: list[str], algorithm: str) -> dict:
    """The XRAY_JSON template of the pool on top of the panel's Default template.

    Every algorithm gets an observatory: Xray's random and roundRobin skip dead outbounds only when ``fallbackTag``
    is set and an observatory exists, leastPing needs ``observatory``, leastLoad needs ``burstObservatory``.
    The fallback is ``proxy`` — the first host of the pool (never «direct»: a VPN must not silently go around itself).
    """
    if algorithm not in ALGORITHMS:
        raise ValueError(algorithm)
    if not hosts:
        raise ValueError("empty pool")
    base = copy.deepcopy(base) if isinstance(base, dict) else {}
    routing = base.get("routing") if isinstance(base.get("routing"), dict) else {}
    # A bare «everything → some outbound» rule of the Default would catch every connection before the balancer.
    conditions = lambda rule: [k for k in rule if k not in ("type", "network", "outboundTag", "balancerTag", "ruleTag")]  # noqa: E731
    rules = [r for r in routing.get("rules") or [] if isinstance(r, dict) and conditions(r)]
    out = {
        "dns": base.get("dns") or {"servers": ["1.1.1.1", "1.0.0.1"], "queryStrategy": "UseIP"},
        "inbounds": base.get("inbounds") or [
            {"tag": "socks", "port": 10808, "listen": "127.0.0.1", "protocol": "socks", "settings": {"udp": True, "auth": "noauth"},
             "sniffing": {"enabled": True, "routeOnly": False, "destOverride": ["http", "tls", "quic"]}},
            {"tag": "http", "port": 10809, "listen": "127.0.0.1", "protocol": "http", "settings": {"allowTransparent": False},
             "sniffing": {"enabled": True, "routeOnly": False, "destOverride": ["http", "tls", "quic"]}}],
        "outbounds": base.get("outbounds") or [{"tag": "direct", "protocol": "freedom"}, {"tag": "block", "protocol": "blackhole"}],
        "remnawave": {"injectHosts": [{"selector": {"type": "uuids", "values": list(hosts)}, "selectFrom": "ALL", "tagPrefix": "proxy"}]},
    }
    strategy: dict = {"type": algorithm}
    if algorithm == "leastLoad":
        strategy["settings"] = {"maxRTT": "1s", "expected": 2, "baselines": ["1s"], "tolerance": 0.01}
        out["burstObservatory"] = {"subjectSelector": ["proxy"], "pingConfig": {
            "destination": PROBE_URL, "interval": "30s", "sampling": 2, "timeout": "3s", "connectivity": ""}}
    else:
        out["observatory"] = {"subjectSelector": ["proxy"], "probeUrl": PROBE_URL, "probeInterval": "1m", "enableConcurrency": True}
    out["routing"] = {
        **{k: v for k, v in routing.items() if k not in ("rules", "balancers")},
        "domainStrategy": routing.get("domainStrategy") or "IPIfNonMatch",
        "balancers": [{"tag": "autoselect", "selector": ["proxy"], "strategy": strategy, "fallbackTag": "proxy"}],
        "rules": rules + [{"type": "field", "network": "tcp,udp", "balancerTag": "autoselect"}],
    }
    return out


def _items(value, key: str) -> list[dict]:
    if isinstance(value, dict):
        value = value.get(key, value.get("response", value.get("items", [])))
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


async def _panel(method: str, path: str, **kw):
    from .rw_extensions import _panel as call
    return await call(method, path, **kw)


async def _config(db: AsyncSession) -> dict:
    from .node_health import _load
    return await _load(db, CONFIG_KEY, DEFAULT)


async def _store(db: AsyncSession, config: dict) -> None:
    from .node_health import _save
    await _save(db, CONFIG_KEY, config)


def _host_nodes(host: dict, nodes: list[dict]) -> list[dict]:
    """Nodes that serve a host: the host's own list when set, else every node with the host's inbound switched on."""
    own = {n if isinstance(n, str) else n.get("uuid") for n in host.get("nodes") or []}
    if own:
        return [n for n in nodes if n.get("uuid") in own]
    inbound = (host.get("inbound") or {}).get("configProfileInboundUuid")
    out = []
    for node in nodes:
        active = (node.get("configProfile") or {}).get("activeInbounds") or node.get("activeInbounds") or []
        if inbound and inbound in {a.get("uuid") if isinstance(a, dict) else a for a in active}:
            out.append(node)
    return out


def pool_view(config: dict, hosts: list[dict], nodes: list[dict], json_at_base: bool | None) -> dict:
    """What the admin page shows: every figure is counted from the panel's hosts and nodes."""
    tile = config.get("tile_uuid")
    pool = set(config.get("hosts") or [])
    rows = []
    for host in hosts:
        if host.get("uuid") == tile:
            continue
        serving = _host_nodes(host, nodes)
        online = [n for n in serving if n.get("isConnected") and not n.get("isDisabled")]
        rows.append({
            "uuid": host.get("uuid"), "name": host.get("remark") or "", "address": host.get("address") or "",
            "country": next((n.get("countryCode") for n in serving if n.get("countryCode")), None),
            "in_pool": host.get("uuid") in pool, "hidden": bool(host.get("isHidden")), "disabled": bool(host.get("isDisabled")),
            "online": bool(online) if serving else None,  # None: the panel does not say which node serves the host
            "users_online": sum(int(n.get("usersOnline") or 0) for n in online) if serving else None,
            "nodes": [n.get("name") for n in serving],
        })
    members = [r for r in rows if r["in_pool"]]
    enabled = [r for r in rows if not r["disabled"]]
    tile_host = next((h for h in hosts if h.get("uuid") == tile), None) if tile else None
    return {
        "enabled": bool(config.get("enabled")), "name": config.get("name") or DEFAULT_NAME, "algorithm": config.get("algorithm"),
        "hide_nodes": bool(config.get("hide_nodes")), "applied_at": config.get("applied_at") or None,
        "algorithms": ALGORITHMS, "checked_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "tile": {"exists": bool(tile_host), "name": (tile_host or {}).get("remark"),
                 "visible": bool(tile_host) and not tile_host.get("isHidden") and not tile_host.get("isDisabled"),
                 "formats_excluded": (tile_host or {}).get("excludeFromSubscriptionTypes") or []},
        "stats": {
            "hosts_total": len(enabled), "in_subscription": len([r for r in enabled if not r["hidden"]]),
            "pool_total": len(members), "pool_served": len([r for r in members if not r["disabled"]]),
            "pool_online": len([r for r in members if r["online"]]), "pool_offline": len([r for r in members if r["online"] is False]),
            "pool_unknown": len([r for r in members if r["online"] is None]),
            "excluded": len([r for r in enabled if not r["in_pool"]]),
            "missing": sorted(pool - {r["uuid"] for r in rows}),  # chosen earlier, deleted on the panel since
        },
        "json_at_base": json_at_base,
        "hosts": rows,
    }


async def _panel_state() -> tuple[list[dict], list[dict], bool | None]:
    hosts = _items(await _panel("GET", "/api/hosts"), "hosts")
    nodes = _items(await _panel("GET", "/api/nodes"), "nodes")
    try:
        settings = await _panel("GET", "/api/subscription-settings")
        json_at_base = bool((settings or {}).get("serveJsonAtBaseSubscription")) if isinstance(settings, dict) else None
    except HTTPException:
        json_at_base = None
    return hosts, nodes, json_at_base


@router.get("")
async def get_pool(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("read"))):
    config = await _config(db)
    hosts, nodes, json_at_base = await _panel_state()
    return pool_view(config, hosts, nodes, json_at_base)


async def _set_hidden(uuid: str, hidden: bool) -> None:
    await _panel("PATCH", "/api/hosts", json={"uuid": uuid, "isHidden": hidden})


async def _template(config: dict) -> str:
    """UUID of the pool's template: the stored one if it still exists, else one with our name, else a new one."""
    templates = _items(await _panel("GET", "/api/subscription-templates"), "templates")
    for candidate in templates:
        if candidate.get("uuid") == config.get("template_uuid"):
            return candidate["uuid"]
    for candidate in templates:
        if candidate.get("templateType") == "XRAY_JSON" and candidate.get("name") == TEMPLATE_NAME:
            return candidate["uuid"]
    created = await _panel("POST", "/api/subscription-templates", json={"name": TEMPLATE_NAME, "templateType": "XRAY_JSON"})
    uuid = (created or {}).get("uuid")
    if not uuid:
        raise HTTPException(502, "Remnawave: панель не вернула UUID нового шаблона")
    return uuid


async def _default_json() -> dict:
    templates = _items(await _panel("GET", "/api/subscription-templates"), "templates")
    default = next((t for t in templates if t.get("templateType") == "XRAY_JSON" and t.get("name") == "Default"), None)
    if not default:
        return {}
    full = await _panel("GET", f"/api/subscription-templates/{default['uuid']}")
    body = (full or {}).get("templateJson")
    return body if isinstance(body, dict) else {}


async def apply_pool(db: AsyncSession, payload: PoolIn, actor: str) -> dict:
    from .main import audit
    config = await _config(db)
    hosts, _, _ = await _panel_state()
    by_uuid = {h.get("uuid"): h for h in hosts}
    tile_uuid = config.get("tile_uuid") if config.get("tile_uuid") in by_uuid else ""
    unknown = [u for u in payload.hosts if u not in by_uuid]
    if unknown:
        raise HTTPException(422, f"Хост не найден в панели: {unknown[0]}")
    if tile_uuid in payload.hosts:
        raise HTTPException(422, "Плитка «Автовыбор» не может входить в собственный пул")
    disabled = [by_uuid[u].get("remark") or u for u in payload.hosts if by_uuid[u].get("isDisabled")]
    if disabled:
        raise HTTPException(422, f"Хост выключен в панели и не попадёт в пул: {disabled[0]}")

    template_uuid = await _template(config)
    template = build_template(await _default_json(), payload.hosts, payload.algorithm)
    await _panel("PATCH", "/api/subscription-templates", json={"uuid": template_uuid, "templateJson": template})

    first = by_uuid[payload.hosts[0]]
    if not tile_uuid:
        body = {"remark": payload.name, "address": first.get("address"), "port": first.get("port"),
                "inbound": {"configProfileUuid": (first.get("inbound") or {}).get("configProfileUuid"),
                            "configProfileInboundUuid": (first.get("inbound") or {}).get("configProfileInboundUuid")}}
        for key in ("sni", "host", "path", "alpn", "fingerprint"):
            if first.get(key):
                body[key] = first[key]
        created = await _panel("POST", "/api/hosts", json=body)
        tile_uuid = (created or {}).get("uuid")
        if not tile_uuid:
            raise HTTPException(502, "Remnawave: панель не вернула UUID плитки")
    # Saved before the rest, so a failure below never leaves a tile or a template the shop does not know about.
    config.update({"template_uuid": template_uuid, "tile_uuid": tile_uuid})
    await _store(db, config)
    await db.commit()

    # With the nodes visible the tile lives only in the Xray JSON format (a real balancer). With the nodes hidden it
    # stays in every format, else Clash / sing-box / Base64 customers would get an empty list.
    await _panel("PATCH", "/api/hosts", json={
        "uuid": tile_uuid, "remark": payload.name, "isHidden": False, "isDisabled": False, "xrayJsonTemplateUuid": template_uuid,
        "serverDescription": "Автовыбор узла", "excludeFromSubscriptionTypes": [] if payload.hide_nodes else NON_JSON_TYPES})

    ours = [u for u in config.get("hidden_by_us") or [] if u in by_uuid]
    want = [u for u in payload.hosts if not by_uuid[u].get("isHidden") or u in ours] if payload.hide_nodes else []
    done: list[str] = list(ours)
    try:
        for uuid in want:
            if uuid not in done:
                await _set_hidden(uuid, True)
                done.append(uuid)
        for uuid in list(done):
            if uuid not in want:  # left the pool or hiding was switched off: back into the list
                await _set_hidden(uuid, False)
                done.remove(uuid)
    finally:
        config.update({"enabled": True, "name": payload.name, "algorithm": payload.algorithm, "hide_nodes": payload.hide_nodes,
                       "hosts": payload.hosts, "hidden_by_us": done, "applied_at": datetime.now(UTC).isoformat(timespec="seconds")})
        await _store(db, config)
        await audit(db, "rw.autoselect.applied", actor, tile_uuid,
                    {"algorithm": payload.algorithm, "hosts": len(payload.hosts), "hide_nodes": payload.hide_nodes, "hidden": len(done)})
        await db.commit()
    return config


@router.put("")
async def put_pool(payload: PoolIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("provision_nodes"))):
    """Create or update the pool. Safe to repeat: the same request leaves the panel as it is."""
    await apply_pool(db, payload, admin.email)
    return await get_pool(db, admin)


@router.post("/refresh")
async def refresh_pool(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("provision_nodes"))):
    """«Обновить пул»: apply the saved choice again; hosts deleted on the panel since then drop out of the pool."""
    config = await _config(db)
    if not config.get("enabled"):
        raise HTTPException(409, "Пул автовыбора не включён")
    hosts, _, _ = await _panel_state()
    alive = {h.get("uuid") for h in hosts if not h.get("isDisabled")}
    members = [u for u in config.get("hosts") or [] if u in alive]
    if not members:
        raise HTTPException(409, "В пуле не осталось ни одного включённого хоста. Выберите узлы заново или уберите плитку.")
    await apply_pool(db, PoolIn(name=config["name"], algorithm=config["algorithm"], hide_nodes=config["hide_nodes"], hosts=members), admin.email)
    return await get_pool(db, admin)


@router.delete("")
async def delete_pool(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("provision_nodes"))):
    """«Убрать плитку»: the nodes we hid come back first, then the tile and the template are deleted."""
    from .main import audit
    config = await _config(db)
    hosts = {h.get("uuid") for h in _items(await _panel("GET", "/api/hosts"), "hosts")}
    left = list(config.get("hidden_by_us") or [])
    try:
        for uuid in list(left):
            if uuid in hosts:
                await _set_hidden(uuid, False)
            left.remove(uuid)
        if config.get("tile_uuid") in hosts:
            await _panel("DELETE", f"/api/hosts/{config['tile_uuid']}")
        config["tile_uuid"] = ""
        if config.get("template_uuid"):
            templates = {t.get("uuid") for t in _items(await _panel("GET", "/api/subscription-templates"), "templates")}
            if config["template_uuid"] in templates:
                await _panel("DELETE", f"/api/subscription-templates/{config['template_uuid']}")
        config["template_uuid"] = ""
        config["enabled"] = False
    finally:
        config["hidden_by_us"] = left
        await _store(db, config)
        await audit(db, "rw.autoselect.removed", admin.email, None, {"still_hidden": len(left)})
        await db.commit()
    return await get_pool(db, admin)
