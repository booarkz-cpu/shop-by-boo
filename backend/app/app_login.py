"""Sign in to the native apps without typing an address or a password.

Three ways lead into the same one-use code (``AuthExchangeCode``):

* the bot (``/start app_login`` or ``/app``) and the cabinet / Mini App
  (``POST /api/me/app-login``) issue a code for the signed-in user;
* Yandex ID, VK ID and Google started from the app with ``?app=1`` finish
  with a redirect to the app instead of the web cabinet.

The code travels in ``corgi://login?base=<api>&code=<code>``. Telegram and
most mail clients refuse custom schemes in buttons, so links point at the
https page ``/api/app/open`` that forwards to the scheme.

The app redeems the code at ``POST /api/auth/mobile/code`` with the same PKCE
challenge header as password sign-in and receives an ``authorization_code``
for ``/api/auth/mobile/token``. The code is useless to a browser: redemption
is native-only and bound to the verifier the app keeps in memory.
"""
from __future__ import annotations

import hashlib
import html
import re
import secrets
import urllib.parse
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import get_db
from .models import AuthExchangeCode, User

router = APIRouter()

APP_CODE_MINUTES = 5
CODE_RE = re.compile(r"[A-Za-z0-9_-]{20,128}")
ORDER_RE = re.compile(r"[A-Za-z0-9_.:-]{6,128}")

__all__ = [
    "router", "api_base", "app_scheme", "issue_app_code", "deep_link", "open_url",
    "oauth_finish_url", "login_methods", "APP_CODE_MINUTES",
]


def api_base() -> str:
    """Public https address the native apps talk to."""
    domain = (settings.api_domain or "").strip()
    if domain and domain != "localhost":
        return f"https://{domain}"
    return (settings.public_base_url or "").rstrip("/")


def app_scheme() -> str:
    scheme = (getattr(settings, "mobile_app_scheme", "") or "corgi").strip().lower()
    return scheme if re.fullmatch(r"[a-z][a-z0-9+.-]{1,31}", scheme) else "corgi"


async def issue_app_code(db: AsyncSession, user_id: int, minutes: int = APP_CODE_MINUTES) -> str:
    raw = secrets.token_urlsafe(32)
    db.add(AuthExchangeCode(code_hash=hashlib.sha256(raw.encode()).hexdigest(), user_id=user_id,
                            expires_at=datetime.utcnow() + timedelta(minutes=minutes)))
    await db.flush()
    return raw


def deep_link(code: str) -> str:
    query = urllib.parse.urlencode({"base": api_base(), "code": code})
    return f"{app_scheme()}://login?{query}"


def open_url(code: str) -> str:
    return f"{api_base()}/api/app/open?" + urllib.parse.urlencode({"code": code})


def payment_link(order_id: str) -> str:
    """corgi://payment?order=… — the app refreshes and shows the result of this order."""
    return f"{app_scheme()}://payment?" + urllib.parse.urlencode({"base": api_base(), "order": order_id})


def payment_return_url(order_id: str) -> str:
    """https return address for payment pages that refuse custom schemes; it forwards to the app."""
    return f"{api_base()}/api/app/paid?" + urllib.parse.urlencode({"order": order_id})


def oauth_finish_url(code: str, app: bool) -> str:
    """Where an OAuth callback sends the browser once the code exists."""
    if app:
        return deep_link(code)
    dest = (settings.cabinet_url or settings.mini_app_url or "/").rstrip("/")
    return f"{dest}/?code=" + urllib.parse.quote(code)


def login_methods() -> dict:
    bot = (settings.bot_username or "").lstrip("@")
    return {
        "telegram": bool(bot and settings.bot_token),
        "telegram_url": f"https://t.me/{bot}?start=app_login" if bot else "",
        "yandex": bool(settings.yandex_client_id and settings.yandex_redirect_uri),
        "vk": bool(settings.vk_client_id and settings.vk_redirect_uri),
        "google": bool(getattr(settings, "google_client_id", "") and getattr(settings, "google_redirect_uri", "")),
        "scheme": app_scheme(),
    }


@router.get("/api/public/app-login/methods")
async def public_login_methods(response: Response):
    response.headers["Cache-Control"] = "no-cache"
    return login_methods()


