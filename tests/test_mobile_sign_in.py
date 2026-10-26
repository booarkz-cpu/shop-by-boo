"""v28.31.0: app sign-in through Telegram (bot), Yandex, VK and Google, bound to the app's PKCE verifier."""
import json
import urllib.parse
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app import main as shop
from app import mobile_oauth as mo
from app.config import settings
from app.mobile_auth import exchange_mobile_code, pkce_challenge
from app.models import AuditLog, User
from app.security import decrypt_secret
from test_subscription_commerce import database  # noqa: F401

VERIFIER = "v" * 43 + "Lusi-verifier_123"
CHALLENGE = pkce_challenge(VERIFIER)


class Req:
    def __init__(self, client="android-user", challenge=CHALLENGE):
        self.headers = {"x-shop-client": client, "x-shop-code-challenge": challenge, "user-agent": "CorgiLusi-Android-User/2.17.0"}
        self.url = SimpleNamespace(hostname="api.shop.example", path="/api/auth/mobile/token")
        self.method = "POST"
        self.client = SimpleNamespace(host="203.0.113.5")
        self.cookies = {}


class Redis:
    def __init__(self):
        self.keys = set()

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.keys:
            return False
        self.keys.add(key)
        return True


@pytest.fixture(autouse=True)
def providers(monkeypatch):
    for key, value in {"google_client_id": "g-id", "google_client_secret": "g-secret", "yandex_client_id": "y-id",
                       "yandex_client_secret": "y-secret", "vk_client_id": "", "vk_client_secret": "", "bot_token": "123:TEST",
                       "bot_username": "corgi_lusi_bot", "api_domain": "api.shop.example", "mobile_auth_scheme": "corgilusi"}.items():
        monkeypatch.setattr(settings, key, value)
    redis = Redis()
    monkeypatch.setattr(shop, "redis_client", redis)
    return redis


def test_only_configured_providers_are_offered():
    assert mo.available_providers() == ["telegram", "yandex", "google"]


@pytest.mark.asyncio
async def test_start_sends_the_browser_to_the_provider_with_a_signed_state():
    resp = await mo.oauth_start("google", "ios-user", CHALLENGE)
    url = urllib.parse.urlparse(resp.headers["location"])
    q = dict(urllib.parse.parse_qsl(url.query))
    assert url.netloc == "accounts.google.com" and q["client_id"] == "g-id"
    assert q["redirect_uri"] == "https://api.shop.example/api/auth/mobile/oauth/google/callback"
    state = mo._read_state(q["state"], "google")
    assert state["c"] == "ios-user" and state["ch"] == CHALLENGE
    for provider, client, challenge, status in (("github", "ios-user", CHALLENGE, 404), ("google", "android-admin", CHALLENGE, 400),
                                                ("google", "ios-user", "short", 400), ("vk", "ios-user", CHALLENGE, 503)):
        with pytest.raises(HTTPException) as refused:
            await mo.oauth_start(provider, client, challenge)
        assert refused.value.status_code == status


def _query(resp):
    url = urllib.parse.urlparse(resp.headers["location"])
    assert url.scheme == "corgilusi" and url.netloc == "auth"
    return dict(urllib.parse.parse_qsl(url.query))


@pytest.mark.asyncio
async def test_callback_signs_in_and_only_the_app_with_the_verifier_gets_the_session(database, monkeypatch, providers):
    async def identity(provider, code):
        assert provider == "google" and code == "provider-code"
        return {"id": "g-1001", "email": "lusi.fan@gmail.com", "username": "Lusi Fan"}
    monkeypatch.setattr(mo, "fetch_identity", identity)
    state = mo._state("google", "android-user", CHALLENGE)
    q = _query(await mo.oauth_callback("google", Req(), state=state, code="provider-code", db=database))
    user = (await database.execute(select(User).where(User.google_id == "g-1001"))).scalar_one()
    assert user.email == "lusi.fan@gmail.com" and q["provider"] == "google"
    payload = json.loads(decrypt_secret(q["code"]))
    assert payload["client"] == "android-user" and payload["challenge"] == CHALLENGE
    with pytest.raises(HTTPException):  # someone else's verifier
        await exchange_mobile_code(Req(), q["code"], "x" * 43, providers)
    token = await exchange_mobile_code(Req(), q["code"], VERIFIER, providers)
    assert shop.decode_token(token["access_token"])["sub"] == str(user.id)
    # The same provider redirect cannot be replayed.
    assert _query(await mo.oauth_callback("google", Req(), state=state, code="provider-code", db=database))["error"] == "used"
    assert (await database.execute(select(AuditLog).where(AuditLog.action == "auth.user.login"))).scalars().first() is not None


