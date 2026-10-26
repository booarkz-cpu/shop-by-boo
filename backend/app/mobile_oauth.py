"""Sign-in for the Android and iOS customer apps through Telegram, Yandex ID, VK ID and Google
(v28.31.0).

Browser providers (Yandex, VK, Google)
  The app opens ``GET /api/auth/mobile/oauth/{provider}/start?client=…&challenge=…`` in the
  system browser. The provider returns to ``/api/auth/mobile/oauth/{provider}/callback``; the
  shop resolves the account and sends the browser to ``<scheme>://auth?code=…``. The code is
  the same encrypted, PKCE-bound authorization code a password login returns: only the app
  that holds the verifier can exchange it at ``/api/auth/mobile/token``.

Telegram (no browser, no domain setup)
  ``POST /api/auth/mobile/telegram/start`` returns a ``t.me/<bot>?start=login_<nonce>`` link and
  a two-digit code. The bot asks the customer to pick that code among three; a wrong pick or
  «Это не я» cancels the attempt, so a login link sent by someone else cannot sign the victim
  into the sender's phone. The app polls ``…/telegram/poll`` and gets the authorization code
  once. Attempts live five minutes in ``app_settings`` (the bot process has no Redis).
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import time
import urllib.parse
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import get_db
from .models import AppSetting, User

router = APIRouter()
APP_CLIENTS = frozenset({"android-user", "ios-user"})
PROVIDERS = ("yandex", "vk", "google")
CHALLENGE = re.compile(r"^[A-Za-z0-9_-]{43}$")
STATE_TTL = 600
TELEGRAM_TTL = 300
TG_PREFIX = "tg_app_login:"
LOCK_BASE = {"yandex": 1100000000, "vk": 1200000000, "google": 1300000000, "telegram": 1400000000}


# ------------------------------------------------------------------ shared pieces

def provider_ready(provider: str) -> bool:
    if provider == "yandex":
        return bool(settings.yandex_client_id and settings.yandex_client_secret)
    if provider == "vk":
        return bool(settings.vk_client_id and settings.vk_client_secret)
    if provider == "google":
        return bool(settings.google_client_id and settings.google_client_secret)
    if provider == "telegram":
        return bool(settings.bot_token and settings.bot_username)
    return False


def available_providers() -> list[str]:
    """Sign-in methods the apps should show besides email and passkey."""
    return [p for p in ("telegram", *PROVIDERS) if provider_ready(p)]


def callback_url(provider: str) -> str:
    return f"https://{settings.api_domain}/api/auth/mobile/oauth/{provider}/callback"


def app_return(params: dict) -> str:
    return f"{settings.mobile_auth_scheme}://auth?" + urllib.parse.urlencode(params)


def exchange_code(client: str, challenge: str, token: str) -> str:
    """The encrypted one-use code the app trades for its session (see mobile_auth.session_body)."""
    from .security import encrypt_secret
    payload = {"type": "mobile_exchange", "client": client, "challenge": challenge, "token": token,
               "exp": int(time.time()) + 120, "jti": secrets.token_urlsafe(32)}
    return encrypt_secret(json.dumps(payload))


async def _lock(db: AsyncSession, provider: str, external_id: str):
    if db.bind.dialect.name == "postgresql":
        key = LOCK_BASE[provider] + int(hashlib.sha256(external_id.encode()).hexdigest()[:8], 16) % 90000000
        await db.execute(sql_text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


async def resolve_user(db: AsyncSession, provider: str, external_id: str, *, email: str | None = None,
                       username: str | None = None) -> User:
    """The account of a provider identity, created on first sign-in.

    An email from the provider never links to an existing email account automatically: email
    registration does not prove ownership, so linking would hand that account to the provider
    identity's owner (the cabinet keeps the same rule for VK)."""
    from .account_merge import email_registered, identity_user
    external_id = str(external_id or "").strip()
    if not external_id or external_id == "None":
        raise HTTPException(401, "Провайдер не вернул идентификатор пользователя")
    await _lock(db, provider, external_id)
    key = "telegram" if provider == "telegram" else provider
    user = await identity_user(db, key, int(external_id) if provider == "telegram" else external_id)
    if user is None:
        if email and await email_registered(db, email):
            raise HTTPException(409, "Эта почта уже зарегистрирована: войдите по почте и привяжите вход в профиле")
        column = {"telegram": "telegram_id", "yandex": "yandex_id", "vk": "vk_id", "google": "google_id"}[provider]
        user = User(**{column: int(external_id) if provider == "telegram" else external_id}, email=email or None,
                    username=(username or f"{provider}_{external_id}")[:255], referral_code=secrets.token_urlsafe(8).upper())
        db.add(user)
        await db.flush()
    if user.deleted_at is not None:
        raise HTTPException(401, "Аккаунт удалён")
    await db.commit()
    await db.refresh(user)
    return user


