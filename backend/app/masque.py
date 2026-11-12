"""MASQUE (CONNECT-IP, RFC 9484): what is confirmed, what a node needs, and why it is not switched on yet.

Checked against the official sources on 2026-11-12 (``docs/MASQUE_IMPLEMENTATION_REPORT.md`` has the commits):

* Xray-core has a MASQUE inbound, outbound and transport since the tag v26.9.30; there is no tag v26.10.10 —
  the first tag not older than it is v26.10.21, and that is the version this module asks of a node;
* the transport works only over TLS (REALITY is not supported), HTTP/3 listens on UDP and HTTP/2 on TCP;
* the Remnawave panel (3.4.10) knows nothing about MASQUE: it does not put users into such an inbound and does not
  write it into a subscription. Until that changes the shop has nothing honest to switch on, so ``can_enable`` is
  False and the page only shows the readiness of the nodes and the prepared, validated configuration.

Everything here is pure except the page endpoint, which reads the nodes and profiles from the panel and changes nothing.
"""
from __future__ import annotations

import ipaddress
import re

from fastapi import APIRouter, Depends, Query

from .security import require_permission

router = APIRouter(prefix="/api/admin/masque", tags=["masque"])

FIRST_TAG = (26, 9, 30)      # the first official Xray-core tag that carries proxy/masque
REQUIRED = (26, 10, 21)      # the first official tag not older than the owner's «v26.10.10+» (that tag does not exist)
DEFAULT_PORT = 2087          # free next to the transports of rw_plan.TRANSPORTS on both TCP and UDP
DEFAULT_PATH = "/.well-known/masque/ip/{target}/{ipproto}/"
DEFAULT_ADDRESS = ("10.77.0.1/24", "fd77::1/64")
HTTP = {"h3": "udp", "h2": "tcp"}
UDP_NETWORKS = {"hysteria", "kcp", "mkcp", "quic"}
VERSION = re.compile(r"(?<![\d.])v?(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?![\d.])")

BLOCKERS = (
    {"key": "panel", "title": "Панель Remnawave не знает MASQUE",
     "text": "Панель 3.4.10 не добавляет пользователей в inbound MASQUE и не пишет его в подписку. Без этого клиент не получит "
             "ни логин, ни адрес сервера."},
    {"key": "link", "title": "Нет общей ссылки для клиента",
     "text": "У v2rayNG ссылка masque:// описывает только Cloudflare WARP (ключи устройства), а не сервер с логином и паролем. "
             "Такой сервер передаётся только целым JSON-конфигом."},
    {"key": "reality", "title": "Не работает с REALITY",
     "text": "MASQUE идёт только через обычный TLS с сертификатом домена ноды, поэтому ставится отдельным портом рядом с REALITY."},
)

__all__ = ["router", "parse_version", "core_state", "inbound", "outbound", "port_conflicts", "readiness"]


def parse_version(text: str | None) -> tuple[int, int, int] | None:
    """``Xray 26.11.9 (Xray, Penetrates Everything.)`` → (26, 11, 9); None when there is no version in the text."""
    match = VERSION.search(str(text or ""))
    return (int(match[1]), int(match[2]), int(match[3])) if match else None


def core_state(version: str | None) -> str:
    """``ready`` — the node's Xray is not older than REQUIRED; ``old``; ``unknown`` — the node did not report a version."""
    parsed = parse_version(version)
    if parsed is None:
        return "unknown"
    return "ready" if parsed >= REQUIRED else "old"


def _address(value) -> list[str]:
    out, families = [], set()
    for raw in value:
        try:
            net = ipaddress.ip_interface(str(raw).strip())
        except ValueError as exc:
            raise ValueError(f"Неверный диапазон адресов туннеля: {raw}") from exc
        limit = 30 if net.version == 4 else 126
        if net.network.prefixlen > limit:
            raise ValueError(f"Слишком узкий диапазон {raw}: длина префикса не больше /{limit}")
        if net.version in families:
            raise ValueError("Не больше одного диапазона IPv4 и одного IPv6")
        families.add(net.version)
        out.append(str(net))
    if not out:
        raise ValueError("Нужен хотя бы один диапазон адресов туннеля")
    return out


def _http(value) -> list[str]:
    out = list(dict.fromkeys(str(v).lower() for v in value))
    if not out or any(v not in HTTP for v in out):
        raise ValueError("Версии HTTP: h3 (UDP), h2 (TCP) или обе")
    return out


def _users(value) -> list[dict]:
    out, seen = [], set()
    for user in value:
        email, password = str(user.get("email") or "").strip(), str(user.get("pass") or "")
        if not email or ":" in email:
            raise ValueError("Логин обязателен и не может содержать двоеточие")
        if email.lower() in seen:
            raise ValueError(f"Логин повторяется: {email}")
        if not password:
            raise ValueError(f"У пользователя {email} нет пароля")
        seen.add(email.lower())
        out.append({"email": email, "pass": password, "level": int(user.get("level") or 0)})
    return out


def _path(path: str) -> str:
    if not path.startswith("/") or re.search(r"\{(?!\??(target|ipproto|target,ipproto)\})", path):
        raise ValueError("Путь начинается с «/» и может содержать только {target} и {ipproto}")
    return path


