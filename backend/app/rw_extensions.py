"""Remnawave Extension Manager, panel side (v28.69, stage 12; docs/ru/new/REMNAWAVE_EXTENSIONS.md).

Everything here is the panel's own API (contract @remnawave/backend-contract 3.4.15, panel 3.4.8), called with the
shop's token, and each call has a live test against the newest panel (tests/live/test_remnawave_live.py):

* **Config profiles** — list with inbounds and nodes, raw JSON, create / edit / delete; a VLESS + REALITY builder
  (x25519 keys from ``GET /api/system/tools/x25519/generate``, shortIds, serverNames, ``minClientVer``, ``dest`` —
  an outside site or the SelfSteal socket of the node, ``xver``), private/torrent blocking, a host for the inbound;
  the profile and its inbounds bound to nodes (``PATCH /api/nodes``).
* **Node plugins** — TorrentBlocker, Ingress / Egress Filter, Connection Drop (``/api/node-plugins``): create, edit
  the config (the panel validates it), delete, bind to nodes (``activePluginUuid``).
* **Subscription settings** — response rules (SRR), HWID device limit, custom headers and remarks
  (``/api/subscription-settings``) and the panel's SRR tester (``POST /api/system/testers/srr-matcher``).
* **Subscription page configs** and **subscription templates** (Xray JSON, Mihomo, Clash, Stash, sing-box — the
  client balancer lives in an Xray JSON template).

Writes need ``provision_nodes`` (profiles, plugins, nodes) or ``settings.runtime.write`` (subscription settings,
pages, templates) and are written to the audit log. The panel's validation message reaches the administrator."""
from __future__ import annotations

import json
import re
import secrets
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import require_permission

router = APIRouter(prefix="/api/admin/rw/extensions", tags=["remnawave-extensions"])
NAME = r"^[A-Za-z0-9_\s-]+$"
UUID = r"^[0-9a-fA-F-]{36}$"
DOMAIN = re.compile(r"^(?=.{4,253}$)(?!-)[a-z0-9-]{1,63}(?:\.(?!-)[a-z0-9-]{1,63})+$")
SELFSTEAL_SOCKET = "/dev/shm/selfsteal.sock"
PLUGIN_KINDS = ("torrentBlocker", "ingressFilter", "egressFilter", "connectionDrop")
TEMPLATE_TYPES = ("XRAY_JSON", "XRAY_BASE64", "MIHOMO", "STASH", "CLASH", "SINGBOX")


def _list(value, key):
    if isinstance(value, dict):
        value = value.get(key, value.get("response", []))
    return value if isinstance(value, list) else []


async def _panel(method: str, path: str, **kw):
    from .remnawave import RemnawaveClient, RemnawaveNotConfigured
    try:
        return await RemnawaveClient()._request(method, path, **kw)
    except RemnawaveNotConfigured as exc:
        raise HTTPException(503, "Магазин не подключён к панели Remnawave (REMNAWAVE_URL и REMNAWAVE_TOKEN)") from exc
    except Exception as exc:  # noqa: BLE001 — the panel's validation message goes to the administrator
        text = str(exc)
        detail = text.split(": ", 2)[-1] if ": " in text else text
        try:
            body = json.loads(detail)
        except ValueError:
            body = None
        if isinstance(body, dict):
            detail = body.get("message") or body.get("errors") or detail
        raise HTTPException(502, f"Remnawave: {str(detail)[:500]}") from exc


async def _audit(db: AsyncSession, action: str, actor: str, target: str, details: dict | None = None) -> None:
    from .main import audit
    await audit(db, action, actor, target, details or {})
    await db.commit()


# ---------------------------------------------------------------- overview

def _node_view(n: dict) -> dict:
    profile = n.get("configProfile") or {}
    return {"uuid": n.get("uuid"), "name": n.get("name"), "address": n.get("address"), "connected": bool(n.get("isConnected")),
            "profile": profile.get("activeConfigProfileUuid"), "inbounds": [i.get("uuid") if isinstance(i, dict) else i for i in profile.get("activeInbounds") or []],
            "plugin": n.get("activePluginUuid"), "xray": (n.get("versions") or {}).get("xray"), "node_version": (n.get("versions") or {}).get("node")}


@router.get("")
async def overview(admin=Depends(require_permission("read"))):
    profiles = _list(await _panel("GET", "/api/config-profiles"), "configProfiles")
    plugins = _list(await _panel("GET", "/api/node-plugins"), "nodePlugins")
    nodes = [_node_view(n) for n in _list(await _panel("GET", "/api/nodes"), "nodes")]
    return {
        "profiles": [{"uuid": p.get("uuid"), "name": p.get("name"),
                      "inbounds": [{"uuid": i.get("uuid"), "tag": i.get("tag"), "type": i.get("type"), "port": i.get("port"),
                                    "security": i.get("security") or (i.get("rawInbound") or {}).get("streamSettings", {}).get("security")}
                                   for i in p.get("inbounds") or []],
                      "nodes": [n["name"] for n in nodes if n["profile"] == p.get("uuid")]} for p in profiles],
        "plugins": [{"uuid": p.get("uuid"), "name": p.get("name"), "config": p.get("pluginConfig"),
                     "nodes": [n["name"] for n in nodes if n["plugin"] == p.get("uuid")]} for p in plugins],
        "nodes": nodes, "plugin_kinds": PLUGIN_KINDS, "template_types": TEMPLATE_TYPES, "selfsteal_socket": SELFSTEAL_SOCKET,
    }