async def _session(db: AsyncSession, user: User, request: Request, method: str) -> str:
    from .main import _client_ip, audit, create_user_session
    token = await create_user_session(db, user, request)
    await audit(db, "auth.user.login", f"user:{user.id}", None, {"method": f"app:{method}", "ip": _client_ip(request)})
    await db.commit()
    return token


# ------------------------------------------------------------------ browser providers

def _authorize_url(provider: str, state: str) -> str:
    redirect = callback_url(provider)
    if provider == "yandex":
        return "https://oauth.yandex.ru/authorize?" + urllib.parse.urlencode(
            {"response_type": "code", "client_id": settings.yandex_client_id, "redirect_uri": redirect, "state": state, "force_confirm": "yes"})
    if provider == "vk":
        return "https://oauth.vk.com/authorize?" + urllib.parse.urlencode(
            {"response_type": "code", "client_id": settings.vk_client_id, "redirect_uri": redirect, "state": state, "scope": "email", "v": "5.199"})
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(
        {"response_type": "code", "client_id": settings.google_client_id, "redirect_uri": redirect, "state": state,
         "scope": "openid email profile", "prompt": "select_account"})


async def fetch_identity(provider: str, code: str) -> dict:
    """Trade the provider's code for {id, email, username}. Network access goes through the
    shop's pinned public HTTP client (no private addresses, no proxy environment)."""
    from .main import _pinned_public_http_client
    redirect = callback_url(provider)
    async with _pinned_public_http_client(20) as client:
        if provider == "yandex":
            r = await client.post("https://oauth.yandex.ru/token", data={"grant_type": "authorization_code", "code": code,
                                  "client_id": settings.yandex_client_id, "client_secret": settings.yandex_client_secret})
            if r.status_code != 200:
                raise HTTPException(401, "Яндекс не подтвердил вход")
            me = await client.get("https://login.yandex.ru/info", params={"format": "json"}, headers={"Authorization": f"OAuth {r.json().get('access_token')}"})
            if me.status_code != 200:
                raise HTTPException(401, "Не удалось прочитать профиль Яндекса")
            info = me.json()
            return {"id": info.get("id"), "email": None, "username": info.get("login") or info.get("display_name")}
        if provider == "vk":
            r = await client.get("https://oauth.vk.com/access_token", params={"client_id": settings.vk_client_id,
                                 "client_secret": settings.vk_client_secret, "redirect_uri": redirect, "code": code})
            if r.status_code != 200:
                raise HTTPException(401, "VK не подтвердил вход")
            data = r.json()
            return {"id": data.get("user_id"), "email": (data.get("email") or "").strip().lower() or None, "username": None}
        r = await client.post("https://oauth2.googleapis.com/token", data={"grant_type": "authorization_code", "code": code,
                              "client_id": settings.google_client_id, "client_secret": settings.google_client_secret, "redirect_uri": redirect})
        if r.status_code != 200:
            raise HTTPException(401, "Google не подтвердил вход")
        me = await client.get("https://openidconnect.googleapis.com/v1/userinfo", headers={"Authorization": f"Bearer {r.json().get('access_token')}"})
        if me.status_code != 200:
            raise HTTPException(401, "Не удалось прочитать профиль Google")
        info = me.json()
        email = (info.get("email") or "").strip().lower() if info.get("email_verified") else None
        return {"id": info.get("sub"), "email": email or None, "username": info.get("name")}


