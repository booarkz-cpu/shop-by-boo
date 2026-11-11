"""«Временный бан за торренты»: the address a BitTorrent connection came from is blocked on the node for a set time.

The blocking itself is done by Remnawave's own node plugin Torrent Blocker (panel and node 2.7.0+): Xray on the node
recognises BitTorrent, the node puts the client's address into its nftables table for ``blockDuration`` seconds and
takes it out by itself afterwards; the panel keeps a report of every block. This module only makes it one action
for the owner instead of hand-editing plugin JSON:

* nodes without a plugin get the shop's plugin «CorgiTorrentBan»;
* nodes that already have a plugin keep it — only its ``torrentBlocker`` part is changed, the other parts
  (ingress / egress filters, connection drop) are left as they are;
* a plugin shared with nodes that were not chosen is never changed silently: the request is refused and names them;
* switching off returns exactly what was changed: our plugin is taken off the nodes, a foreign plugin gets
  ``torrentBlocker.enabled = false``.

What the owner is told on the page: the block is by address, so on a shared address (mobile operator NAT, one Wi-Fi
for several people) everyone behind it loses this node for the time of the block; nothing is restarted.
"""
from __future__ import annotations

import copy
import ipaddress
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import require_permission

router = APIRouter(prefix="/api/admin/rw/torrent-ban", tags=["remnawave-torrent-ban"])

UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
PLUGIN_NAME = "CorgiTorrentBan"
REPORTS = 50


class BanIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    minutes: int = Field(default=60, ge=1, le=10080)
    node_uuids: list[str] = Field(min_length=1, max_length=500)
    ignore_ips: list[str] = Field(default_factory=list, max_length=200)

    @field_validator("node_uuids")
    @classmethod
    def uuids_ok(cls, value: list[str]) -> list[str]:
        if not all(UUID.match(v) for v in value):
            raise ValueError("Неверный UUID ноды")
        return list(dict.fromkeys(value))

    @field_validator("ignore_ips")
    @classmethod
    def ips_ok(cls, value: list[str]) -> list[str]:
        out = []
        for item in value:
            try:  # the plugin takes single addresses only, no CIDR (Remnawave docs, Node Plugins)
                out.append(str(ipaddress.ip_address(item.strip())))
            except ValueError:
                raise ValueError(f"«{item}» — не адрес. Нужен один IPv4 или IPv6 без маски") from None
        return list(dict.fromkeys(out))


def _list(value, key: str) -> list[dict]:
    if isinstance(value, dict):
        value = value.get(key, value.get("response", value.get("items", value.get("records", []))))
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


async def _panel(method: str, path: str, **kw):
    from .rw_extensions import _panel as call
    return await call(method, path, **kw)


def _blocker(plugin: dict | None) -> dict:
    part = ((plugin or {}).get("pluginConfig") or {}).get("torrentBlocker")
    return part if isinstance(part, dict) else {}


def with_blocker(config: dict | None, enabled: bool, minutes: int, ignore_ips: list[str]) -> dict:
    """A plugin config with only the torrentBlocker part changed; user ids and rule tags the owner set are kept."""
    out = copy.deepcopy(config) if isinstance(config, dict) else {}
    part = out.get("torrentBlocker") if isinstance(out.get("torrentBlocker"), dict) else {}
    lists = part.get("ignoreLists") if isinstance(part.get("ignoreLists"), dict) else {}
    if enabled:
        part.update({"enabled": True, "blockDuration": minutes * 60, "ignoreLists": {**lists, "ip": list(ignore_ips), "userId": lists.get("userId") or []}})
    else:
        part.update({"enabled": False, "blockDuration": part.get("blockDuration") or 3600, "ignoreLists": {"ip": lists.get("ip") or [], "userId": lists.get("userId") or []}})
    out["torrentBlocker"] = part
    return out