# ---------------------------------------------------------------- config profiles

class ProfileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=2, max_length=30, pattern=NAME)
    config: dict[str, Any]


class ProfilePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=2, max_length=30, pattern=NAME)
    config: dict[str, Any] | None = None


class RealityIn(BaseModel):
    """VLESS + REALITY (TCP, xtls-rprx-vision): the profile eGamesAPI/remnawave-reverse-proxy (MIT, (c) 2025 eGames)
    creates on install, built here from typed values."""
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=2, max_length=30, pattern=NAME)
    tag: str = Field(default="VLESS_REALITY", min_length=2, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    port: int = Field(default=443, ge=1, le=65535)
    server_names: list[str] = Field(min_length=1, max_length=10)
    dest: Literal["selfsteal", "site"] = "selfsteal"
    target: str | None = Field(default=None, max_length=260)   # host:port of an outside site when dest == "site"
    short_ids: int = Field(default=1, ge=1, le=8)
    min_client_ver: str | None = Field(default=None, pattern=r"^\d+\.\d+\.\d+$")
    block_private: bool = True
    block_torrent: bool = True
    doh: bool = True

    @field_validator("server_names")
    @classmethod
    def names_ok(cls, value: list[str]) -> list[str]:
        out = [v.strip().lower().rstrip(".") for v in value]
        if not all(DOMAIN.match(v) for v in out):
            raise ValueError("serverNames: только доменные имена")
        return list(dict.fromkeys(out))

    @field_validator("target")
    @classmethod
    def target_ok(cls, value: str | None) -> str | None:
        if value is None:
            return None
        host, _, port = value.rpartition(":")
        if not (DOMAIN.match(host.lower()) and port.isdigit() and 0 < int(port) < 65536):
            raise ValueError("Сайт для REALITY: домен:порт, например www.example.com:443")
        return f"{host.lower()}:{int(port)}"


def reality_config(payload: RealityIn, private_key: str) -> dict:
    if payload.dest == "site" and not payload.target:
        raise HTTPException(422, "Укажите сайт для REALITY (домен:порт) или выберите SelfSteal")
    reality = {"show": False, "xver": 1 if payload.dest == "selfsteal" else 0,
               "dest": SELFSTEAL_SOCKET if payload.dest == "selfsteal" else payload.target, "spiderX": "",
               "shortIds": [secrets.token_hex(8) for _ in range(payload.short_ids)], "privateKey": private_key,
               "serverNames": payload.server_names}
    if payload.min_client_ver:
        reality["minClientVer"] = payload.min_client_ver
    rules = []
    if payload.block_private:
        rules.append({"ip": ["geoip:private"], "outboundTag": "BLOCK"})
    if payload.block_torrent:
        rules.append({"protocol": ["bittorrent"], "outboundTag": "BLOCK"})
    config = {
        "log": {"loglevel": "warning"},
        "inbounds": [{"tag": payload.tag, "port": payload.port, "listen": "0.0.0.0", "protocol": "vless",
                      "settings": {"clients": [], "decryption": "none"},
                      "sniffing": {"enabled": True, "destOverride": ["http", "tls", "quic"]},
                      "streamSettings": {"network": "tcp", "security": "reality", "realitySettings": reality}}],
        "outbounds": [{"tag": "DIRECT", "protocol": "freedom"}, {"tag": "BLOCK", "protocol": "blackhole"}],
        "routing": {"rules": rules},
    }
    if payload.doh:
        config["dns"] = {"queryStrategy": "UseIPv4", "servers": [{"address": "https://dns.google/dns-query", "skipFallback": False}]}
    return config


@router.get("/x25519")
async def x25519(admin=Depends(require_permission("provision_nodes"))):
    """A key pair for REALITY, generated by the panel. The private key goes into the profile, the public one is what
    the panel puts into subscriptions."""
    pairs = (await _panel("GET", "/api/system/tools/x25519/generate")).get("keypairs") or []
    if not pairs:
        raise HTTPException(502, "Панель не выдала ключи x25519")
    return {"public_key": pairs[0]["publicKey"], "private_key": pairs[0]["privateKey"]}


@router.get("/profiles/{profile_uuid}")
async def get_profile(profile_uuid: str, admin=Depends(require_permission("read"))):
    if not re.match(UUID, profile_uuid):
        raise HTTPException(422, "Неверный UUID")
    profile = await _panel("GET", f"/api/config-profiles/{profile_uuid}")
    return {"uuid": profile.get("uuid"), "name": profile.get("name"), "config": profile.get("config"),
            "inbounds": profile.get("inbounds") or []}


@router.post("/profiles")
async def create_profile(payload: ProfileIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("provision_nodes"))):
    out = await _panel("POST", "/api/config-profiles", json=payload.model_dump())
    await _audit(db, "rw.profile.created", admin.email, out.get("uuid") or payload.name, {"name": payload.name})
    return {"uuid": out.get("uuid"), "name": out.get("name"), "inbounds": out.get("inbounds") or []}


