"""Subscription proxy: the shop serves the subscription links itself and fetches the configs from the panel.

Remnawave usually lives abroad behind Cloudflare; from Russia its subscription domain often does not open and the
VPN clients stop updating. With the proxy switched on, customers get ``https://<public domain>/<shortUuid>`` (the
shop's own domain, «Серверы → Прослойка подписки»); the shop fetches the subscription from the panel (the internal
address by default) and answers the client. On the way it can:

* **block a device** by HWID — the device gets a stub (one placeholder server named with the owner's text) instead
  of the configs; HWID comes from ``x-hwid`` or, for clients that can only change the User-Agent, from
  ``x-hwid=…`` inside the User-Agent;
* **rewrite response headers per app** (profile title, announce, update interval…): rules by User-Agent and OS;
* **add links** — extra servers (VLESS, WireGuard… URIs) for the customers of an Internal Squad, and the servers
  of a second subscription merged into the same link. Only for URI-list subscriptions (plain or base64); JSON and
  YAML formats are passed unchanged, and nothing is added for a blocked device, an inactive subscription or when the
  panel reports a device limit (``x-hwid-*`` headers);
* **log every request** (app, version, OS, model, decision, size, time) — «Журнал подписки», 14 days by default —
  and mark clients older than the latest release from the app catalogue (``client_versions.py``);
* show a **neutral page** for everything that is not a subscription request (scanners see no proxy).

The panel's own subscription link keeps working: the proxy only adds a second door. Off by default.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import logging
import re
import time
from datetime import datetime, timedelta

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import get_db
from .security import require_permission

logger = logging.getLogger("vpnshop.sub_proxy")
router = APIRouter()
CONFIG_KEY = "sub_proxy.config"
DEFAULT: dict = {
    "enabled": False,
    "public_base": "",           # https://sub.example.ru — the links customers get
    "origin": "",                # empty: <REMNAWAVE_URL>/api/sub
    "prefix": "",                # /<prefix>/<shortUuid> on the public domain; both forms are accepted
    "rewrite_links": True,       # customers see the proxy link in the cabinet, Mini App, bot and apps
    "mask": True,                # a neutral page for non-subscription requests
    "mask_title": "Вход",
    "ua_hwid": True,
    "block_text": "Устройство отключено — напишите в поддержку",
    "blocked_hwids": [],         # [{"hwid": "...", "note": "...", "at": "..."}]
    "rules": [],                 # [{"name", "ua", "os", "headers": {...}}]
    "extras": [],                # [{"name", "squad", "links": [...]}]
    "merge_url": "",             # second subscription: https://.../{short_uuid}
    "log_days": 14,
}
TOKEN = re.compile(r"^[A-Za-z0-9_-]{6,64}$")
FORWARD_REQUEST = ("user-agent", "accept", "accept-language", "x-hwid", "x-device-os", "x-ver-os", "x-device-model",
                   "x-app-version", "x-device-locale")
DROP_RESPONSE = {"set-cookie", "server", "transfer-encoding", "connection", "content-length", "content-encoding",
                 "x-powered-by", "date", "keep-alive", "alt-svc", "cf-ray", "cf-cache-status", "nel", "report-to"}
PANEL_DEVICE_LIMIT = ("x-hwid-limit", "x-hwid-max-devices-reached", "x-hwid-not-supported")
UA_FIELDS = ("x-hwid", "x-device-os", "x-ver-os", "x-device-model")
# Known VPN clients: User-Agent token → display name.
APPS = (("happ", "Happ"), ("v2raytun", "v2RayTun"), ("v2rayng", "v2rayNG"), ("hiddify", "Hiddify"), ("streisand", "Streisand"),
        ("shadowrocket", "Shadowrocket"), ("clash-verge", "Clash Verge"), ("clashmeta", "Clash Meta"), ("flclash", "FlClash"),
        ("clash", "Clash"), ("nekobox", "NekoBox"), ("karing", "Karing"), ("sing-box", "sing-box"), ("sfa", "sing-box"),
        ("sfi", "sing-box"), ("incy", "INCY"), ("koala", "Koala Clash"), ("throne", "Throne"), ("corgilusi", "Корги Люси"),
        ("v2box", "V2Box"), ("foxray", "FoXray"), ("loon", "Loon"), ("quantumult", "Quantumult X"), ("stash", "Stash"),
        ("mozilla", "Браузер"))

_state: dict = {"cfg": dict(DEFAULT), "at": 0.0}
_index: dict[str, tuple[float, dict | None]] = {}


# ---------------------------------------------------------------- configuration


async def load_config(db: AsyncSession) -> dict:
    from .node_health import _load
    cfg = await _load(db, CONFIG_KEY, DEFAULT)
    _state.update(cfg=cfg, at=time.monotonic())
    return cfg


async def config(db: AsyncSession) -> dict:
    if time.monotonic() - _state["at"] > 30:
        return await load_config(db)
    return _state["cfg"]


def short_uuid_of(url: str | None) -> str:
    """The panel subscription link ends with the user's shortUuid (``https://sub.panel/<shortUuid>``)."""
    tail = (url or "").strip().rstrip("/").rsplit("/", 1)[-1].split("?", 1)[0]
    return tail if TOKEN.match(tail) else ""