def _pick(record: dict, *paths: str):
    for path in paths:
        value = record
        for key in path.split("."):
            value = value.get(key) if isinstance(value, dict) else None
        if value not in (None, "", {}, []):
            return value
    return None


def _version(value) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", str(value or ""))[:3])


def view(nodes: list[dict], plugins: list[dict], reports: list[dict] | None, stats: dict | None) -> dict:
    by_uuid = {p.get("uuid"): p for p in plugins}
    rows = []
    for node in sorted(nodes, key=lambda n: str(n.get("name") or "")):
        plugin = by_uuid.get(node.get("activePluginUuid"))
        part = _blocker(plugin)
        version = (node.get("versions") or {}).get("node")
        rows.append({
            "uuid": node.get("uuid"), "name": node.get("name"), "country": node.get("countryCode"),
            "online": bool(node.get("isConnected")) and not node.get("isDisabled"),
            "plugin": {"uuid": plugin.get("uuid"), "name": plugin.get("name"), "ours": plugin.get("name") == PLUGIN_NAME} if plugin else None,
            "ban": bool(part.get("enabled")), "minutes": round(int(part.get("blockDuration") or 0) / 60) if part.get("enabled") else None,
            "node_version": version,
            # Plugins need node 2.7.0+; an unknown version is shown as unknown, not as fine.
            "supported": (_version(version) >= (2, 7, 0)) if version else None,
        })
    ours = next((p for p in plugins if p.get("name") == PLUGIN_NAME), None)
    return {
        "nodes": rows, "enabled_nodes": len([r for r in rows if r["ban"]]),
        "ignore_ips": list(((_blocker(ours).get("ignoreLists") or {}).get("ip")) or []),
        "minutes": round(int(_blocker(ours).get("blockDuration") or 3600) / 60),
        "reports_supported": reports is not None,
        # The report's fields differ between panel versions: each value is looked up in the places known so far and
        # shown as empty when it is in none of them — never guessed.
        "reports": [{"at": _pick(r, "createdAt", "created_at"), "node": _pick(r, "node.name", "nodeName"),
                     "user": _pick(r, "user.username", "username", "email", "report.xrayReport.email"),
                     "ip": _pick(r, "ip", "report.actionReport.ip", "report.xrayReport.source"),
                     "seconds": _pick(r, "blockDuration", "report.actionReport.blockDuration")} for r in (reports or [])[:REPORTS]],
        "stats": stats if isinstance(stats, dict) else None,
    }


async def _state() -> dict:
    nodes = _list(await _panel("GET", "/api/nodes"), "nodes")
    try:
        plugins = _list(await _panel("GET", "/api/node-plugins"), "nodePlugins")
    except HTTPException as error:
        # A panel older than 2.7.0 has no plugins at all: say so instead of an error page.
        return {**view(nodes, [], None, None), "panel_supported": False, "panel_error": str(error.detail)[:200]}
    reports, stats = None, None
    try:
        reports = _list(await _panel("GET", "/api/node-plugins/torrent-blocker", params={"start": 0, "size": REPORTS}), "records")
        stats = await _panel("GET", "/api/node-plugins/torrent-blocker/stats")
    except HTTPException:
        reports = reports or None  # the report endpoints are optional: the switch itself still works
    return {**view(nodes, plugins, reports, stats), "panel_supported": True, "panel_error": None}


@router.get("")
async def get_state(admin=Depends(require_permission("read"))):
    return await _state()