@router.post("/profiles/reality")
async def create_reality(payload: RealityIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("provision_nodes"))):
    pairs = (await _panel("GET", "/api/system/tools/x25519/generate")).get("keypairs") or []
    if not pairs:
        raise HTTPException(502, "Панель не выдала ключи x25519")
    config = reality_config(payload, pairs[0]["privateKey"])
    out = await _panel("POST", "/api/config-profiles", json={"name": payload.name, "config": config})
    await _audit(db, "rw.profile.created", admin.email, out.get("uuid") or payload.name,
                 {"name": payload.name, "reality": {"dest": payload.dest, "server_names": payload.server_names}})
    return {"uuid": out.get("uuid"), "name": out.get("name"), "inbounds": out.get("inbounds") or [],
            "public_key": pairs[0]["publicKey"], "short_ids": config["inbounds"][0]["streamSettings"]["realitySettings"]["shortIds"]}


@router.patch("/profiles/{profile_uuid}")
async def patch_profile(profile_uuid: str, payload: ProfilePatch, db: AsyncSession = Depends(get_db),
                        admin=Depends(require_permission("provision_nodes"))):
    if not re.match(UUID, profile_uuid):
        raise HTTPException(422, "Неверный UUID")
    body = {"uuid": profile_uuid, **payload.model_dump(exclude_none=True)}
    out = await _panel("PATCH", "/api/config-profiles", json=body)
    await _audit(db, "rw.profile.updated", admin.email, profile_uuid, {"fields": sorted(k for k in body if k != "uuid")})
    return {"uuid": out.get("uuid"), "name": out.get("name"), "inbounds": out.get("inbounds") or []}


@router.delete("/profiles/{profile_uuid}")
async def delete_profile(profile_uuid: str, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("provision_nodes"))):
    if not re.match(UUID, profile_uuid):
        raise HTTPException(422, "Неверный UUID")
    await _panel("DELETE", f"/api/config-profiles/{profile_uuid}")
    await _audit(db, "rw.profile.deleted", admin.email, profile_uuid)
    return {"deleted": True}


class NodeProfileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile_uuid: str = Field(pattern=UUID)
    inbounds: list[str] = Field(min_length=1, max_length=50)


@router.post("/nodes/{node_uuid}/profile")
async def node_profile(node_uuid: str, payload: NodeProfileIn, db: AsyncSession = Depends(get_db),
                       admin=Depends(require_permission("provision_nodes"))):
    if not re.match(UUID, node_uuid) or not all(re.match(UUID, i) for i in payload.inbounds):
        raise HTTPException(422, "Неверный UUID")
    out = await _panel("PATCH", "/api/nodes", json={"uuid": node_uuid, "configProfile": {
        "activeConfigProfileUuid": payload.profile_uuid, "activeInbounds": payload.inbounds}})
    await _audit(db, "rw.node.profile", admin.email, node_uuid, {"profile": payload.profile_uuid, "inbounds": len(payload.inbounds)})
    return _node_view(out)


class ProfileHostIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    inbound_uuid: str = Field(pattern=UUID)
    remark: str = Field(min_length=1, max_length=40)
    address: str = Field(min_length=1, max_length=255)
    port: int = Field(default=443, ge=1, le=65535)
    sni: str = Field(default="", max_length=255)


@router.post("/profiles/{profile_uuid}/host")
async def profile_host(profile_uuid: str, payload: ProfileHostIn, db: AsyncSession = Depends(get_db),
                       admin=Depends(require_permission("provision_nodes"))):
    """The host customers get for the inbound (address and SNI of the node), as the panel's «Хосты»."""
    if not re.match(UUID, profile_uuid):
        raise HTTPException(422, "Неверный UUID")
    out = await _panel("POST", "/api/hosts", json={
        "remark": payload.remark, "address": payload.address, "port": payload.port, "sni": payload.sni or None,
        "inbound": {"configProfileUuid": profile_uuid, "configProfileInboundUuid": payload.inbound_uuid}})
    await _audit(db, "rw.profile.host", admin.email, profile_uuid, {"remark": payload.remark, "address": payload.address})
    return {"uuid": out.get("uuid"), "remark": out.get("remark")}


# ---------------------------------------------------------------- WARP in a profile (v28.70.0)

WARP_TAG = "warp-out"
WARP_DEFAULT = ["whoer.net", "browserleaks.com", "2ip.io", "2ip.ru"]
RULE_VALUE = re.compile(r"^(?:(?:geosite|geoip|domain|full|regexp|keyword):[A-Za-z0-9_.!@:-]{1,120}|(?!-)[a-z0-9.-]{3,253})$")


class WarpIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    domains: list[str] = Field(default_factory=lambda: list(WARP_DEFAULT), max_length=100)

    @field_validator("domains")
    @classmethod
    def domains_ok(cls, value: list[str]) -> list[str]:
        out = [v.strip().lower() if ":" not in v else v.strip() for v in value if v.strip()]
        if not all(RULE_VALUE.match(v) for v in out):
            raise ValueError("Домены: example.com или geosite:имя")
        return list(dict.fromkeys(out))


async def _profile_config(profile_uuid: str) -> tuple[dict, dict]:
    if not re.match(UUID, profile_uuid):
        raise HTTPException(422, "Неверный UUID")
    profile = await _panel("GET", f"/api/config-profiles/{profile_uuid}")
    config = profile.get("config")
    if not isinstance(config, dict):
        raise HTTPException(502, "Панель не вернула конфигурацию профиля")
    return profile, json.loads(json.dumps(config))


async def _save_config(profile_uuid: str, config: dict) -> dict:
    return await _panel("PATCH", "/api/config-profiles", json={"uuid": profile_uuid, "config": config})


ADS = "geosite:category-ads-all"


class AdBlockIn(BaseModel):
    enabled: bool = True


@router.post("/profiles/{profile_uuid}/adblock")
async def profile_adblock(profile_uuid: str, payload: AdBlockIn, db: AsyncSession = Depends(get_db),
                          admin=Depends(require_permission("provision_nodes"))):
    """v28.92.0 (N7 «Блокировка рекламы»): on the node, for every client of the profile — the ad domains of the node's
    geosite.dat go to BLOCK, first of all rules. Switched off, only this rule goes; nothing else in the profile changes."""
    _, config = await _profile_config(profile_uuid)
    routing = config.get("routing") if isinstance(config.get("routing"), dict) else {}
    rules = [r for r in routing.get("rules") or [] if r.get("domain") != [ADS]]
    outbounds = list(config.get("outbounds") or [])
    if payload.enabled:
        rules.insert(0, {"domain": [ADS], "outboundTag": "BLOCK"})
        if not any(o.get("tag") == "BLOCK" for o in outbounds):
            outbounds.append({"tag": "BLOCK", "protocol": "blackhole"})
    config["outbounds"] = outbounds
    config["routing"] = {**routing, "rules": rules}
    await _save_config(profile_uuid, config)
    await _audit(db, "rw.profile.adblock", admin.email, profile_uuid, {"enabled": payload.enabled})
    return {"enabled": payload.enabled}


@router.post("/profiles/{profile_uuid}/warp")
async def profile_warp(profile_uuid: str, payload: WarpIn, db: AsyncSession = Depends(get_db),
                       admin=Depends(require_permission("provision_nodes"))):
    """The outbound ``warp-out`` (freedom through the WireGuard interface ``warp`` the wizard raises on the node —
    module WARP Native) and the rule sending the chosen domains there. Run again, it replaces its own outbound and
    rule; switched off, it removes them. Nothing else in the profile changes."""
    _, config = await _profile_config(profile_uuid)
    outbounds = [o for o in config.get("outbounds") or [] if o.get("tag") != WARP_TAG]
    routing = config.get("routing") if isinstance(config.get("routing"), dict) else {}
    rules = [r for r in routing.get("rules") or [] if r.get("outboundTag") != WARP_TAG]
    if payload.enabled:
        if not payload.domains:
            raise HTTPException(422, "Укажите домены, которые пойдут через WARP")
        outbounds.append({"tag": WARP_TAG, "protocol": "freedom", "settings": {"domainStrategy": "UseIP"},
                          "streamSettings": {"sockopt": {"interface": "warp", "tcpFastOpen": True}}})
        rules.append({"domain": payload.domains, "outboundTag": WARP_TAG})
    config["outbounds"] = outbounds
    config["routing"] = {**routing, "rules": rules}
    await _save_config(profile_uuid, config)
    await _audit(db, "rw.profile.warp", admin.email, profile_uuid, {"enabled": payload.enabled, "domains": len(payload.domains)})
    return {"enabled": payload.enabled, "domains": payload.domains if payload.enabled else []}


# ---------------------------------------------------------------- server routing (v28.70.0)
# A bridge from an entry node (for example in Russia) to an exit node: the exit node gets a Shadowsocks inbound,
# a service user of the panel holds its password (an internal squad gives the user that inbound), and the entry
# profile gets a Shadowsocks outbound to the exit node with rules for Russian addresses — as server_routing of
# eGamesAPI/remnawave-reverse-proxy (MIT, (c) 2025 eGames), built here on the panel's API.

SR_OUT = "SR_BRIDGE_SS"
SR_IN = "SR_BRIDGE_SS_IN"
SR_METHOD = "chacha20-ietf-poly1305"


def _sr_ours(rule: dict) -> bool:
    return rule.get("ip") == ["geoip:ru"] or rule.get("domain") == ["geosite:category-ru"]