def proxy_url(short: str, cfg: dict | None = None) -> str:
    cfg = cfg or _state["cfg"]
    base = str(cfg.get("public_base") or "").rstrip("/")
    prefix = str(cfg.get("prefix") or "").strip("/")
    return f"{base}/{prefix + '/' if prefix else ''}{short}" if base and short else ""


def client_url(url: str | None) -> str | None:
    """The link a customer sees: the proxy link when the proxy is on and set to rewrite links, else the panel's."""
    cfg = _state["cfg"]
    if not url or not cfg.get("enabled") or not cfg.get("rewrite_links") or not cfg.get("public_base"):
        return url
    short = short_uuid_of(url)
    return proxy_url(short, cfg) or url if short and not url.startswith("sandbox://") else url


# ---------------------------------------------------------------- request parsing


def ua_fields(ua: str) -> dict[str, str]:
    """``x-hwid=…`` style pairs inside a User-Agent (v2rayNG, Clash and others can change only the User-Agent)."""
    out = {}
    for key in UA_FIELDS:
        m = re.search(rf"(?:^|[\s;(,]){re.escape(key)}[=:]([^\s;),]+)", ua, re.I)
        if m:
            out[key] = m.group(1)[:128]
    return out


def client_app(ua: str) -> tuple[str, str]:
    """(app, version) from the User-Agent: «v2rayNG/1.9.30» → ("v2rayNG", "1.9.30")."""
    low = ua.lower()
    for token, name in APPS:
        i = low.find(token)
        if i < 0:
            continue
        m = re.match(r"[a-z0-9._-]*[/ ]v?(\d+(?:\.\d+){0,3})", low[i:])
        return name, (m.group(1) if m else "")
    first = re.match(r"([A-Za-z][\w.-]{1,30})/v?(\d+(?:\.\d+){0,3})", ua)
    return (first.group(1), first.group(2)) if first else ("", "")


def client_os(ua: str, header: str) -> str:
    if header:
        return header[:40]
    low = ua.lower()
    for token, name in (("android", "Android"), ("iphone", "iOS"), ("ios", "iOS"), ("ipad", "iPadOS"), ("mac", "macOS"),
                        ("windows", "Windows"), ("linux", "Linux")):
        if token in low:
            return name
    return ""


def matching_rule(cfg: dict, ua: str, os_name: str) -> dict | None:
    for rule in cfg.get("rules") or []:
        try:
            if rule.get("ua") and not re.search(rule["ua"], ua, re.I):
                continue
        except re.error:
            continue
        if rule.get("os") and rule["os"].lower() != os_name.lower():
            continue
        return rule
    return None


# ---------------------------------------------------------------- body helpers


def uri_list(body: bytes) -> tuple[str, list[str]] | None:
    """("base64" | "plain", lines) for a subscription that is a list of URIs; None for JSON, YAML and the rest."""
    text = body.decode("utf-8", "replace").strip()
    if not text or text[:1] in "{[" or "proxies:" in text[:2000]:
        return None
    if "://" in text.split("\n", 1)[0]:
        return "plain", [x for x in text.splitlines() if x.strip()]
    try:
        decoded = base64.b64decode(text + "=" * (-len(text) % 4), validate=False).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    lines = [x for x in decoded.splitlines() if x.strip()]
    return ("base64", lines) if lines and all("://" in x for x in lines[:5]) else None