def inbound(domain: str, certificate: str, key: str, users=(), *, tag: str = "MASQUE", port: int = DEFAULT_PORT, http=("h3", "h2"),
            address=DEFAULT_ADDRESS, mtu: int = 1280, path: str = DEFAULT_PATH) -> dict:
    """A MASQUE inbound exactly as the official Xray documentation describes it. With no users Xray rejects every tunnel."""
    if not re.fullmatch(r"(?=.{4,253}$)([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}", domain):
        raise ValueError("Нужен домен ноды: MASQUE работает только с сертификатом TLS")
    if not 1 <= int(port) <= 65535:
        raise ValueError("Порт от 1 до 65535")
    if not 1280 <= int(mtu) <= 65535:
        raise ValueError("MTU от 1280 до 65535")
    return {"tag": tag, "port": int(port), "listen": "0.0.0.0", "protocol": "masque",
            "settings": {"users": _users(users), "address": _address(address), "mtu": int(mtu)},
            "streamSettings": {"method": "masque", "masqueSettings": {"path": _path(path)}, "security": "tls",
                               "tlsSettings": {"serverName": domain, "alpn": _http(http),
                                               "certificates": [{"certificateFile": certificate, "keyFile": key}]}}}


def outbound(domain: str, user: str, password: str, *, port: int = DEFAULT_PORT, http: str = "h3", path: str = DEFAULT_PATH,
             tag: str = "masque") -> dict:
    """The client side for the same server: one HTTP version (h3, or h2 where UDP is closed). Mux is not supported."""
    if http not in HTTP:
        raise ValueError("Клиент выбирает одну версию: h3 или h2")
    if not user or ":" in user or not password:
        raise ValueError("Нужны логин без двоеточия и пароль")
    return {"tag": tag, "protocol": "masque", "settings": {"address": domain, "port": int(port)},
            "streamSettings": {"method": "masque", "masqueSettings": {"path": _path(path), "user": user, "pass": password},
                               "security": "tls", "tlsSettings": {"serverName": domain, "alpn": [http]}}}


def _listens(item: dict) -> set[str]:
    """Which layer-4 protocols an existing inbound occupies on its port."""
    stream = item.get("streamSettings") or {}
    name = str(stream.get("method") or stream.get("network") or "tcp").lower()
    if str(item.get("protocol") or "").lower() == "masque" or name == "masque":
        alpn = [str(a).lower() for a in (stream.get("tlsSettings") or {}).get("alpn") or []]
        return {"tcp", "udp"} if "h2" in alpn and "h3" in alpn else {"tcp"} if "h2" in alpn else {"udp"}
    if str(item.get("protocol") or "").lower() in ("hysteria", "wireguard") or name in UDP_NETWORKS:
        return {"udp"}
    if str(item.get("protocol") or "").lower() in ("shadowsocks", "dokodemo-door", "tunnel", "socks"):
        return {"tcp", "udp"}
    return {"tcp"}


def port_conflicts(inbounds: list[dict], port: int = DEFAULT_PORT, http=("h3", "h2"), tag: str = "MASQUE") -> list[str]:
    """Why MASQUE cannot listen on ``port`` next to the inbounds of a profile (an empty list: it can)."""
    wanted = {HTTP[v] for v in _http(http)}
    out = []
    for item in inbounds:
        if not isinstance(item, dict) or item.get("tag") == tag:
            continue
        try:
            same = int(item.get("port")) == int(port)
        except (TypeError, ValueError):
            continue
        for layer in sorted(wanted & _listens(item)) if same else ():
            out.append(f"{layer.upper()} {port} занят inbound «{item.get('tag') or item.get('protocol')}»")
    return out


def readiness(nodes: list[dict], profiles: list[dict], port: int = DEFAULT_PORT, http=("h3", "h2")) -> dict:
    """What the page shows: every node's Xray against REQUIRED, every profile's port conflicts, and the blockers."""
    rows = []
    for node in nodes:
        version = (node.get("versions") or {}).get("xray") or node.get("xrayVersion")
        parsed = parse_version(version)
        rows.append({"uuid": node.get("uuid"), "name": node.get("name") or "—", "xray": ".".join(map(str, parsed)) if parsed else None,
                     "state": core_state(version)})
    checks = [{"uuid": p.get("uuid"), "name": p.get("name") or "—",
               "conflicts": port_conflicts((p.get("config") or {}).get("inbounds") or [], port, http)} for p in profiles]
    return {"required": "v" + ".".join(map(str, REQUIRED)), "first_tag": "v" + ".".join(map(str, FIRST_TAG)), "port": int(port),
            "http": _http(http), "nodes": rows, "nodes_ready": sum(r["state"] == "ready" for r in rows), "profiles": checks,
            "blockers": list(BLOCKERS), "can_enable": False,
            "example": inbound("node.example.com", "/var/lib/corgi-hysteria/cert.pem", "/var/lib/corgi-hysteria/key.pem",
                               port=port, http=http)}


def _list(value, key: str) -> list[dict]:
    if isinstance(value, dict):
        value = value.get(key, value.get("response", value.get("items", [])))
        if isinstance(value, dict):
            value = value.get(key, [])
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


@router.get("")
async def state(port: int = Query(DEFAULT_PORT, ge=1, le=65535), admin=Depends(require_permission("read"))):
    """Readiness for MASQUE. Read-only: nothing on the panel or the nodes is changed."""
    from .rw_extensions import _panel
    nodes = _list(await _panel("GET", "/api/nodes"), "nodes")
    profiles = _list(await _panel("GET", "/api/config-profiles"), "configProfiles")
    return readiness(nodes, profiles, port)
