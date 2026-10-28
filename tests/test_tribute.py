"""Tribute (tribute.py, v28.44): a signed donation in Telegram tops up the wallet of the customer with that Telegram
account, once; anything else is acknowledged and not credited."""
import hashlib
import hmac
import json
from decimal import Decimal

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app import main as shop
from app import tribute
from app.models import User
from test_subscription_commerce import database  # noqa: F401


def note(**over):
    body = {"name": "new_donation", "created_at": "2026-10-28T18:00:00Z",
            "payload": {"donation_request_id": 77, "telegram_user_id": 5550001, "amount": 25000, "currency": "rub", **over}}
    return json.dumps(body).encode()


def req(body: bytes, sig: str):
    sent = []

    async def receive():
        if sent:
            return {"type": "http.disconnect"}
        sent.append(1)
        return {"type": "http.request", "body": body, "more_body": False}
    return Request({"type": "http", "method": "POST", "path": "/api/webhooks/tribute", "headers": [(b"trbt-signature", sig.encode())],
                    "client": ("203.0.113.9", 1), "query_string": b""}, receive)


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setattr(tribute.settings, "tribute_api_key", "tr-key")
    monkeypatch.setattr(tribute.settings, "tribute_donate_link", "https://t.me/tribute/app?startapp=dXYZ")
    monkeypatch.setattr(tribute.settings, "default_currency", "RUB")


def sign(body: bytes) -> str:
    return hmac.new(b"tr-key", body, hashlib.sha256).hexdigest()


def test_parse_takes_donations_in_the_shop_currency_only(keys):
    d = tribute.parse(note())
    assert d["telegram_id"] == 5550001 and d["amount"] == Decimal("250.00") and d["event"] == "77:5550001:25000:2026-10-28T18:00:00Z"
    assert tribute.parse(note(currency="eur")) == {"skip": "currency EUR"}
    assert tribute.parse(json.dumps({"name": "cancelled_subscription", "payload": {}}).encode())["skip"].startswith("event")
    assert tribute.parse(note(telegram_user_id=None))["skip"] == "no payer or amount"


@pytest.mark.asyncio
async def test_signed_donation_tops_up_the_wallet_once(database, keys, monkeypatch):  # noqa: F811
    db = database
    owner = await db.get(User, 1)
    owner.telegram_id = 5550001
    before = Decimal(str(owner.wallet_balance))
    await db.commit()
    events = {}

    async def register(session, provider, event_id, payment_id):
        if event_id in events:
            return False
        events[event_id] = "processing"
        return True

    async def finish(session, provider, event_id, *, ok, error=None):
        events[event_id] = "processed" if ok else "retry"

    async def quiet(*a, **k):
        return None
    monkeypatch.setattr(shop, "register_provider_event", register)
    monkeypatch.setattr(shop, "finish_provider_event", finish)
    monkeypatch.setattr(shop, "engine", db.bind)
    monkeypatch.setattr(shop, "redis_client", object())
    monkeypatch.setattr(shop, "notify_user_telegram", quiet)
    body = note()
    assert await tribute.tribute_webhook(req(body, sign(body)), db=db) == {"status": "ok"}
    await db.refresh(owner)
    assert Decimal(str(owner.wallet_balance)) == before + Decimal("250.00")
    assert list(events.values()) == ["processed"]
    assert await tribute.tribute_webhook(req(body, sign(body)), db=db) == {"status": "duplicate"}
    await db.refresh(owner)
    assert Decimal(str(owner.wallet_balance)) == before + Decimal("250.00"), "a repeated notification credits nothing"
    other = note(telegram_user_id=999)
    assert (await tribute.tribute_webhook(req(other, sign(other)), db=db))["reason"] == "unknown customer"
    with pytest.raises(HTTPException) as bad:
        await tribute.tribute_webhook(req(body, "0" * 64), db=db)
    assert bad.value.status_code == 403


def test_link_is_offered_only_when_set_up(keys, monkeypatch):
    from app.app_config import _tribute
    assert _tribute() == {"url": "https://t.me/tribute/app?startapp=dXYZ"}
    monkeypatch.setattr(tribute.settings, "tribute_api_key", "")
    assert _tribute() is None