def encode_list(kind: str, lines: list[str]) -> bytes:
    text = "\n".join(lines) + "\n"
    return base64.b64encode(text.encode()) if kind == "base64" else text.encode()


def header_value(value: str) -> str:
    """HTTP headers are Latin-1: text in other scripts goes as ``base64:…``, the form VPN clients decode."""
    try:
        value.encode("latin-1")
        return value
    except UnicodeEncodeError:
        return "base64:" + base64.b64encode(value.encode()).decode()


def stub_body(text: str, kind: str = "base64") -> bytes:
    """One placeholder server whose name carries the owner's message; it never connects anywhere."""
    from urllib.parse import quote
    link = f"vless://00000000-0000-0000-0000-000000000000@0.0.0.0:1?type=tcp&security=none#{quote(text[:120])}"
    return encode_list(kind, [link])


async def merged_lines(cfg: dict, short: str, client: httpx.AsyncClient, ua: str) -> list[str]:
    template = str(cfg.get("merge_url") or "").strip()
    if not template:
        return []
    try:
        r = await client.get(template.replace("{short_uuid}", short), headers={"User-Agent": ua or "v2rayNG/1.9"})
        parsed = uri_list(r.content) if r.status_code == 200 else None
        return parsed[1] if parsed else []
    except httpx.HTTPError as exc:
        logger.info("Second subscription is unavailable: %s", exc)
        return []


# ---------------------------------------------------------------- lookup and logging


async def lookup(db: AsyncSession, short: str) -> dict | None:
    """The shop's subscription for a shortUuid (cached 5 minutes): ids, squad and whether it is active now."""
    hit = _index.get(short)
    if hit and time.monotonic() - hit[0] < 300:
        return hit[1]
    from .models import Subscription
    sub = (await db.execute(select(Subscription).where(Subscription.subscription_url.like(f"%/{short}"))
                            .order_by(Subscription.id.desc()).limit(1))).scalar_one_or_none()
    info = None if not sub else {
        "subscription_id": sub.id, "user_id": sub.user_id, "panel_user": sub.remnawave_uuid or "",
        "squad": sub.remnawave_profile_id_snapshot or "",
        "active": bool(sub.expires_at and sub.expires_at > datetime.utcnow() and sub.lifecycle_status in {"active", "grace"}),
    }
    if len(_index) > 20000:
        _index.clear()
    _index[short] = (time.monotonic(), info)
    return info


def forget(short: str) -> None:
    _index.pop(short, None)


async def _log(db: AsyncSession, **row) -> None:
    from .models import SubRequest
    try:
        db.add(SubRequest(**row))
        await db.commit()
    except Exception as exc:  # noqa: BLE001 — the log never breaks a subscription answer
        logger.warning("Subscription request log failed: %s", exc)
        await db.rollback()


def _client_ip(request: Request) -> str:
    from .main import _client_ip as ip
    return ip(request)[:64]


# ---------------------------------------------------------------- the proxy


def mask_page(cfg: dict) -> HTMLResponse:
    title = (cfg.get("mask_title") or "Вход")[:60]
    html = ("<!doctype html><html lang=ru><head><meta charset=utf-8><meta name=viewport content='width=device-width'>"
            f"<meta name=robots content=noindex><title>{title}</title><style>body{{font:16px system-ui;background:#f4f4f5;"
            "display:grid;place-items:center;height:100vh;margin:0}}form{{background:#fff;padding:32px;border-radius:12px;"
            "box-shadow:0 2px 12px #0001;display:grid;gap:12px;width:280px}}input,button{{padding:10px;border-radius:8px;"
            "border:1px solid #ddd;font:inherit}}button{{background:#18181b;color:#fff}}</style></head><body>"
            f"<form onsubmit='return false'><b>{title}</b><input placeholder='Логин' autocomplete=off>"
            "<input type=password placeholder='Пароль'><button>Войти</button></form></body></html>")
    return HTMLResponse(html, status_code=200, headers={"X-Frame-Options": "DENY", "Cache-Control": "no-store"})


def _origin(cfg: dict) -> tuple[str, dict]:
    origin = str(cfg.get("origin") or "").rstrip("/") or settings.remnawave_url.rstrip("/") + "/api/sub"
    headers = {"X-Forwarded-Proto": "https", "X-Forwarded-For": "127.0.0.1"} if origin.startswith("http://") else {}
    return origin, headers


