"""Sign-in to the native apps by a one-use link (bot, cabinet, Yandex/VK/Google with ?app=1).

Behaviour, not source text: a code issued for a user is redeemed by the native client with a
PKCE challenge, exchanged for a bearer session exactly once, and refused to browsers, to a second
use and after expiry. The https trampoline only forwards; Google needs a verified e-mail and never
links an unverified registration.
"""
import hashlib
import urllib.parse
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from fastapi import HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from starlette.requests import Request

from app import app_login
from app import main as shop
from app.config import settings
from app.mobile_auth import exchange_mobile_code, pkce_challenge
from app.models import AuthExchangeCode, Base, User, UserSession

VERIFIER = "v" * 50


@pytest_asyncio.fixture
async def db(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        session.add(User(id=1, username="lusi", referral_code="LUSI1", telegram_id=777))
        await session.commit()
        monkeypatch.setattr(settings, "api_domain", "api.corgi.test")
        monkeypatch.setattr(settings, "app_env", "test")
        monkeypatch.setattr(settings, "mobile_require_proof", False)
        yield session
    await engine.dispose()


def native(path="/api/auth/mobile/code", client="android-user", challenge=True, browser=False):
    headers = [(b"x-shop-client", client.encode()), (b"user-agent", b"CorgiLusi-Android-User/3.0.0"), (b"host", b"api.corgi.test")]
    if challenge:
        headers.append((b"x-shop-code-challenge", pkce_challenge(VERIFIER).encode()))
    if browser:
        headers.append((b"origin", b"https://evil.test"))
    return Request({"type": "http", "method": "POST", "path": path, "headers": headers, "client": ("10.0.0.5", 1234),
                    "scheme": "https", "server": ("api.corgi.test", 443), "query_string": b""})


class Redis:
    def __init__(self):
        self.keys = set()

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.keys:
            return False
        self.keys.add(key)
        return True


def test_links_point_at_the_api_and_the_app_scheme(monkeypatch):
    monkeypatch.setattr(settings, "api_domain", "api.corgi.test")
    monkeypatch.setattr(settings, "mobile_app_scheme", "corgi")
    link = app_login.deep_link("A" * 43)
    parsed = urllib.parse.urlparse(link)
    assert parsed.scheme == "corgi" and parsed.netloc == "login"
    assert urllib.parse.parse_qs(parsed.query) == {"base": ["https://api.corgi.test"], "code": ["A" * 43]}
    assert app_login.open_url("A" * 43) == "https://api.corgi.test/api/app/open?code=" + "A" * 43
    monkeypatch.setattr(settings, "mobile_app_scheme", "javascript:alert(1)//")
    assert app_login.app_scheme() == "corgi", "an unsafe scheme falls back to the default"


def test_oauth_finish_goes_to_the_app_only_when_asked(monkeypatch):
    monkeypatch.setattr(settings, "cabinet_url", "https://cabinet.corgi.test")
    assert app_login.oauth_finish_url("C" * 43, False) == "https://cabinet.corgi.test/?code=" + "C" * 43
    assert app_login.oauth_finish_url("C" * 43, True).startswith("corgi://login?")


def test_methods_follow_configuration(monkeypatch):
    for name, value in {"bot_username": "@corgi_bot", "bot_token": "1:x", "yandex_client_id": "", "yandex_redirect_uri": "",
                        "vk_client_id": "vk", "vk_redirect_uri": "https://api/cb", "google_client_id": "", "google_redirect_uri": ""}.items():
        monkeypatch.setattr(settings, name, value)
    methods = app_login.login_methods()
    assert methods["telegram"] and methods["telegram_url"] == "https://t.me/corgi_bot?start=app_login"
    assert methods["vk"] and not methods["yandex"] and not methods["google"]


@pytest.mark.asyncio
async def test_trampoline_forwards_without_consuming(db):
    page = await app_login.open_app(code="B" * 43)
    body = page.body.decode()
    assert "corgi://login?base=https%3A%2F%2Fapi.corgi.test&amp;code=" + "B" * 43 in body
    assert page.headers["cache-control"] == "no-store" and "frame-ancestors 'none'" in page.headers["content-security-policy"]
    with pytest.raises(HTTPException) as bad:
        await app_login.open_app(code='"><script>')
    assert bad.value.status_code == 400


@pytest.mark.asyncio
async def test_code_signs_the_native_app_in_exactly_once(db):
    code = await app_login.issue_app_code(db, 1)
    await db.commit()
    stored = (await db.execute(select(AuthExchangeCode))).scalar_one()
    assert stored.code_hash == hashlib.sha256(code.encode()).hexdigest(), "only the hash is stored"
    body = await app_login.redeem_app_code(app_login.AppCodeIn(code=code), native(), Response(), db)
    assert "access_token" not in body and body["authorization_code"], "the bearer comes only from the PKCE exchange"
    redis = Redis()
    token = await exchange_mobile_code(native("/api/auth/mobile/token"), body["authorization_code"], VERIFIER, redis)
    assert token["token_type"] == "bearer" and token["access_token"]
    assert (await db.execute(select(UserSession).where(UserSession.user_id == 1))).scalar_one()
    with pytest.raises(HTTPException) as again:
        await app_login.redeem_app_code(app_login.AppCodeIn(code=code), native(), Response(), db)
    assert again.value.status_code == 400
    with pytest.raises(HTTPException) as wrong_verifier:
        await exchange_mobile_code(native("/api/auth/mobile/token"), body["authorization_code"], "w" * 50, redis)
    assert wrong_verifier.value.status_code == 401


@pytest.mark.asyncio
async def test_browsers_old_codes_and_missing_pkce_are_refused(db):
    code = await app_login.issue_app_code(db, 1)
    await db.commit()
    for request, status in ((native(client="browser"), 400), (native(browser=True), 403), (native(challenge=False), 400)):
        with pytest.raises(HTTPException) as refused:
            await app_login.redeem_app_code(app_login.AppCodeIn(code=code), request, Response(), db)
        assert refused.value.status_code == status
    row = (await db.execute(select(AuthExchangeCode))).scalar_one()
    assert row.used_at is None, "a refused attempt does not burn the code"
    row.expires_at = datetime.utcnow() - timedelta(seconds=1)
    await db.commit()
    with pytest.raises(HTTPException) as expired:
        await app_login.redeem_app_code(app_login.AppCodeIn(code=code), native(), Response(), db)
    assert expired.value.status_code == 400


class FakeGoogle:
    def __init__(self, profile):
        self.profile = profile

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, data):
        assert data["client_secret"] == "google-secret"
        return type("R", (), {"status_code": 200, "json": lambda self: {"access_token": "at"}})()

    async def get(self, url, headers):
        profile = self.profile
        return type("R", (), {"status_code": 200, "json": lambda self: profile})()