def routing_config(config: dict, host: str, port: int, password: str, mode: str) -> dict:
    """The entry profile with our outbound and rules; run again (another exit node or mode), it replaces them."""
    tags = [i.get("tag") for i in config.get("inbounds") or [] if i.get("tag")]
    if not tags:
        raise HTTPException(422, "В профиле входа нет inbound")
    outbounds = [o for o in config.get("outbounds") or [] if o.get("tag") != SR_OUT]
    outbounds.append({"tag": SR_OUT, "protocol": "shadowsocks",
                      "settings": {"servers": [{"address": host, "port": port, "method": SR_METHOD, "password": password, "level": 0}]}})
    for tag, protocol in (("DIRECT", "freedom"), ("BLOCK", "blackhole")):
        if not any(o.get("tag") == tag for o in outbounds):
            outbounds.append({"tag": tag, "protocol": protocol})
    routing = config.get("routing") if isinstance(config.get("routing"), dict) else {}
    keep = [r for r in routing.get("rules") or [] if r.get("outboundTag") != SR_OUT and not _sr_ours(r)]
    rules = list(keep)
    if not any("geoip:private" in (r.get("ip") or []) for r in keep):
        rules.append({"ip": ["geoip:private"], "outboundTag": "BLOCK"})
    if not any("geosite:private" in (r.get("domain") or []) for r in keep):
        rules.append({"domain": ["geosite:private"], "outboundTag": "BLOCK"})
    if not any("bittorrent" in (r.get("protocol") or []) for r in keep):
        rules.append({"protocol": ["bittorrent"], "outboundTag": "BLOCK"})
    ru = SR_OUT if mode == "bridge" else "DIRECT"
    rules += [{"ip": ["geoip:ru"], "outboundTag": ru}, {"domain": ["geosite:category-ru"], "outboundTag": ru}]
    if mode == "direct":
        rules.append({"inboundTag": tags, "outboundTag": SR_OUT})
    return {**config, "outbounds": outbounds, "routing": {**routing, "rules": rules}}


def unrouting_config(config: dict) -> dict:
    outbounds = [o for o in config.get("outbounds") or [] if o.get("tag") != SR_OUT]
    routing = config.get("routing") if isinstance(config.get("routing"), dict) else {}
    rules = [r for r in routing.get("rules") or []
             if r.get("outboundTag") != SR_OUT and not (_sr_ours(r) and r.get("outboundTag") == "DIRECT")]
    return {**config, "outbounds": outbounds, "routing": {**routing, "rules": rules}}


class RoutingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entry_profile_uuid: str = Field(pattern=UUID)
    exit_node_uuid: str = Field(pattern=UUID)
    port: int = Field(default=8443, ge=1024, le=65535)
    # direct — Russian addresses straight from the entry node, everything else through the exit node;
    # bridge — only Russian addresses through the exit node, the rest as the profile had it.
    mode: Literal["direct", "bridge"] = "direct"


def _names(entry: str) -> tuple[str, str]:
    short = entry.replace("-", "")[:8]
    return f"SR Bridge {short}", f"srbridge{short}"


async def _user_by_name(username: str) -> dict | None:
    try:
        out = await _panel("GET", f"/api/users/by-username/{username}")
    except HTTPException:
        return None
    return out if isinstance(out, dict) and out.get("username") == username else None


@router.get("/routing")
async def list_routing(admin=Depends(require_permission("read"))):
    out = []
    for p in _list(await _panel("GET", "/api/config-profiles"), "configProfiles"):
        config = p.get("config") if isinstance(p.get("config"), dict) else None
        if config is None and p.get("uuid"):
            config = (await _panel("GET", f"/api/config-profiles/{p['uuid']}")).get("config") or {}
        bridge = next((o for o in (config or {}).get("outbounds") or [] if o.get("tag") == SR_OUT), None)
        if not bridge:
            continue
        server = ((bridge.get("settings") or {}).get("servers") or [{}])[0]
        rules = ((config or {}).get("routing") or {}).get("rules") or []
        mode = "bridge" if any(r.get("ip") == ["geoip:ru"] and r.get("outboundTag") == SR_OUT for r in rules) else "direct"
        out.append({"profile_uuid": p.get("uuid"), "profile": p.get("name"), "exit": f"{server.get('address')}:{server.get('port')}", "mode": mode})
    return {"bridges": out}