def _state(provider: str, client: str, challenge: str) -> str:
    import jwt
    return jwt.encode({"typ": "app_oauth", "p": provider, "c": client, "ch": challenge, "n": secrets.token_urlsafe(16),
                       "exp": int(time.time()) + STATE_TTL}, settings.app_secret, algorithm="HS256")


def _read_state(state: str, provider: str) -> dict:
    import jwt
    try:
        data = jwt.decode(state, settings.app_secret, algorithms=["HS256"])
    except Exception:
        raise HTTPException(400, "Ссылка входа устарела")
    if data.get("typ") != "app_oauth" or data.get("p") != provider or data.get("c") not in APP_CLIENTS or not CHALLENGE.match(data.get("ch", "")):
        raise HTTPException(400, "Ссылка входа устарела")
    return data


@router.get("/api/auth/mobile/oauth/{provider}/start")
async def oauth_start(provider: str, client: str, challenge: str):
    if provider not in PROVIDERS:
        raise HTTPException(404, "Неизвестный способ входа")
    if client not in APP_CLIENTS or not CHALLENGE.match(challenge):
        raise HTTPException(400, "Обновите приложение: нужен PKCE-код")
    if not provider_ready(provider):
        raise HTTPException(503, "Этот способ входа не настроен в магазине")
    return RedirectResponse(_authorize_url(provider, _state(provider, client, challenge)), status_code=302)


@router.get("/api/auth/mobile/oauth/{provider}/callback")
async def oauth_callback(provider: str, request: Request, state: str = "", code: str = "", error: str = "",
                         db: AsyncSession = Depends(get_db)):
    if provider not in PROVIDERS:
        raise HTTPException(404, "Неизвестный способ входа")
    data = _read_state(state, provider)
    if error or not code:
        return RedirectResponse(app_return({"error": "cancelled"}), status_code=302)
    from .main import redis_client
    if redis_client is not None:
        # One state, one session: a replayed provider redirect gets nothing.
        if not await redis_client.set("app-oauth-state:" + hashlib.sha256(state.encode()).hexdigest(), "1", ex=STATE_TTL, nx=True):
            return RedirectResponse(app_return({"error": "used"}), status_code=302)
    try:
        identity = await fetch_identity(provider, code)
        user = await resolve_user(db, provider, identity["id"], email=identity.get("email"), username=identity.get("username"))
        token = await _session(db, user, request, provider)
    except HTTPException as exc:
        await db.rollback()
        return RedirectResponse(app_return({"error": "denied", "message": str(exc.detail)[:200]}), status_code=302)
    return RedirectResponse(app_return({"code": exchange_code(data["c"], data["ch"], token), "provider": provider}), status_code=302)


@router.get("/api/auth/mobile/providers")
async def providers():
    return {"providers": available_providers(), "scheme": settings.mobile_auth_scheme, "bot": settings.bot_username or ""}


# ------------------------------------------------------------------ Telegram through the bot

def _codes() -> tuple[str, list[str]]:
    picks = secrets.SystemRandom().sample(range(10, 100), 3)
    code = str(picks[0])
    choices = [str(x) for x in picks]
    secrets.SystemRandom().shuffle(choices)
    return code, choices


async def _attempt(db: AsyncSession, nonce: str, lock: bool = False) -> tuple[AppSetting | None, dict | None]:
    if not re.fullmatch(r"[A-Za-z0-9_-]{32}", nonce or ""):
        return None, None
    query = select(AppSetting).where(AppSetting.key == TG_PREFIX + nonce)
    if lock:
        query = query.with_for_update()
    row = (await db.execute(query)).scalar_one_or_none()
    if not row:
        return None, None
    data = json.loads(row.value)
    if data["exp"] < time.time():
        await db.delete(row)
        await db.commit()
        return None, None
    return row, data