async def serve(request: Request, path: str, db: AsyncSession) -> Response:
    cfg = await config(db)
    if not cfg.get("enabled"):
        raise HTTPException(404)
    parts = [p for p in path.split("/") if p]
    prefix = str(cfg.get("prefix") or "").strip("/")
    if prefix and parts and parts[0] == prefix:
        parts = parts[1:]
    if not parts or not TOKEN.match(parts[0]):
        if cfg.get("mask"):
            return mask_page(cfg)
        raise HTTPException(404)
    short, suffix = parts[0], "/".join(parts[1:])
    started = time.monotonic()
    ua = request.headers.get("user-agent", "")[:255]
    fields = ua_fields(ua) if cfg.get("ua_hwid") else {}
    hwid = (request.headers.get("x-hwid") or fields.get("x-hwid") or "")[:128]
    os_name = client_os(ua, request.headers.get("x-device-os") or fields.get("x-device-os") or "")
    model = (request.headers.get("x-device-model") or fields.get("x-device-model") or "")[:80]
    app, version = client_app(ua)
    from .client_versions import is_outdated
    outdated = await is_outdated(db, app, version)
    info = await lookup(db, short)
    base = {"short_uuid": short, "user_id": info["user_id"] if info else None, "app": app[:40], "app_version": version[:40],
            "os": os_name, "model": model, "hwid": hwid, "ip": _client_ip(request), "user_agent": ua, "outdated": outdated}
    blocked = {str(x.get("hwid")) for x in cfg.get("blocked_hwids") or [] if isinstance(x, dict)}
    if hwid and hwid in blocked:
        body = stub_body(cfg.get("block_text") or DEFAULT["block_text"])
        await _log(db, decision="blocked", status=200, bytes=len(body), ms=int((time.monotonic() - started) * 1000), **base)
        return Response(body, media_type="text/plain; charset=utf-8",
                        headers={"announce": "base64:" + base64.b64encode((cfg.get("block_text") or "").encode()).decode(),
                                 "profile-update-interval": "1", "Cache-Control": "no-store"})
    origin, extra_headers = _origin(cfg)
    forward = {k: v for k, v in request.headers.items() if k.lower() in FORWARD_REQUEST}
    if hwid and "x-hwid" not in {k.lower() for k in forward}:
        forward["x-hwid"] = hwid  # the panel's own device limit sees the HWID from the User-Agent too
    for key in ("x-device-os", "x-device-model", "x-ver-os"):
        if key in fields and key not in {k.lower() for k in forward}:
            forward[key] = fields[key]
    from .panel_api_stats import record
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=6.0), follow_redirects=False, trust_env=False) as client:
            t0 = time.monotonic()
            upstream = await client.get(f"{origin}/{short}" + (f"/{suffix}" if suffix else ""), headers={**forward, **extra_headers},
                                        params=dict(request.query_params))
            record("subscription", "GET", "/api/sub/{x}", upstream.status_code, (time.monotonic() - t0) * 1000)
            body = upstream.content
            headers = {k: v for k, v in upstream.headers.items() if k.lower() not in DROP_RESPONSE}
            decision = "proxied" if upstream.status_code < 400 else ("not_found" if upstream.status_code == 404 else "error")
            limited = any(k in {h.lower() for h in headers} for k in PANEL_DEVICE_LIMIT)
            if upstream.status_code == 200 and info and info["active"] and not limited:
                parsed = uri_list(body)
                if parsed:
                    kind, lines = parsed
                    added = [link for extra in cfg.get("extras") or [] if isinstance(extra, dict)
                             and (not extra.get("squad") or extra.get("squad") == info.get("squad"))
                             for link in extra.get("links") or [] if "://" in str(link)]
                    added += await merged_lines(cfg, short, client, ua)
                    if added:
                        body = encode_list(kind, lines + [x for x in added if x not in lines])
                        decision = "extended"
    except httpx.HTTPError as exc:
        record("subscription", "GET", "/api/sub/{x}", 599, (time.monotonic() - started) * 1000)
        await _log(db, decision="error", status=502, bytes=0, ms=int((time.monotonic() - started) * 1000), **base)
        logger.warning("Subscription origin is unavailable: %s", exc)
        raise HTTPException(502, "Subscription origin is unavailable") from exc
    if upstream.status_code == 404 and cfg.get("mask"):
        await _log(db, decision="not_found", status=404, bytes=0, ms=int((time.monotonic() - started) * 1000), **base)
        return mask_page(cfg)
    public = proxy_url(short, cfg)
    if public:
        # The panel points «open the subscription page» at its own domain; customers get the mirror instead.
        headers = {k: (public if k.lower() == "profile-web-page-url" else v) for k, v in headers.items()}
    rule = matching_rule(cfg, ua, os_name)
    if rule:
        for key, value in (rule.get("headers") or {}).items():
            key = str(key).strip().lower()
            if not re.fullmatch(r"[a-z0-9-]{2,40}", key) or "\n" in str(value) or "\r" in str(value):
                continue
            if value == "":
                headers = {k: v for k, v in headers.items() if k.lower() != key}
            else:
                headers = {k: v for k, v in headers.items() if k.lower() != key}
                headers[key] = header_value(str(value)[:500])
    await _log(db, decision=decision, status=upstream.status_code, bytes=len(body), ms=int((time.monotonic() - started) * 1000), **base)
    return Response(body, status_code=upstream.status_code, headers=headers)