@router.post("/routing")
async def create_routing(payload: RoutingIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("provision_nodes"))):
    entry, entry_config = await _profile_config(payload.entry_profile_uuid)
    node = await _panel("GET", f"/api/nodes/{payload.exit_node_uuid}")
    current = node.get("configProfile") or {}
    exit_uuid = current.get("activeConfigProfileUuid")
    if not exit_uuid:
        raise HTTPException(422, "У ноды выхода нет профиля конфигурации")
    if exit_uuid == payload.entry_profile_uuid:
        raise HTTPException(422, "Нода выхода работает на профиле входа: выберите ноду с другим профилем")
    # 1. Shadowsocks inbound on the exit node's profile (added once; the node keeps serving its customers).
    _, exit_config = await _profile_config(exit_uuid)
    inbounds = [i for i in exit_config.get("inbounds") or [] if i.get("tag") != SR_IN]
    inbounds.append({"tag": SR_IN, "port": payload.port, "listen": "0.0.0.0", "protocol": "shadowsocks",
                     "settings": {"method": SR_METHOD, "network": "tcp,udp", "clients": []},
                     "sniffing": {"enabled": True, "destOverride": ["http", "tls", "quic"]}})
    await _save_config(exit_uuid, {**exit_config, "inbounds": inbounds})
    exit_profile = await _panel("GET", f"/api/config-profiles/{exit_uuid}")
    inbound = next((i.get("uuid") for i in exit_profile.get("inbounds") or [] if i.get("tag") == SR_IN), None)
    if not inbound:
        raise HTTPException(502, "Панель не создала inbound моста на профиле выхода")
    active = [i.get("uuid") if isinstance(i, dict) else i for i in current.get("activeInbounds") or []]
    if inbound not in active:
        await _panel("PATCH", "/api/nodes", json={"uuid": payload.exit_node_uuid, "configProfile": {
            "activeConfigProfileUuid": exit_uuid, "activeInbounds": [*active, inbound]}})
    # 2. Internal squad with that inbound and the service user whose password the bridge uses.
    squad_name, username = _names(payload.entry_profile_uuid)
    squads = _list(await _panel("GET", "/api/internal-squads"), "internalSquads")
    squad = next((s for s in squads if s.get("name") == squad_name), None)
    if squad:
        await _panel("PATCH", "/api/internal-squads", json={"uuid": squad["uuid"], "inbounds": [inbound]})
    else:
        squad = await _panel("POST", "/api/internal-squads", json={"name": squad_name, "inbounds": [inbound]})
    user = await _user_by_name(username)
    if user and user.get("ssPassword"):
        password = user["ssPassword"]
    else:
        password = secrets.token_urlsafe(18)[:24]
        await _panel("POST", "/api/users", json={
            "username": username, "status": "ACTIVE", "expireAt": "2099-12-31T23:59:59.000Z", "trafficLimitBytes": 0,
            "activeInternalSquads": [squad["uuid"]], "ssPassword": password,
            "description": "Lucy: служебный пользователь моста серверного роутинга"})
    # 3. The entry profile: outbound to the exit node and the rules of the chosen mode.
    await _save_config(payload.entry_profile_uuid, routing_config(entry_config, node.get("address"), payload.port, password, payload.mode))
    await _audit(db, "rw.routing.created", admin.email, payload.entry_profile_uuid,
                 {"exit_node": payload.exit_node_uuid, "port": payload.port, "mode": payload.mode})
    return {"profile": entry.get("name"), "exit": f"{node.get('address')}:{payload.port}", "mode": payload.mode,
            "note": f"Откройте TCP и UDP порт {payload.port} на сервере выхода для адреса ноды входа (если включён файрвол)."}


@router.delete("/routing/{profile_uuid}")
async def delete_routing(profile_uuid: str, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("provision_nodes"))):
    """Removes our outbound and rules from the entry profile, the service user and the squad. The inbound on the exit
    node stays: other bridges may use it (it is removed in the exit profile's JSON when no longer needed)."""
    _, config = await _profile_config(profile_uuid)
    await _save_config(profile_uuid, unrouting_config(config))
    squad_name, username = _names(profile_uuid)
    user = await _user_by_name(username)
    if user and user.get("id") is not None:
        await _panel("DELETE", f"/api/users/{user['id']}")
    squad = next((s for s in _list(await _panel("GET", "/api/internal-squads"), "internalSquads") if s.get("name") == squad_name), None)
    if squad:
        await _panel("DELETE", f"/api/internal-squads/{squad['uuid']}")
    await _audit(db, "rw.routing.deleted", admin.email, profile_uuid)
    return {"deleted": True}


# ---------------------------------------------------------------- node plugins

class PluginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=2, max_length=30, pattern=NAME)


class PluginPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=2, max_length=30, pattern=NAME)
    config: dict[str, Any] | None = None


@router.post("/plugins")
async def create_plugin(payload: PluginIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("provision_nodes"))):
    """A plugin starts with the panel's example config (all plugins off); then it is edited and bound to nodes."""
    out = await _panel("POST", "/api/node-plugins", json={"name": payload.name})
    await _audit(db, "rw.plugin.created", admin.email, out.get("uuid") or payload.name, {"name": payload.name})
    return {"uuid": out.get("uuid"), "name": out.get("name"), "config": out.get("pluginConfig")}


@router.patch("/plugins/{plugin_uuid}")
async def patch_plugin(plugin_uuid: str, payload: PluginPatch, db: AsyncSession = Depends(get_db),
                       admin=Depends(require_permission("provision_nodes"))):
    if not re.match(UUID, plugin_uuid):
        raise HTTPException(422, "Неверный UUID")
    body: dict = {"uuid": plugin_uuid}
    if payload.name:
        body["name"] = payload.name
    if payload.config is not None:
        body["pluginConfig"] = payload.config
    out = await _panel("PATCH", "/api/node-plugins", json=body)
    enabled = sorted(k for k, v in (out.get("pluginConfig") or {}).items() if isinstance(v, dict) and v.get("enabled"))
    await _audit(db, "rw.plugin.updated", admin.email, plugin_uuid, {"enabled": enabled})
    return {"uuid": out.get("uuid"), "name": out.get("name"), "config": out.get("pluginConfig")}