@router.post("/api/me/app-login")
async def create_app_login(request: Request, db: AsyncSession = Depends(get_db)):
    """A signed-in cabinet / Mini App user opens the app already signed in."""
    from .main import audit, user_from_token, _client_ip

    user = await user_from_token(request, db)
    code = await issue_app_code(db, user.id)
    await audit(db, "auth.app_login.issued", f"user:{user.id}", None, {"via": "cabinet", "ip": _client_ip(request)})
    await db.commit()
    return {"code": code, "deep_link": deep_link(code), "open_url": open_url(code), "expires_in": APP_CODE_MINUTES * 60}


_OPEN_PAGE = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>Корги Люси</title>
<style>body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#0F1115;color:#F4F5F7;
font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif}}main{{max-width:420px;padding:32px;text-align:center}}
a.btn{{display:block;margin:24px 0 12px;padding:16px;border-radius:16px;background:#FF8A1F;color:#111;
font-weight:700;text-decoration:none}}p{{color:#A9AFBC;line-height:1.5}}</style></head>
<body><main><h1>Открываем приложение…</h1>
<p>Если приложение не открылось само, нажмите кнопку. Ссылка действует {minutes} минут и работает один раз.</p>
<a class="btn" href="{link}">Открыть приложение</a>
<p>Приложение ещё не установлено? Установите его и снова нажмите «Войти в приложение» в боте или кабинете.</p>
</main><script>setTimeout(function(){{location.href={js}}},50)</script></body></html>"""


@router.get("/api/app/open")
async def open_app(code: str = ""):
    """https trampoline for the custom scheme; it never consumes the code."""
    if not CODE_RE.fullmatch(code or ""):
        raise HTTPException(400, "Invalid sign-in link")
    link = deep_link(code)
    import json

    body = _OPEN_PAGE.format(minutes=APP_CODE_MINUTES, link=html.escape(link, quote=True), js=json.dumps(link))
    return HTMLResponse(body, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
                                       "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'"})


_PAID_PAGE = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>Корги Люси</title>
<style>body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#0F1115;color:#F4F5F7;
font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif}}main{{max-width:420px;padding:32px;text-align:center}}
a.btn{{display:block;margin:24px 0 12px;padding:16px;border-radius:16px;background:#FF8A1F;color:#111;
font-weight:700;text-decoration:none}}p{{color:#A9AFBC;line-height:1.5}}</style></head>
<body><main><h1>Возвращаемся в приложение…</h1>
<p>Приложение покажет, прошла ли оплата. Если оно не открылось само, нажмите кнопку.</p>
<a class="btn" href="{link}">Открыть приложение</a>
</main><script>setTimeout(function(){{location.href={js}}},50)</script></body></html>"""


@router.get("/api/app/paid")
async def paid_return(order: str = ""):
    """Return address of payments made in the app: back to the app with the order to check.
    The order id is not a secret: the app reads its status only with the customer's session."""
    if not ORDER_RE.fullmatch(order or ""):
        raise HTTPException(400, "Invalid order")
    import json

    link = payment_link(order)
    body = _PAID_PAGE.format(link=html.escape(link, quote=True), js=json.dumps(link))
    return HTMLResponse(body, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
                                       "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'"})


class AppCodeIn(BaseModel):
    code: str = Field(min_length=20, max_length=128)


@router.post("/api/auth/mobile/code")
async def redeem_app_code(payload: AppCodeIn, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    """Native-only: one-use sign-in code → PKCE authorization code."""
    from .main import audit, create_user_session, _client_ip
    from .mobile_auth import mobile_client_name, require_mobile_proof, require_pkce_challenge, session_body

    if not mobile_client_name(request):
        raise HTTPException(400, "Sign-in links open in the mobile app")
    require_mobile_proof(request)
    require_pkce_challenge(request)
    digest = hashlib.sha256(payload.code.encode()).hexdigest()
    row = (await db.execute(select(AuthExchangeCode).where(AuthExchangeCode.code_hash == digest).with_for_update())).scalar_one_or_none()
    if not row or row.used_at or row.expires_at < datetime.utcnow():
        raise HTTPException(400, "Invalid or expired sign-in link")
    user = await db.get(User, row.user_id)
    if not user or user.deleted_at is not None:
        raise HTTPException(400, "Invalid or expired sign-in link")
    row.used_at = datetime.utcnow()
    await db.flush()
    token = await create_user_session(db, user, request)
    await audit(db, "auth.user.login", f"user:{user.id}", None, {"method": "app_link", "ip": _client_ip(request)})
    await db.commit()
    response.headers["Cache-Control"] = "no-store"
    return session_body(request, token, {"id": user.id, "username": user.username})


# ---------- Google (OpenID Connect, verified e-mail) ----------
def _google_state(app: bool) -> str:
    import jwt

    return jwt.encode({"typ": "google_oauth", "app": bool(app), "nonce": secrets.token_urlsafe(12),
                       "exp": int((datetime.now(timezone.utc) + timedelta(minutes=10)).timestamp())},
                      settings.app_secret, algorithm="HS256")


@router.get("/api/auth/google")
async def google_login(app: int = 0):
    if not getattr(settings, "google_client_id", "") or not getattr(settings, "google_redirect_uri", ""):
        raise HTTPException(503, "Google sign-in is not configured")
    state = _google_state(bool(app))
    params = urllib.parse.urlencode({"response_type": "code", "client_id": settings.google_client_id,
                                     "redirect_uri": settings.google_redirect_uri, "scope": "openid email profile",
                                     "state": state, "prompt": "select_account"})
    resp = RedirectResponse("https://accounts.google.com/o/oauth2/v2/auth?" + params)
    resp.set_cookie("google_oauth_state", state, httponly=True, secure=settings.cookie_secure, samesite="lax", max_age=600)
    return resp


@router.get("/api/auth/google/callback")
async def google_callback(code: str, state: str, request: Request, db: AsyncSession = Depends(get_db)):
    import hmac
    import jwt
    from .main import _advisory_lock, _pinned_public_http_client, audit, _client_ip

    try:
        if not request.cookies.get("google_oauth_state") or not hmac.compare_digest(request.cookies["google_oauth_state"], state):
            raise ValueError()
        claims = jwt.decode(state, settings.app_secret, algorithms=["HS256"])
        if claims.get("typ") != "google_oauth":
            raise ValueError()
    except Exception:
        raise HTTPException(400, "Invalid OAuth state")
    if not getattr(settings, "google_client_secret", ""):
        raise HTTPException(503, "Google sign-in secret is not configured")
    async with _pinned_public_http_client(20) as client:
        token_r = await client.post("https://oauth2.googleapis.com/token", data={
            "grant_type": "authorization_code", "code": code, "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret, "redirect_uri": settings.google_redirect_uri})
        if token_r.status_code != 200:
            raise HTTPException(401, "Google authorization failed")
        access = token_r.json().get("access_token")
        me_r = await client.get("https://openidconnect.googleapis.com/v1/userinfo", headers={"Authorization": f"Bearer {access}"})
    if me_r.status_code != 200:
        raise HTTPException(401, "Could not read Google profile")
    info = me_r.json()
    email = (info.get("email") or "").strip().lower()
    if not email or info.get("email_verified") is not True:
        raise HTTPException(401, "Google account has no verified e-mail")
    lock = int.from_bytes(hashlib.sha256(("register:" + email).encode()).digest()[:8], "big", signed=True)
    await _advisory_lock(db, lock)
    from .account_merge import email_identity

    user, _hash, verified = await email_identity(db, email)
    if user and not verified:
        # An unverified e-mail registration proves nothing; linking it would hand
        # its password and sessions to whoever owns the Google account, or back.
        raise HTTPException(409, "Email already registered; confirm it in the cabinet first")
    if not user:
        user = User(email=email, email_verified_at=datetime.utcnow(), username=(info.get("name") or email.split("@")[0])[:255],
                    referral_code=secrets.token_urlsafe(8).upper())
        db.add(user)
        await db.flush()
    if user.deleted_at is not None:
        raise HTTPException(401, "User account deleted")
    raw = await issue_app_code(db, user.id)
    await audit(db, "auth.user.login", f"user:{user.id}", None, {"method": "google", "ip": _client_ip(request)})
    await db.commit()
    resp = RedirectResponse(oauth_finish_url(raw, bool(claims.get("app"))))
    resp.delete_cookie("google_oauth_state")
    return resp