@router.put("")
async def apply(payload: BanIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("provision_nodes"))):
    """Switch the temporary ban on or off for the chosen nodes. Safe to repeat."""
    from .main import audit
    nodes = {n.get("uuid"): n for n in _list(await _panel("GET", "/api/nodes"), "nodes")}
    plugins = {p.get("uuid"): p for p in _list(await _panel("GET", "/api/node-plugins"), "nodePlugins")}
    unknown = [u for u in payload.node_uuids if u not in nodes]
    if unknown:
        raise HTTPException(422, f"Нода не найдена в панели: {unknown[0]}")
    chosen = set(payload.node_uuids)
    ours = next((p for p in plugins.values() if p.get("name") == PLUGIN_NAME), None)
    foreign = {}  # plugin uuid -> plugin, for chosen nodes that already have somebody else's plugin
    bare = []     # chosen nodes without a plugin
    for uuid in payload.node_uuids:
        plugin = plugins.get(nodes[uuid].get("activePluginUuid"))
        if plugin is None:
            bare.append(uuid)
        elif plugin.get("name") != PLUGIN_NAME:
            foreign[plugin["uuid"]] = plugin
    # A plugin is one config for all its nodes: changing it would also change nodes that were not chosen.
    for plugin in list(foreign.values()) + ([ours] if ours else []):
        if plugin is ours and not payload.enabled:
            continue  # switching off only takes our plugin off the chosen nodes; its config is not touched
        others = sorted(str(n.get("name")) for u, n in nodes.items() if n.get("activePluginUuid") == plugin["uuid"] and u not in chosen)
        relevant = plugin is not ours or (_blocker(ours).get("blockDuration") != payload.minutes * 60
                                          or ((_blocker(ours).get("ignoreLists") or {}).get("ip") or []) != payload.ignore_ips)
        if others and relevant:
            raise HTTPException(409, f"Плагин «{plugin.get('name')}» общий ещё для нод: {', '.join(others)}. "
                                     "Выберите и их тоже, чтобы настройка была одинаковой, или назначьте им отдельные плагины.")

    changed: list[str] = []
    if payload.enabled:
        if bare or ours:
            if ours is None:
                created = await _panel("POST", "/api/node-plugins", json={"name": PLUGIN_NAME})
                ours = {"uuid": (created or {}).get("uuid"), "name": PLUGIN_NAME, "pluginConfig": (created or {}).get("pluginConfig")}
                if not ours["uuid"]:
                    raise HTTPException(502, "Remnawave: панель не вернула UUID плагина")
            wanted = with_blocker(ours.get("pluginConfig"), True, payload.minutes, payload.ignore_ips)
            if wanted != ours.get("pluginConfig"):
                await _panel("PATCH", "/api/node-plugins", json={"uuid": ours["uuid"], "pluginConfig": wanted})
            for uuid in bare:
                await _panel("PATCH", "/api/nodes", json={"uuid": uuid, "activePluginUuid": ours["uuid"]})
                changed.append(str(nodes[uuid].get("name")))
        for plugin in foreign.values():
            wanted = with_blocker(plugin.get("pluginConfig"), True, payload.minutes, payload.ignore_ips)
            if wanted != plugin.get("pluginConfig"):
                await _panel("PATCH", "/api/node-plugins", json={"uuid": plugin["uuid"], "pluginConfig": wanted})
                changed.append(f"плагин «{plugin.get('name')}»")
    else:
        for uuid in payload.node_uuids:
            if ours and nodes[uuid].get("activePluginUuid") == ours["uuid"]:
                await _panel("PATCH", "/api/nodes", json={"uuid": uuid, "activePluginUuid": None})
                changed.append(str(nodes[uuid].get("name")))
        for plugin in foreign.values():
            if _blocker(plugin).get("enabled"):
                await _panel("PATCH", "/api/node-plugins", json={"uuid": plugin["uuid"], "pluginConfig": with_blocker(plugin.get("pluginConfig"), False, 0, [])})
                changed.append(f"плагин «{plugin.get('name')}»")
    await audit(db, "rw.torrent_ban.enabled" if payload.enabled else "rw.torrent_ban.disabled", admin.email, None,
                {"nodes": len(payload.node_uuids), "minutes": payload.minutes if payload.enabled else None, "changed": changed[:50]})
    await db.commit()
    return {**await _state(), "changed": changed}