@router.delete("/plugins/{plugin_uuid}")
async def delete_plugin(plugin_uuid: str, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("provision_nodes"))):
    if not re.match(UUID, plugin_uuid):
        raise HTTPException(422, "Неверный UUID")
    await _panel("DELETE", f"/api/node-plugins/{plugin_uuid}")
    await _audit(db, "rw.plugin.deleted", admin.email, plugin_uuid)
    return {"deleted": True}


class NodePluginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plugin_uuid: str | None = Field(default=None, pattern=UUID)


@router.post("/nodes/{node_uuid}/plugin")
async def node_plugin(node_uuid: str, payload: NodePluginIn, db: AsyncSession = Depends(get_db),
                      admin=Depends(require_permission("provision_nodes"))):
    if not re.match(UUID, node_uuid):
        raise HTTPException(422, "Неверный UUID")
    out = await _panel("PATCH", "/api/nodes", json={"uuid": node_uuid, "activePluginUuid": payload.plugin_uuid})
    await _audit(db, "rw.node.plugin", admin.email, node_uuid, {"plugin": payload.plugin_uuid})
    return _node_view(out)


# ---------------------------------------------------------------- subscription settings (SRR, HWID, headers)

class SubscriptionSettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    response_rules: dict[str, Any] | None = None
    hwid_settings: dict[str, Any] | None = None
    custom_response_headers: dict[str, str] | None = None
    randomize_hosts: bool | None = None
    serve_json_at_base_subscription: bool | None = None
    is_show_custom_remarks: bool | None = None
    custom_remarks: dict[str, Any] | None = None

    @field_validator("custom_response_headers")
    @classmethod
    def headers_ok(cls, value):
        if value and not all(re.fullmatch(r"[A-Za-z0-9_-]{1,64}", k) and "\n" not in v and len(v) <= 500 for k, v in value.items()):
            raise ValueError("Заголовок: имя из букв, цифр, _ и -; значение — одна строка до 500 символов")
        return value


FIELDS = {"response_rules": "responseRules", "hwid_settings": "hwidSettings", "custom_response_headers": "customResponseHeaders",
          "randomize_hosts": "randomizeHosts", "serve_json_at_base_subscription": "serveJsonAtBaseSubscription",
          "is_show_custom_remarks": "isShowCustomRemarks", "custom_remarks": "customRemarks"}


@router.get("/subscription-settings")
async def subscription_settings(admin=Depends(require_permission("read"))):
    return await _panel("GET", "/api/subscription-settings")


@router.patch("/subscription-settings")
async def patch_subscription_settings(payload: SubscriptionSettingsIn, db: AsyncSession = Depends(get_db),
                                      admin=Depends(require_permission("settings.runtime.write"))):
    current = await _panel("GET", "/api/subscription-settings")
    body = {"uuid": current.get("uuid"), **{FIELDS[k]: v for k, v in payload.model_dump(exclude_none=True).items()}}
    out = await _panel("PATCH", "/api/subscription-settings", json=body)
    await _audit(db, "rw.subscription_settings.updated", admin.email, str(current.get("uuid")), {"fields": sorted(k for k in body if k != "uuid")})
    return out


class SrrTestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    response_rules: dict[str, Any]
    user_agent: str = Field(default="", max_length=300)
    headers: dict[str, str] = Field(default_factory=dict, max_length=10)


@router.post("/srr-test")
async def srr_test(payload: SrrTestIn, admin=Depends(require_permission("read"))):
    """Which rule a client with these headers would hit — the panel's own matcher, nothing is saved."""
    headers = {k: v for k, v in payload.headers.items() if re.fullmatch(r"[A-Za-z0-9-]{1,64}", k) and "\n" not in v}
    if payload.user_agent:
        headers["User-Agent"] = payload.user_agent.replace("\n", " ")
    return await _panel("POST", "/api/system/testers/srr-matcher", json={"responseRules": payload.response_rules}, extra_headers=headers)


# ---------------------------------------------------------------- subscription page configs and templates

class NamedJsonIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=2, max_length=60, pattern=NAME)


class SubpagePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=2, max_length=60, pattern=NAME)
    config: Any = None


@router.get("/subpage-configs")
async def subpage_configs(admin=Depends(require_permission("read"))):
    return {"configs": _list(await _panel("GET", "/api/subscription-page-configs"), "configs")}


@router.get("/subpage-configs/{config_uuid}")
async def subpage_config(config_uuid: str, admin=Depends(require_permission("read"))):
    if not re.match(UUID, config_uuid):
        raise HTTPException(422, "Неверный UUID")
    return await _panel("GET", f"/api/subscription-page-configs/{config_uuid}")


@router.post("/subpage-configs")
async def create_subpage_config(payload: NamedJsonIn, db: AsyncSession = Depends(get_db),
                                admin=Depends(require_permission("settings.runtime.write"))):
    out = await _panel("POST", "/api/subscription-page-configs", json={"name": payload.name})
    await _audit(db, "rw.subpage_config.created", admin.email, out.get("uuid") or payload.name)
    return out