@router.get("/sub/{path:path}", include_in_schema=False)
async def subscription(path: str, request: Request, db: AsyncSession = Depends(get_db)):
    return await serve(request, path, db)


@router.get("/sub", include_in_schema=False)
async def subscription_root(request: Request, db: AsyncSession = Depends(get_db)):
    return await serve(request, "", db)


# ---------------------------------------------------------------- admin


class RuleIn(BaseModel):
    name: str = Field("", max_length=60)
    ua: str = Field("", max_length=200)
    os: str = Field("", max_length=20)
    headers: dict[str, str] = Field(default_factory=dict)


class ExtraIn(BaseModel):
    name: str = Field("", max_length=60)
    squad: str = Field("", max_length=64)
    links: list[str] = Field(default_factory=list, max_length=50)


class ProxyIn(BaseModel):
    enabled: bool = False
    public_base: str = Field("", max_length=200, pattern=r"^$|^https://[A-Za-z0-9.-]+(:\d+)?(/[A-Za-z0-9._~-]*)*$")
    origin: str = Field("", max_length=200, pattern=r"^$|^https?://[A-Za-z0-9.-]+(:\d+)?(/[A-Za-z0-9._~-]*)*$")
    prefix: str = Field("", max_length=40, pattern=r"^[A-Za-z0-9_-]*$")
    rewrite_links: bool = True
    mask: bool = True
    mask_title: str = Field("Вход", max_length=60)
    ua_hwid: bool = True
    block_text: str = Field(DEFAULT["block_text"], max_length=120)
    rules: list[RuleIn] = Field(default_factory=list, max_length=50)
    extras: list[ExtraIn] = Field(default_factory=list, max_length=30)
    merge_url: str = Field("", max_length=300, pattern=r"^$|^https://\S+$")
    log_days: int = Field(14, ge=1, le=90)


class BlockIn(BaseModel):
    hwid: str = Field(..., min_length=1, max_length=128)
    note: str = Field("", max_length=120)


@router.get("/api/admin/sub-proxy")
async def get_proxy(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("ops.diagnostics"))):
    cfg = await load_config(db)
    since = datetime.utcnow() - timedelta(days=1)
    from .models import SubRequest
    rows = (await db.execute(select(SubRequest.decision, func.count()).where(SubRequest.created_at >= since)
                             .group_by(SubRequest.decision))).all()
    origin, _ = _origin(cfg)
    return {"config": cfg, "origin_effective": origin, "example": proxy_url("AbCdEfGh12345678", cfg),
            "last_24h": {d: n for d, n in rows}}


@router.put("/api/admin/sub-proxy")
async def put_proxy(payload: ProxyIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("settings.runtime.write"))):
    from .node_health import _save
    cfg = await load_config(db)
    for rule in payload.rules:
        try:
            re.compile(rule.ua)
        except re.error as exc:
            raise HTTPException(422, f"Правило «{rule.name}»: неверное выражение User-Agent") from exc
    for extra in payload.extras:
        if any("://" not in x or len(x) > 2000 or "\n" in x for x in extra.links):
            raise HTTPException(422, f"Доп. ключи «{extra.name}»: каждая строка — одна ссылка вида scheme://…")
    if payload.enabled and payload.rewrite_links and not payload.public_base:
        raise HTTPException(422, "Укажите адрес зеркала, чтобы выдавать клиентам ссылки прослойки")
    new = {**cfg, **payload.model_dump()}
    await _save(db, CONFIG_KEY, new)
    await db.commit()
    _state.update(cfg=new, at=time.monotonic())
    _index.clear()
    return {"ok": True, "config": new}


