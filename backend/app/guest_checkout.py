"""Guest purchase: buy on the website with just an e-mail — no Telegram, no password first.

``POST /api/auth/guest`` with an e-mail (and the offer consent) creates the account and signs the browser in; the
customer goes straight to the usual checkout (the same gateways, receipts and delivery). A letter («Шаблоны писем →
Покупка по email») brings a link to set a password, so the customer can come back from any device; the cabinet's
password page sends it to ``POST /api/auth/guest/setup``. An e-mail that already has an account must sign in (no
takeover of existing accounts). Moderation rules apply (black list, disposable mail, invites). Off by default:
«Настройки → Покупка без Telegram».
"""
from __future__ import annotations

import hashlib
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import require_permission

router = APIRouter()
KEY = "guest.checkout"


class GuestIn(BaseModel):
    email: str = Field(min_length=5, max_length=320)
    consent: bool = False
    invite: str | None = Field(None, max_length=40)


class SetupIn(BaseModel):
    token: str = Field(min_length=40, max_length=128)
    password: str = Field(min_length=8, max_length=128)


async def enabled(db: AsyncSession) -> bool:
    from .backups_api import setting_value
    return await setting_value(db, KEY, "0") == "1"


@router.post("/api/auth/guest")
async def guest_start(payload: GuestIn, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    from .account_actions import enqueue
    from .account_merge import email_registered
    from .cabinet_api import _client_ip, _normalize_email
    from .main import _set_auth_cookies, audit, create_user_session
    from .models import User
    from .moderation import registration_check
    from .config import settings
    if not await enabled(db):
        raise HTTPException(404, "Покупка без регистрации выключена")
    if not payload.consent:
        raise HTTPException(400, "Примите условия публичной оферты")
    email = _normalize_email(payload.email)
    if db.bind.dialect.name == "postgresql":
        key = int.from_bytes(hashlib.sha256(("register:" + email).encode()).digest()[:8], "big", signed=True)
        await db.execute(sql_text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
    if await email_registered(db, email):
        raise HTTPException(409, "Этот email уже зарегистрирован — войдите в кабинет")
    await registration_check(db, email=email, invite=payload.invite)
    user = User(email=email, username=email.split("@")[0][:255], referral_code=secrets.token_urlsafe(8).upper())
    db.add(user)
    await db.flush()
    from .app_config import load_overrides
    from .models import UserConsent
    consent = (await load_overrides(db)).consent
    if consent.enabled:
        db.add(UserConsent(user_id=user.id, document="offer", version=consent.version, source="cabinet"))
    token = await create_user_session(db, user, request)
    if settings.smtp_host:
        await enqueue(db, user, "guest_setup")
    from .activity_log import record
    record(db, user.id, "cabinet", "guest.created")
    await audit(db, "auth.user.register", f"user:{user.id}", None, {"method": "guest", "ip": _client_ip(request)})
    await db.commit()
    response.set_cookie("rw_user", token, httponly=True, secure=settings.cookie_secure, samesite=settings.cookie_samesite, max_age=3600)
    _set_auth_cookies(response, token)
    return {"id": user.id, "email": email, "letter": bool(settings.smtp_host)}


@router.post("/api/auth/guest/setup")
async def guest_setup(payload: SetupIn, db: AsyncSession = Depends(get_db)):
    from .account_actions import consume
    from .account_merge import update_account_password
    from .main import audit
    from .security import hash_password
    user, _action = await consume(db, payload.token, "guest_setup")
    if user.email_password_hash:
        raise HTTPException(400, "Пароль уже задан — войдите или восстановите пароль")
    user.email_password_hash = hash_password(payload.password)
    from datetime import datetime
    user.email_verified_at = user.email_verified_at or datetime.utcnow()
    await update_account_password(db, user.id, user.email_password_hash)
    await audit(db, "auth.user.guest_password", f"user:{user.id}")
    await db.commit()
    return {"ok": True, "message": "Пароль задан. Войдите с email и паролем."}


@router.get("/api/public/guest-checkout")
async def public_guest(db: AsyncSession = Depends(get_db)):
    return {"enabled": await enabled(db)}


@router.get("/api/admin/guest-checkout")
async def get_guest(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("read"))):
    from .config import settings
    return {"enabled": await enabled(db), "smtp": bool(settings.smtp_host)}


@router.put("/api/admin/guest-checkout")
async def put_guest(payload: dict, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("settings.runtime.write"))):
    from .backups_api import set_setting
    from .main import audit
    await set_setting(db, KEY, "1" if payload.get("enabled") else "0")
    await audit(db, "guest.checkout", admin.email, None, {"enabled": bool(payload.get("enabled"))})
    await db.commit()
    return {"enabled": bool(payload.get("enabled"))}