@router.patch("/subpage-configs/{config_uuid}")
async def patch_subpage_config(config_uuid: str, payload: SubpagePatch, db: AsyncSession = Depends(get_db),
                               admin=Depends(require_permission("settings.runtime.write"))):
    if not re.match(UUID, config_uuid):
        raise HTTPException(422, "Неверный UUID")
    body = {"uuid": config_uuid, **({"name": payload.name} if payload.name else {}),
            **({"config": payload.config} if payload.config is not None else {})}
    out = await _panel("PATCH", "/api/subscription-page-configs", json=body)
    await _audit(db, "rw.subpage_config.updated", admin.email, config_uuid)
    return out


@router.delete("/subpage-configs/{config_uuid}")
async def delete_subpage_config(config_uuid: str, db: AsyncSession = Depends(get_db),
                                admin=Depends(require_permission("settings.runtime.write"))):
    if not re.match(UUID, config_uuid):
        raise HTTPException(422, "Неверный UUID")
    await _panel("DELETE", f"/api/subscription-page-configs/{config_uuid}")
    await _audit(db, "rw.subpage_config.deleted", admin.email, config_uuid)
    return {"deleted": True}


class TemplateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=2, max_length=60, pattern=NAME)
    template_type: Literal["XRAY_JSON", "XRAY_BASE64", "MIHOMO", "STASH", "CLASH", "SINGBOX"]


class TemplatePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=2, max_length=60, pattern=NAME)
    template_json: dict[str, Any] | None = None
    template_yaml: str | None = Field(default=None, max_length=200000)


@router.get("/templates")
async def templates(admin=Depends(require_permission("read"))):
    return {"templates": _list(await _panel("GET", "/api/subscription-templates"), "templates")}


@router.get("/templates/{template_uuid}")
async def template(template_uuid: str, admin=Depends(require_permission("read"))):
    if not re.match(UUID, template_uuid):
        raise HTTPException(422, "Неверный UUID")
    return await _panel("GET", f"/api/subscription-templates/{template_uuid}")


@router.post("/templates")
async def create_template(payload: TemplateIn, db: AsyncSession = Depends(get_db),
                          admin=Depends(require_permission("settings.runtime.write"))):
    out = await _panel("POST", "/api/subscription-templates", json={"name": payload.name, "templateType": payload.template_type})
    await _audit(db, "rw.template.created", admin.email, out.get("uuid") or payload.name, {"type": payload.template_type})
    return out


@router.patch("/templates/{template_uuid}")
async def patch_template(template_uuid: str, payload: TemplatePatch, db: AsyncSession = Depends(get_db),
                         admin=Depends(require_permission("settings.runtime.write"))):
    if not re.match(UUID, template_uuid):
        raise HTTPException(422, "Неверный UUID")
    import base64
    body: dict = {"uuid": template_uuid}
    if payload.name:
        body["name"] = payload.name
    if payload.template_json is not None:
        body["templateJson"] = payload.template_json
    if payload.template_yaml is not None:
        body["encodedTemplateYaml"] = base64.b64encode(payload.template_yaml.encode()).decode()
    out = await _panel("PATCH", "/api/subscription-templates", json=body)
    await _audit(db, "rw.template.updated", admin.email, template_uuid, {"fields": sorted(k for k in body if k != "uuid")})
    return out


@router.delete("/templates/{template_uuid}")
async def delete_template(template_uuid: str, db: AsyncSession = Depends(get_db),
                          admin=Depends(require_permission("settings.runtime.write"))):
    if not re.match(UUID, template_uuid):
        raise HTTPException(422, "Неверный UUID")
    await _panel("DELETE", f"/api/subscription-templates/{template_uuid}")
    await _audit(db, "rw.template.deleted", admin.email, template_uuid)
    return {"deleted": True}


BALANCER_TEMPLATE = {
    "observatory": {"subjectSelector": ["proxy"], "probeUrl": "https://www.gstatic.com/generate_204", "probeInterval": "1m",
                    "enableConcurrency": True},
    "routing": {"balancers": [{"tag": "Balancer", "selector": ["proxy"], "strategy": {"type": "leastPing"},
                               "fallbackTag": "direct"}],
                "rules": [{"network": "tcp,udp", "balancerTag": "Balancer"}]},
}


@router.get("/presets")
async def presets(admin=Depends(require_permission("read"))):
    """Ready-made fragments: the client balancer for an Xray JSON template (one entry in the client's list that picks
    the fastest node, the idea of client_balancer in eGamesAPI/remnawave-reverse-proxy) and plugin config parts."""
    return {"client_balancer_xray_json": BALANCER_TEMPLATE,
            "plugins": {"torrentBlocker": {"enabled": True, "blockDuration": 3600, "ignoreLists": {"ip": []}},
                        "ingressFilter": {"enabled": True, "blockedIps": []},
                        "egressFilter": {"enabled": True, "blockedIps": [], "blockedPorts": [25, 465, 587]},
                        "connectionDrop": {"enabled": True, "whitelistIps": []}}}
