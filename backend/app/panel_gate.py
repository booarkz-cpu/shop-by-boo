"""The shop's own login in front of a Remnawave panel the wizard installed (v28.78.0, «Доступ к панели → Вход через
магазин»). It replaces the TinyAuth container with the shop's administrators, their two-factor and roles.

How it works:

* Caddy on the panel's server asks the shop about every page of the panel (``forward_auth`` →
  ``GET /api/panel-gate/verify``). The same requests stay open as with the other closed modes: the shop's bearer
  API calls to ``/api/`` and subscriptions ``/api/sub/``.
* An administrator with ``provision_nodes`` presses «Открыть панель» in the wizard: the shop makes a one-time ticket
  (60 seconds, stored only as a SHA-256 in Redis) and opens ``https://<panel>/__corgi_gate?t=…``.
* The panel's Caddy hands that request to ``GET /api/panel-gate/redeem``; the shop answers with a cookie of the
  panel's own domain — a signed token bound to the administrator, the installation and the domain, 12 hours, backed
  by an ``admin_sessions`` row. So no common parent domain is needed, and «revoke all sessions», a disabled account
  or a role without ``provision_nodes`` close the panel at once.
* Every login is written to the audit log. A browser without a valid cookie is sent to the shop's admin panel
  («Установка Remnawave»); other clients get 401.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import time
from datetime import datetime, timedelta

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import get_db
from .models import AdminSession, AdminUser, RemnawaveInstallation
from .security import PERMISSIONS, require_permission

router = APIRouter()
COOKIE = "corgi_gate"
GATE_PATH = "/__corgi_gate"
TICKET_TTL = 60
SESSION_HOURS = 12
PERMISSION = "provision_nodes"
BROWSER = ("Mozilla", "Chrome", "Gecko", "AppleWebKit", "Opera", "Edge")
_cache: dict[str, float] = {}  # token hash → time it may be trusted until (a page loads dozens of assets)
CACHE_SECONDS = 20


def shop_base() -> str:
    """The shop's public API address, the one Caddy on the panel's server calls."""
    domain = settings.api_domain
    if domain and domain != "localhost":
        return f"https://{domain}"
    return settings.public_base_url.rstrip("/")


def admin_url() -> str:
    domain = settings.admin_domain
    base = f"https://{domain}" if domain and domain != "localhost" else settings.public_base_url.rstrip("/")
    return f"{base}/#rwInstaller"


def _ticket_key(ticket: str) -> str:
    return "panel-gate-ticket:" + hashlib.sha256(ticket.encode()).hexdigest()


def _redis():
    from . import main
    if main.redis_client is None:
        raise HTTPException(503, "Для входа в панель нужен Redis")
    return main.redis_client


async def _audit(db, action, actor, target, details):
    from .main import audit
    await audit(db, action, actor, target, details)


async def open_ticket(db: AsyncSession, installation_id: int, admin) -> dict:
    row = await db.get(RemnawaveInstallation, installation_id)
    params = (row.params or {}) if row else {}
    if not row or row.action != "install" or row.status != "succeeded" or params.get("panel_access") != "gate":
        raise HTTPException(409, "Вход через магазин включён не для этой установки")
    ticket = secrets.token_urlsafe(32)
    data = {"admin_id": admin.id, "installation_id": row.id, "domain": params["panel_domain"]}
    await _redis().set(_ticket_key(ticket), json.dumps(data), ex=TICKET_TTL, nx=True)
    await _audit(db, "rw.panel_gate.ticket", admin.email, str(row.id), {"domain": params["panel_domain"]})
    await db.commit()
    return {"url": f"https://{params['panel_domain']}{GATE_PATH}?t={ticket}", "expires_in": TICKET_TTL}


@router.post("/api/admin/rw/installations/{installation_id}/panel-gate")
async def open_panel(installation_id: int, db: AsyncSession = Depends(get_db), admin=Depends(require_permission(PERMISSION))):
    """«Открыть панель»: a one-time link that signs this administrator in to the panel's pages."""
    return await open_ticket(db, installation_id, admin)


HOST_HEADER = "X-Corgi-Gate-Host"