@pytest.mark.asyncio
async def test_provider_email_never_takes_over_an_email_account(database, monkeypatch):
    database.add(User(email="owner@example.com", referral_code="OWNEREM"))
    await database.commit()

    async def identity(provider, code):
        return {"id": "g-2002", "email": "owner@example.com", "username": None}
    monkeypatch.setattr(mo, "fetch_identity", identity)
    q = _query(await mo.oauth_callback("google", Req(), state=mo._state("google", "ios-user", CHALLENGE), code="c", db=database))
    assert q["error"] == "denied" and "почта уже зарегистрирована" in q["message"]
    assert (await database.execute(select(User).where(User.google_id == "g-2002"))).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_cancelled_provider_page_returns_to_the_app(database):
    q = _query(await mo.oauth_callback("yandex", Req(), state=mo._state("yandex", "ios-user", CHALLENGE), error="access_denied", db=database))
    assert q == {"error": "cancelled"}
    with pytest.raises(HTTPException):
        await mo.oauth_callback("yandex", Req(), state="forged", code="c", db=database)


@pytest.mark.asyncio
async def test_telegram_sign_in_needs_the_right_code_in_the_bot(database, providers):
    started = await mo.telegram_start(mo.TelegramStartIn(platform="android"), Req(), database)
    assert started["url"].startswith("https://t.me/corgi_lusi_bot?start=login_") and len(started["code"]) == 2
    nonce = started["nonce"]
    prompt = await mo.telegram_prompt(database, nonce)
    assert started["code"] in prompt["choices"] and len(prompt["choices"]) == 3 and prompt["platform"] == "Android"
    assert (await mo.telegram_poll(mo.TelegramPollIn(nonce=nonce), Req(), database))["status"] == "pending"
    with pytest.raises(HTTPException) as other_app:
        await mo.telegram_poll(mo.TelegramPollIn(nonce=nonce), Req(client="ios-user"), database)
    assert other_app.value.status_code == 403
    assert await mo.telegram_answer(database, nonce, started["code"], 555001, "lusi") == "approved"
    approved = await mo.telegram_poll(mo.TelegramPollIn(nonce=nonce), Req(), database)
    assert approved["status"] == "approved"
    token = await exchange_mobile_code(Req(), approved["authorization_code"], VERIFIER, providers)
    user = (await database.execute(select(User).where(User.telegram_id == 555001))).scalar_one()
    assert shop.decode_token(token["access_token"])["sub"] == str(user.id)
    assert (await mo.telegram_poll(mo.TelegramPollIn(nonce=nonce), Req(), database))["status"] == "expired"  # used once


@pytest.mark.asyncio
async def test_a_wrong_code_or_not_me_cancels_the_attempt(database):
    for answer in ("wrong", "deny"):
        started = await mo.telegram_start(mo.TelegramStartIn(), Req(), database)
        choice = next(c for c in (await mo.telegram_prompt(database, started["nonce"]))["choices"] if c != started["code"]) if answer == "wrong" else "deny"
        assert await mo.telegram_answer(database, started["nonce"], choice, 777, None) == "denied"
        assert await mo.telegram_answer(database, started["nonce"], started["code"], 777, None) == "expired"
        assert (await mo.telegram_poll(mo.TelegramPollIn(nonce=started["nonce"]), Req(), database))["status"] == "denied"
    assert (await database.execute(select(User).where(User.telegram_id == 777))).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_telegram_start_requires_the_customer_app_and_pkce(database):
    with pytest.raises(HTTPException):
        await mo.telegram_start(mo.TelegramStartIn(), Req(client="android-admin"), database)
    with pytest.raises(HTTPException):
        await mo.telegram_start(mo.TelegramStartIn(), Req(challenge="bad"), database)