@router.post("/api/admin/sub-proxy/blocked")
async def block_device(payload: BlockIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("users.write"))):
    from .node_health import _save
    cfg = await load_config(db)
    rows = [x for x in cfg.get("blocked_hwids") or [] if x.get("hwid") != payload.hwid]
    rows.append({"hwid": payload.hwid, "note": payload.note, "at": datetime.utcnow().isoformat(timespec="seconds")})
    cfg["blocked_hwids"] = rows[-2000:]
    await _save(db, CONFIG_KEY, cfg)
    await db.commit()
    _state.update(cfg=cfg, at=time.monotonic())
    return {"ok": True, "blocked": len(cfg["blocked_hwids"])}


@router.delete("/api/admin/sub-proxy/blocked/{hwid}")
async def unblock_device(hwid: str, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("users.write"))):
    from .node_health import _save
    cfg = await load_config(db)
    cfg["blocked_hwids"] = [x for x in cfg.get("blocked_hwids") or [] if x.get("hwid") != hwid]
    await _save(db, CONFIG_KEY, cfg)
    await db.commit()
    _state.update(cfg=cfg, at=time.monotonic())
    return {"ok": True}


@router.get("/api/admin/sub-proxy/log")
async def request_log(short_uuid: str = "", user_id: int | None = None, decision: str = "", outdated: bool = False,
                      limit: int = 100, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("ops.diagnostics"))):
    from .models import SubRequest
    q = select(SubRequest).order_by(SubRequest.id.desc()).limit(min(max(limit, 1), 500))
    if short_uuid:
        q = q.where(SubRequest.short_uuid == short_uuid)
    if user_id:
        q = q.where(SubRequest.user_id == user_id)
    if decision:
        q = q.where(SubRequest.decision == decision)
    if outdated:
        q = q.where(SubRequest.outdated.is_(True))
    rows = (await db.execute(q)).scalars().all()
    return {"rows": [{"id": r.id, "at": r.created_at.isoformat(timespec="seconds"), "short_uuid": r.short_uuid, "user_id": r.user_id,
                      "app": r.app, "version": r.app_version, "os": r.os, "model": r.model, "hwid": r.hwid, "ip": r.ip,
                      "decision": r.decision, "status": r.status, "bytes": r.bytes, "ms": r.ms, "outdated": r.outdated} for r in rows]}


@router.get("/api/admin/sub-proxy/apps")
async def apps_seen(days: int = 7, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("ops.diagnostics"))):
    """Which apps and versions the customers update the subscription with (for the client catalogue)."""
    from .models import SubRequest
    since = datetime.utcnow() - timedelta(days=min(max(days, 1), 90))
    rows = (await db.execute(select(SubRequest.app, SubRequest.app_version, func.count(func.distinct(SubRequest.short_uuid)))
                             .where(SubRequest.created_at >= since, SubRequest.app != "")
                             .group_by(SubRequest.app, SubRequest.app_version))).all()
    return {"apps": sorted(({"app": a, "version": v, "customers": n} for a, v, n in rows), key=lambda x: -x["customers"])}


# ---------------------------------------------------------------- housekeeping


async def cleanup(db: AsyncSession) -> int:
    from .models import SubRequest
    cfg = await load_config(db)
    cutoff = datetime.utcnow() - timedelta(days=int(cfg.get("log_days") or 14))
    result = await db.execute(delete(SubRequest).where(SubRequest.created_at < cutoff))
    await db.commit()
    return int(result.rowcount or 0)


async def _loop() -> None:
    from .db import SessionLocal
    while True:
        try:
            async with SessionLocal() as db:
                await load_config(db)
                await cleanup(db)
                from .webhook_tee import cleanup as journal_cleanup
                await journal_cleanup(db)
        except Exception as exc:  # noqa: BLE001 — the next round tries again
            logger.warning("Subscription proxy housekeeping failed: %s", exc)
        await asyncio.sleep(3600)


async def _start() -> None:
    from . import main
    main._track_task(_loop())


router.add_event_handler("startup", _start)
