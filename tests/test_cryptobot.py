"""CryptoBot (Crypto Pay) as a reserve gateway: invoice creation, signed webhooks, verification against the
invoice itself, and routing to it when the main gateway is unavailable."""
import hashlib
import hmac
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from starlette.requests import Request

from app import main as shop
from app import payments
from app.models import Payment, PaymentProviderHealth
from test_subscription_commerce import database  # noqa: F401

TOKEN = "12345:AAcryptopaytoken"


class Api:
    def __init__(self):
        self.calls, self.invoice = [], {"invoice_id": 777, "status": "paid", "currency_type": "fiat", "fiat": "RUB", "amount": "100",
                                        "payload": "order-1"}

    async def post(self, url, json=None, headers=None):
        self.calls.append((url, json, headers))
        body = {"ok": True, "result": {"invoice_id": 777, "bot_invoice_url": "https://t.me/CryptoBot?start=IV777", "status": "active"}}
        return type("R", (), {"raise_for_status": lambda self: None, "json": lambda self: body})()

    async def get(self, url, params=None, headers=None):
        self.calls.append((url, params, headers))
        body = {"ok": True, "result": {"items": [self.invoice]}}
        return type("R", (), {"raise_for_status": lambda self: None, "json": lambda self: body})()


@pytest.fixture
def api(monkeypatch):
    fake = Api()

    @asynccontextmanager
    async def client(timeout):
        yield fake
    monkeypatch.setattr(payments, "_public_client", client)
    monkeypatch.setattr(payments.settings, "cryptobot_token", TOKEN)
    monkeypatch.setattr(payments.settings, "cryptobot_network", "mainnet")
    return fake


@pytest.mark.asyncio
async def test_an_invoice_is_created_in_rubles_with_the_order_in_its_payload(api):
    out = await payments.CryptoBotProvider().create(Decimal("199"), "order-1", "VPN 1 месяц", "https://shop.example/paid")
    url, body, headers = api.calls[0]
    assert url == "https://pay.crypt.bot/api/createInvoice" and headers == {"Crypto-Pay-API-Token": TOKEN}
    assert (body["currency_type"], body["fiat"], body["amount"], body["payload"]) == ("fiat", "RUB", "199.00", "order-1")
    assert out == {"id": "777", "url": "https://t.me/CryptoBot?start=IV777", "status": "active"}


@pytest.mark.asyncio
async def test_payment_is_confirmed_only_by_the_invoice_itself(api):
    provider = payments.CryptoBotProvider()
    assert await provider.verify_succeeded("777", Decimal("100"), "RUB", "order-1") is True
    assert await provider.verify_succeeded("777", Decimal("100"), "RUB", "order-2") is False, "another order"
    assert await provider.verify_succeeded("777", Decimal("150"), "RUB", "order-1") is False, "another amount"
    api.invoice["status"] = "active"
    assert await provider.verify_succeeded("777", Decimal("100"), "RUB", "order-1") is False, "not paid yet"


def signed(body: dict, token=TOKEN):
    raw = json.dumps(body).encode()
    sig = hmac.new(hashlib.sha256(token.encode()).digest(), raw, hashlib.sha256).hexdigest()

    async def receive():
        return {"type": "http.request", "body": raw, "more_body": False}
    return Request({"type": "http", "method": "POST", "path": "/api/webhooks/cryptobot", "client": ("1.2.3.4", 1), "query_string": b"",
                    "headers": [(b"crypto-pay-api-signature", sig.encode()), (b"content-type", b"application/json")]}, receive)


@pytest.mark.asyncio
async def test_a_signed_paid_webhook_fulfills_once_and_a_forged_one_is_refused(database, api, monkeypatch):
    database.add(Payment(user_id=1, subscription_id=1, plan_id=1, provider="cryptobot", order_id="order-1", provider_payment_id="777",
                         amount=Decimal("100"), currency="RUB", status="pending", idempotency_key="k-cb"))
    await database.commit()
    fulfilled = []

    async def confirm(payment_id, db):
        fulfilled.append(payment_id)
        return {"ok": True}

    async def claim(db, provider, event_id, payment_id):
        return event_id not in claimed and not claimed.add(event_id)
    claimed = set()

    async def finish(*a, **k):
        return None
    monkeypatch.setattr(shop, "_confirm_and_fulfill_payment", confirm)
    monkeypatch.setattr(shop, "register_provider_event", claim)
    monkeypatch.setattr(shop, "finish_provider_event", finish)
    monkeypatch.setattr(shop, "engine", database.bind)
    update = {"update_type": "invoice_paid", "payload": {"invoice_id": 777, "status": "paid", "payload": "order-1"}}
    assert await shop.cryptobot_webhook(signed(update), database) == {"ok": True}
    assert (await shop.cryptobot_webhook(signed(update), database)).get("duplicate") is True
    assert len(fulfilled) == 1
    with pytest.raises(HTTPException) as forged:
        await shop.cryptobot_webhook(signed(update, token="99999:other"), database)
    assert forged.value.status_code == 403


@pytest.mark.asyncio
async def test_cryptobot_takes_over_when_the_main_gateway_is_down(database, monkeypatch):
    monkeypatch.setattr(shop.settings, "yookassa_shop_id", "shop")
    monkeypatch.setattr(shop.settings, "yookassa_secret_key", "key")
    monkeypatch.setattr(shop.settings, "yookassa_webhook_ip_allowlist", "185.71.76.0/27")
    monkeypatch.setattr(shop.settings, "cryptobot_token", TOKEN)
    order = await shop._payment_provider_order(database, None)
    assert order[0] == "yookassa" and "cryptobot" in order
    yookassa = await database.scalar(select(PaymentProviderHealth).where(PaymentProviderHealth.provider == "yookassa"))
    yookassa.circuit_open_until = datetime.utcnow() + timedelta(minutes=5)  # several failures in a row
    await database.commit()
    assert (await shop._payment_provider_order(database, None))[0] == "cryptobot"