def _forwarded_host(request: Request) -> str:
    """The panel's domain as the panel's Caddy saw it. Its own header: the shop's Caddy replaces X-Forwarded-Host of
    requests that do not come from a trusted proxy. A forged value gains nothing — the cookie is bound to the domain."""
    value = request.headers.get(HOST_HEADER.lower()) or request.headers.get("x-forwarded-host") or ""
    return value.split(",")[0].strip().lower().split(":")[0]


@router.get("/api/panel-gate/redeem")
async def redeem(t: str, request: Request, db: AsyncSession = Depends(get_db)):
    if not 20 <= len(t) <= 128:
        raise HTTPException(400, "Неверная ссылка")
    raw = await _redis().getdel(_ticket_key(t))
    if not raw:
        raise HTTPException(401, "Ссылка устарела: откройте панель из магазина ещё раз")
    data = json.loads(raw)
    if _forwarded_host(request) != data["domain"]:
        raise HTTPException(400, "Ссылка открыта не на домене панели")
    admin = await db.get(AdminUser, int(data["admin_id"]))
    if not admin or admin.disabled or PERMISSION not in PERMISSIONS.get(admin.role, set()):
        raise HTTPException(403, "Нет права входа в панель")
    jti = secrets.token_urlsafe(32)
    expires = datetime.utcnow() + timedelta(hours=SESSION_HOURS)
    from .main import _client_ip
    db.add(AdminSession(admin_id=admin.id, jti_hash=hashlib.sha256(jti.encode()).hexdigest(), ip=_client_ip(request),
                        user_agent=("panel-gate " + (request.headers.get("user-agent") or ""))[:512], expires_at=expires))
    token = jwt.encode({"type": "panel_gate", "sub": str(admin.id), "inst": int(data["installation_id"]), "aud": data["domain"],
                        "jti": jti, "exp": int(time.time()) + SESSION_HOURS * 3600}, settings.app_secret, algorithm="HS256")
    await _audit(db, "rw.panel_gate.login", admin.email, str(data["installation_id"]), {"domain": data["domain"], "ip": _client_ip(request)})
    await db.commit()
    response = RedirectResponse("/", status_code=302)
    response.set_cookie(COOKIE, token, max_age=SESSION_HOURS * 3600, path="/", secure=True, httponly=True, samesite="lax")
    response.headers["Cache-Control"] = "no-store"
    return response


async def check(db: AsyncSession, token: str, domain: str) -> bool:
    try:
        claims = jwt.decode(token, settings.app_secret, algorithms=["HS256"], audience=domain)
    except jwt.PyJWTError:
        return False
    if claims.get("type") != "panel_gate":
        return False
    key = hashlib.sha256(token.encode()).hexdigest()
    if _cache.get(key, 0) > time.monotonic():
        return True
    admin = await db.get(AdminUser, int(claims["sub"]))
    if not admin or admin.disabled or PERMISSION not in PERMISSIONS.get(admin.role, set()):
        return False
    session = (await db.execute(select(AdminSession).where(AdminSession.jti_hash == hashlib.sha256(claims["jti"].encode()).hexdigest(),
                                                           AdminSession.revoked_at.is_(None)))).scalar_one_or_none()
    if not session or session.admin_id != admin.id or session.expires_at < datetime.utcnow():
        return False
    row = await db.get(RemnawaveInstallation, int(claims["inst"]))
    if not row or (row.params or {}).get("panel_domain") != domain:
        return False
    if len(_cache) > 5000:
        _cache.clear()
    _cache[key] = time.monotonic() + CACHE_SECONDS
    return True


@router.get("/api/panel-gate/verify")
async def verify(request: Request, db: AsyncSession = Depends(get_db)):
    """Caddy's ``forward_auth``: 200 lets the request through to the panel, anything else goes back to the browser."""
    domain = _forwarded_host(request)
    token = request.cookies.get(COOKIE, "")
    if domain and token and await check(db, token, domain):
        return Response(status_code=200)
    agent = request.headers.get("user-agent") or ""
    if any(x in agent for x in BROWSER):
        return RedirectResponse(admin_url(), status_code=302, headers={"Cache-Control": "no-store"})
    return Response(status_code=401, content=b'{"detail":"Panel login required"}', media_type="application/json")
