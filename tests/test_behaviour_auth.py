"""Customer and admin sign-in (auth_api.py, admin_auth_api.py), tested by behaviour.

Replaces the source-text checks of v1.0.3, v1 deep audit and v2.0.0 («'Invalid Telegram auth
date' in MAIN», «'UserSession.jti_hash' in MAIN», «'/api/me/security/revoke-all' in MAIN» …):
each property is now exercised through the real functions against a database.
"""
import hashlib
import hmac
import json
import time
import urllib.parse
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from fastapi import HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from starlette.requests import Request

from app import main as shop  # first: main imports the moved sections at its end
from app import admin_auth_api, auth_api, runtime_security, totp
from app.config import settings
from app.models import AdminSession, AdminUser, AuthExchangeCode, Base, User, UserSession
from app.security import encrypt_secret, hash_password

BOT_TOKEN = "123456:TEST-token"
UA = b"Mozilla/5.0 Corgi test"


@pytest.fixture(autouse=True)
def bot(monkeypatch):
    monkeypatch.setattr(settings, "bot_token", BOT_TOKEN)


@pytest_asyncio.fixture
async def db(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        monkeypatch.setattr(settings, "bot_token", BOT_TOKEN)
        monkeypatch.setattr(settings, "mobile_require_proof", False)

        async def no_lock(db, key):
            return None
        monkeypatch.setattr(shop, "_advisory_lock", no_lock)
        yield session
    await engine.dispose()


def init_data(user: dict | None, *, auth_date: int | None = None, token: str = BOT_TOKEN, tamper: bool = False) -> str:
    pairs = {"auth_date": str(int(time.time()) if auth_date is None else auth_date), "query_id": "AAE"}
    if user is not None:
        pairs["user"] = json.dumps(user, separators=(",", ":"))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    pairs["hash"] = hmac.new(secret, "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs)).encode(), hashlib.sha256).hexdigest()
    if tamper:
        pairs["user"] = json.dumps({**user, "id": 1}, separators=(",", ":"))
    return urllib.parse.urlencode(pairs)


def request(path="/api/auth/telegram", token: str | None = None, ua: bytes = UA, method="POST", cookie: bytes | None = None):
    headers = [(b"user-agent", ua), (b"host", b"api.corgi.test")]
    if token:
        headers.append((b"authorization", f"Bearer {token}".encode()))
    if cookie:
        headers.append((b"cookie", cookie))
    return Request({"type": "http", "method": method, "path": path, "headers": headers, "client": ("10.0.0.5", 1),
                    "scheme": "https", "server": ("api.corgi.test", 443), "query_string": b""})


# ---------------------------------------------------------------- Telegram initData

def test_valid_init_data_returns_the_telegram_user():
    user = auth_api.telegram_user_from_init_data(init_data({"id": 777, "username": "lusi"}))
    assert user == {"id": 777, "username": "lusi"}


@pytest.mark.parametrize("data,message", [
    (lambda: init_data({"id": 777}, tamper=True), "Invalid Telegram initData"),
    (lambda: init_data({"id": 777}, token="999:other"), "Invalid Telegram initData"),
    (lambda: init_data({"id": 777}, auth_date=int(time.time()) - 601), "Expired Telegram initData"),
    (lambda: init_data({"id": 777}).replace("auth_date=", "auth_date=x"), "Invalid Telegram auth date"),
    (lambda: init_data({"username": "no-id"}), "Invalid Telegram user data"),
    (lambda: init_data(None), "Invalid Telegram user data"),
    (lambda: "auth_date=1&user=%7B%7D", "Invalid Telegram initData"),
])
def test_forged_expired_or_broken_init_data_is_refused(data, message):
    with pytest.raises(HTTPException) as refused:
        auth_api.telegram_user_from_init_data(data())
    assert (refused.value.status_code, refused.value.detail) == (401, message)


def test_without_a_bot_token_nothing_is_trusted(monkeypatch):
    raw = init_data({"id": 777})
    monkeypatch.setattr(settings, "bot_token", "")
    with pytest.raises(HTTPException):
        auth_api.telegram_user_from_init_data(raw)


@pytest.mark.asyncio
async def test_telegram_sign_in_creates_one_account_and_a_registered_session(db):
    for name in ("lusi", "lusi_renamed"):
        response = Response()
        body = await auth_api.telegram_auth({"initData": init_data({"id": 777, "username": name})}, request(), response, db)
        assert body["telegram_id"] == 777 and body["username"] == name
        assert "rw_user=" in response.headers["set-cookie"]
    users = (await db.execute(select(User))).scalars().all()
    assert len(users) == 1, "the second sign-in reuses the account"
    sessions = (await db.execute(select(UserSession))).scalars().all()
    assert len(sessions) == 2 and all(len(s.jti_hash) == 64 for s in sessions), "only a hash of the session id is stored"


@pytest.mark.asyncio
async def test_sign_ins_of_one_identity_are_serialised_across_processes(db, monkeypatch):
    keys = []

    async def lock(db, key):
        keys.append(key)
    monkeypatch.setattr(shop, "_advisory_lock", lock)
    for telegram_id in (777, 777, 778):
        await auth_api.telegram_auth({"initData": init_data({"id": telegram_id})}, request(), Response(), db)
    assert keys[0] == keys[1] != keys[2], "one lock per Telegram id"
    assert all(1000000000 <= k < 1900000000 for k in keys)


# ---------------------------------------------------------------- sessions

async def signed_in(db, ua=UA):
    user = User(username="lusi", referral_code="LUSI1", telegram_id=777)
    db.add(user)
    await db.commit()
    token = await auth_api.create_user_session(db, user, request(ua=ua))
    return user, token


@pytest.mark.asyncio
async def test_a_session_token_works_until_logout(db):
    user, token = await signed_in(db)
    assert (await auth_api.user_from_token(request("/api/me", token), db)).id == user.id
    assert (await auth_api.user_from_token(request("/api/me", cookie=f"rw_user={token}".encode()), db)).id == user.id
    await auth_api.user_logout(request("/api/auth/logout", token), Response(), db)
    with pytest.raises(HTTPException) as gone:
        await auth_api.user_from_token(request("/api/me", token), db)
    assert gone.value.detail == "User session expired or revoked"


@pytest.mark.asyncio
async def test_revoke_all_signs_every_device_out(db):
    user, first = await signed_in(db)
    second = await auth_api.create_user_session(db, user, request())
    await auth_api.revoke_all_user_sessions(request("/api/me/security/revoke-all", first), db)
    for token in (first, second):
        with pytest.raises(HTTPException):
            await auth_api.user_from_token(request("/api/me", token), db)


@pytest.mark.asyncio
async def test_a_stolen_token_on_another_device_is_revoked(db):
    _user, token = await signed_in(db)
    with pytest.raises(HTTPException) as moved:
        await auth_api.user_from_token(request("/api/me", token, ua=b"curl/8"), db)
    assert moved.value.detail == "User session device changed"
    with pytest.raises(HTTPException):
        await auth_api.user_from_token(request("/api/me", token), db)


@pytest.mark.asyncio
async def test_unregistered_expired_and_foreign_tokens_are_refused(db):
    user, token = await signed_in(db)
    unregistered = auth_api.issue_user_token(user)
    with pytest.raises(HTTPException) as no_session:
        await auth_api.user_from_token(request("/api/me", unregistered), db)
    assert no_session.value.status_code == 401
    session = (await db.execute(select(UserSession))).scalar_one()
    session.expires_at = datetime.utcnow() - timedelta(seconds=1)
    await db.commit()
    with pytest.raises(HTTPException):
        await auth_api.user_from_token(request("/api/me", token), db)
    with pytest.raises(HTTPException):
        await auth_api.user_from_token(request("/api/me"), db)


@pytest.mark.asyncio
async def test_deleted_or_restricted_accounts_get_no_session(db):
    user = User(username="gone", referral_code="GONE1", deleted_at=datetime.utcnow())
    db.add(user)
    await db.commit()
    with pytest.raises(HTTPException) as deleted:
        await auth_api.create_user_session(db, user, request())
    assert deleted.value.status_code == 401
    blocked = User(username="blocked", referral_code="BLK1")
    db.add(blocked)
    await db.commit()
    blocked.restricted_at = datetime.utcnow()
    await db.commit()
    with pytest.raises(HTTPException) as restricted:
        await auth_api.create_user_session(db, blocked, request())
    assert restricted.value.status_code == 403


@pytest.mark.asyncio
async def test_exchange_code_is_single_use_and_short_lived(db):
    user = User(username="ya", referral_code="YA1", yandex_id="42")
    db.add(user)
    await db.commit()
    raw = "c" * 32
    db.add(AuthExchangeCode(code_hash=hashlib.sha256(raw.encode()).hexdigest(), user_id=user.id, expires_at=datetime.utcnow() + timedelta(minutes=1)))
    await db.commit()
    body = await auth_api.auth_exchange(auth_api.ExchangeIn(code=raw), request("/api/auth/exchange"), Response(), db)
    assert body["yandex_id"] == "42"
    with pytest.raises(HTTPException) as again:
        await auth_api.auth_exchange(auth_api.ExchangeIn(code=raw), request("/api/auth/exchange"), Response(), db)
    assert again.value.status_code == 400


# ---------------------------------------------------------------- Yandex

class FakeYandex:
    def __init__(self, profile):
        self.profile = profile

    def __call__(self, **kw):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, data):
        return type("R", (), {"status_code": 200, "json": lambda s: {"access_token": "at"}})()

    async def get(self, url, params, headers):
        profile = self.profile
        return type("R", (), {"status_code": 200, "json": lambda s: profile})()


@pytest.mark.asyncio
@pytest.mark.parametrize("profile,ok", [({"id": "42", "login": "lusi"}, True), ({"login": "no-id"}, False)])
async def test_yandex_needs_a_stable_identifier_and_a_signed_state(db, monkeypatch, profile, ok):
    import httpx

    monkeypatch.setattr(settings, "yandex_client_id", "yid")
    monkeypatch.setattr(settings, "yandex_client_secret", "ysecret")
    monkeypatch.setattr(settings, "yandex_redirect_uri", "https://api.corgi.test/api/auth/yandex/callback")
    monkeypatch.setattr(httpx, "AsyncClient", FakeYandex(profile))
    start = await auth_api.yandex_login(request("/api/auth/yandex", method="GET"), app=1)
    state = urllib.parse.parse_qs(urllib.parse.urlparse(start.headers["location"]).query)["state"][0]
    with pytest.raises(HTTPException) as forged:
        await auth_api.yandex_callback("code", state, request(method="GET", cookie=b"yandex_oauth_state=other"), db)
    assert forged.value.detail == "Invalid OAuth state"
    call = auth_api.yandex_callback("code", state, request(method="GET", cookie=f"yandex_oauth_state={state}".encode()), db)
    if ok:
        resp = await call
        assert resp.headers["location"].startswith("corgi://login?"), "app=1 returns to the native app"
        assert (await db.execute(select(User.yandex_id))).scalar_one() == "42"
    else:
        with pytest.raises(HTTPException) as no_id:
            await call
        assert no_id.value.detail == "Yandex profile has no stable identifier"


# ---------------------------------------------------------------- admin

@pytest.fixture
def limiter(monkeypatch):
    calls = {}

    async def allowed(key, limit, window):
        calls[key] = calls.get(key, 0) + 1
        return calls[key] <= limit

    async def reset(_redis, key):
        calls.pop(key, None)
    monkeypatch.setattr(shop, "_redis_allowed", allowed)
    monkeypatch.setattr(runtime_security, "reset_login_attempts", reset)
    return calls


@pytest.mark.asyncio
async def test_admin_password_and_totp(db, limiter):
    secret = totp.random_base32()
    db.add(AdminUser(email="owner@corgi.test", password_hash=hash_password("correct horse"), role="owner",
                     totp_secret_encrypted=encrypt_secret(secret), mfa_enabled=True))
    await db.commit()
    login = lambda password, otp=None: admin_auth_api.admin_login(
        shop.LoginIn(email=" Owner@Corgi.test ", password=password, otp=otp), request("/api/admin/auth/login"), Response(), db)
    for password, otp, detail in (("wrong", None, "Invalid credentials"), ("correct horse", None, "MFA code required or invalid"),
                                  ("correct horse", "000000", "MFA code required or invalid")):
        with pytest.raises(HTTPException) as refused:
            await login(password, otp)
        assert refused.value.detail == detail
    body = await login("correct horse", totp.code(secret))
    assert body == {"mfa_enabled": True, "role": "owner", "email": "owner@corgi.test"}
    assert (await db.execute(select(AdminSession))).scalar_one().expires_at <= datetime.utcnow() + timedelta(minutes=30)
    assert not limiter, "a successful login clears the attempt counter"


@pytest.mark.asyncio
async def test_admin_brute_force_is_throttled_and_disabled_admins_stay_out(db, limiter):
    db.add(AdminUser(email="op@corgi.test", password_hash=hash_password("correct horse"), role="operator", disabled=True))
    await db.commit()
    statuses = []
    for _ in range(9):
        try:
            await admin_auth_api.admin_login(shop.LoginIn(email="op@corgi.test", password="correct horse"), request("/api/admin/auth/login"), Response(), db)
        except HTTPException as exc:
            statuses.append(exc.status_code)
    assert statuses == [401] * 8 + [429]


@pytest.mark.asyncio
async def test_mfa_disable_needs_the_password(db):
    admin = AdminUser(email="a@corgi.test", password_hash=hash_password("correct horse"), role="owner",
                      totp_secret_encrypted=encrypt_secret(totp.random_base32()), mfa_enabled=True)
    db.add(admin)
    await db.commit()
    with pytest.raises(HTTPException):
        await admin_auth_api.mfa_disable(admin_auth_api.PasswordConfirm(password="wrong pass"), db, admin)
    assert (await admin_auth_api.mfa_disable(admin_auth_api.PasswordConfirm(password="correct horse"), db, admin))["mfa_enabled"] is False
    assert admin.totp_secret_encrypted is None and admin.recovery_codes_encrypted is None