def google_request(state):
    cookie = f"google_oauth_state={state}".encode()
    return Request({"type": "http", "method": "GET", "path": "/api/auth/google/callback", "headers": [(b"cookie", cookie)],
                    "client": ("10.0.0.5", 1), "query_string": b""})


@pytest.fixture
def google(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "gid")
    monkeypatch.setattr(settings, "google_client_secret", "google-secret")
    monkeypatch.setattr(settings, "google_redirect_uri", "https://api.corgi.test/api/auth/google/callback")

    def use(profile):
        monkeypatch.setattr(shop, "_pinned_public_http_client", lambda timeout: FakeGoogle(profile))
    return use


@pytest.mark.asyncio
async def test_google_creates_a_verified_account_and_returns_to_the_app(db, google):
    google({"email": "Lusi@Example.test", "email_verified": True, "name": "Lusi"})
    state = app_login._google_state(True)
    resp = await app_login.google_callback(code="g", state=state, request=google_request(state), db=db)
    assert resp.headers["location"].startswith("corgi://login?")
    user = (await db.execute(select(User).where(User.email == "lusi@example.test"))).scalar_one()
    assert user.email_verified_at is not None


@pytest.mark.asyncio
async def test_google_refuses_unverified_mail_and_unverified_registrations(db, google):
    google({"email": "x@example.test", "email_verified": False})
    state = app_login._google_state(False)
    with pytest.raises(HTTPException) as unverified:
        await app_login.google_callback(code="g", state=state, request=google_request(state), db=db)
    assert unverified.value.status_code == 401
    db.add(User(email="taken@example.test", email_password_hash="x", referral_code="TAKEN"))
    await db.commit()
    google({"email": "taken@example.test", "email_verified": True})
    with pytest.raises(HTTPException) as taken:
        await app_login.google_callback(code="g", state=state, request=google_request(state), db=db)
    assert taken.value.status_code == 409
    with pytest.raises(HTTPException) as forged:
        await app_login.google_callback(code="g", state=state, request=google_request("other"), db=db)
    assert forged.value.status_code == 400