class TelegramStartIn(BaseModel):
    platform: str = Field(default="", max_length=20)


@router.post("/api/auth/mobile/telegram/start")
async def telegram_start(payload: TelegramStartIn, request: Request, db: AsyncSession = Depends(get_db)):
    from .mobile_auth import mobile_client_name, require_native_transport, require_pkce_challenge
    require_native_transport(request)
    client = mobile_client_name(request)
    if client not in APP_CLIENTS:
        raise HTTPException(400, "Вход через Telegram доступен в приложении для клиентов")
    challenge = require_pkce_challenge(request)
    if not provider_ready("telegram"):
        raise HTTPException(503, "Telegram-бот магазина не настроен")
    # Expired attempts are removed on the way.
    for old in (await db.execute(select(AppSetting).where(AppSetting.key.like(TG_PREFIX + "%")))).scalars():
        if json.loads(old.value).get("exp", 0) < time.time():
            await db.delete(old)
    nonce = secrets.token_urlsafe(24)
    code, choices = _codes()
    platform = "iOS" if client.startswith("ios") else "Android"
    db.add(AppSetting(key=TG_PREFIX + nonce, value=json.dumps({"client": client, "challenge": challenge, "code": code, "choices": choices,
                                                                  "platform": platform, "status": "pending", "exp": int(time.time()) + TELEGRAM_TTL})))
    await db.commit()
    return {"nonce": nonce, "code": code, "expires_in": TELEGRAM_TTL,
            "url": f"https://t.me/{settings.bot_username}?start=login_{nonce}", "app_url": f"tg://resolve?domain={settings.bot_username}&start=login_{nonce}"}


class TelegramPollIn(BaseModel):
    nonce: str = Field(min_length=32, max_length=32)


@router.post("/api/auth/mobile/telegram/poll")
async def telegram_poll(payload: TelegramPollIn, request: Request, db: AsyncSession = Depends(get_db)):
    from .mobile_auth import mobile_client_name, require_native_transport
    require_native_transport(request)
    row, data = await _attempt(db, payload.nonce, lock=True)
    if not data:
        return {"status": "expired"}
    if data["client"] != mobile_client_name(request):
        raise HTTPException(403, "Попытка входа начата в другом приложении")
    if data["status"] != "approved":
        return {"status": data["status"]}
    # Approved: the attempt is consumed here, a second poll gets «expired».
    user = await db.get(User, int(data["user_id"]))
    await db.delete(row)
    await db.commit()
    if not user:
        return {"status": "expired"}
    token = await _session(db, user, request, "telegram")
    return {"status": "approved", "authorization_code": exchange_code(data["client"], data["challenge"], token), "expires_in": 120}


# Called by the bot (backend/app/bot.py), which shares the database but not Redis.

async def telegram_prompt(db: AsyncSession, nonce: str) -> dict | None:
    _, data = await _attempt(db, nonce)
    if not data or data["status"] != "pending":
        return None
    return {"choices": data["choices"], "platform": data["platform"], "expires_in": int(data["exp"] - time.time())}


async def telegram_answer(db: AsyncSession, nonce: str, choice: str, telegram_id: int, username: str | None) -> str:
    """approved | denied | expired. One answer per attempt: a wrong code cancels it."""
    row, data = await _attempt(db, nonce, lock=True)
    if not data or data["status"] != "pending":
        return "expired"
    if choice != data["code"]:
        data["status"] = "denied"
        row.value = json.dumps(data)
        await db.commit()
        return "denied"
    user = await resolve_user(db, "telegram", str(int(telegram_id)), username=username)
    row, data = await _attempt(db, nonce, lock=True)  # resolve_user committed; re-read under lock
    if not data or data["status"] != "pending":
        return "expired"
    data.update(status="approved", user_id=user.id)
    row.value = json.dumps(data)
    from .main import audit
    await audit(db, "auth.app.telegram_approved", f"user:{user.id}", None, {"platform": data["platform"]})
    await db.commit()
    return "approved"
