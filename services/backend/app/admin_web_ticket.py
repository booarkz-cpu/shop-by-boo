"""Open the full web admin panel from the admin apps without a second sign-in.

The app (signed in with its bearer token) asks for a one-time ticket; the in-app browser opens
https://<admin domain>/?ticket=…, and the panel exchanges the ticket for an ordinary browser session
(cookie + CSRF), bound to the same administrator and MFA state. A ticket lives 60 seconds, works once
and is stored only as a SHA-256 hash in Redis.
"""
from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import current_admin

TTL = 60
router = APIRouter()


class TicketIn(BaseModel):
    ticket: str = Field(min_length=20, max_length=128)


def _key(ticket: str) -> str:
    return "admin-web-ticket:" + hashlib.sha256(ticket.encode()).hexdigest()


@router.post("/api/admin/auth/web-ticket")
async def issue_web_ticket(request: Request, admin=Depends(current_admin)):
    from . import main
    if main.redis_client is None:
        raise HTTPException(503, "Redis is required for panel tickets")
    from .security import decode_token
    raw = (request.headers.get("authorization") or "").removeprefix("Bearer ").strip() or request.cookies.get("rw_admin", "")
    mfa = bool(decode_token(raw).get("mfa")) if raw else False
    ticket = secrets.token_urlsafe(32)
    await main.redis_client.set(_key(ticket), json.dumps({"admin_id": admin.id, "mfa": mfa}), ex=TTL, nx=True)
    domain = main.settings.admin_domain if main.settings.admin_domain and main.settings.admin_domain != "localhost" else ""
    base = f"https://{domain}" if domain else main.settings.public_base_url.rstrip("/")
    return {"url": f"{base}/?ticket={ticket}", "expires_in": TTL}


@router.post("/api/admin/auth/ticket")
async def redeem_web_ticket(payload: TicketIn, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    from . import main
    if main.redis_client is None:
        raise HTTPException(503, "Redis is required for panel tickets")
    raw = await main.redis_client.getdel(_key(payload.ticket))
    if not raw:
        raise HTTPException(401, "Ссылка устарела: откройте панель из приложения ещё раз")
    data = json.loads(raw)
    admin = await db.get(main.AdminUser, int(data["admin_id"]))
    if admin is None or admin.disabled:
        raise HTTPException(401, "Admin account disabled or missing")
    jti = secrets.token_urlsafe(32)
    db.add(main.AdminSession(admin_id=admin.id, jti_hash=hashlib.sha256(jti.encode()).hexdigest(), ip=main._client_ip(request),
                             user_agent=(request.headers.get("user-agent") or "")[:512], expires_at=datetime.utcnow() + timedelta(minutes=30)))
    token = main.issue_token(admin, bool(data.get("mfa")), 30, jti=jti)
    await main.audit(db, "admin.web_ticket.redeemed", admin.email, None, {"ip": main._client_ip(request)})
    await db.commit()
    response.set_cookie("rw_admin", token, httponly=True, secure=main.settings.cookie_secure, samesite=main.settings.cookie_samesite, max_age=1800)
    main._set_auth_cookies(response, token)
    return {"mfa_enabled": bool(admin.mfa_enabled), "role": admin.role, "email": admin.email}
