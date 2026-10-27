"""Freekassa as a reserve gateway: signed payment link, notifications only from Freekassa with secret word 2,
the order re-read through API v1 before fulfillment, and routing when it is configured."""
import hashlib
import hmac
from contextlib import asynccontextmanager
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app import main as shop
from app import payments, payments_api
from app.models import Payment
from test_subscription_commerce import database  # noqa: F401

FK_IP = "168.119.157.136"


class Api:
    def __init__(self):
        self.calls = []
        self.order = {"merchant_order_id": "order-1", "fk_order_id": 555, "amount": 100, "currency": "RUB", "status": 1}

    async def post(self, url, json=None, headers=None):
        self.calls.append((url, json))
        body = {"type": "success", "pages": 1, "orders": [self.order]}
        return type("R", (), {"raise_for_status": lambda self: None, "json": lambda self: body})()


@pytest.fixture
def fk(monkeypatch):
    api = Api()

    @asynccontextmanager
    async def client(timeout):
        yield api
    monkeypatch.setattr(payments, "_public_client", client)
    for name, value in {"freekassa_shop_id": "7012", "freekassa_secret1": "secret", "freekassa_secret2": "secret2",
                        "freekassa_api_key": "api-key"}.items():
        monkeypatch.setattr(payments.settings, name, value)
    return api


def sign(params, secret="secret2"):
    return hashlib.md5(f"{params['MERCHANT_ID']}:{params['AMOUNT']}:{secret}:{params['MERCHANT_ORDER_ID']}".encode()).hexdigest()


def test_the_payment_link_is_signed_as_the_documentation_shows():
    assert payments.FreekassaProvider.form_signature("7012", "100.11", "secret", "RUB", "154") == hashlib.md5(b"7012:100.11:secret:RUB:154").hexdigest()
    body = {"shopId": 7012, "nonce": 5, "paymentId": "order-1"}
    expected = hmac.new(b"api-key", b"5|order-1|7012", hashlib.sha256).hexdigest()
    assert payments.FreekassaProvider.api_signature(body, "api-key") == expected, "values sorted by key: nonce, paymentId, shopId"


@pytest.mark.asyncio
async def test_creating_a_payment_needs_no_call_and_carries_the_order(fk):
    out = await payments.FreekassaProvider().create(Decimal("199"), "order-1", "VPN", "https://shop/paid")
    query = {k: v[0] for k, v in parse_qs(urlsplit(out["url"]).query).items()}
    assert out["id"] == "order-1" and out["url"].startswith("https://pay.fk.money/") and not fk.calls
    assert (query["m"], query["oa"], query["currency"], query["o"]) == ("7012", "199.00", "RUB", "order-1")
    assert query["s"] == hashlib.md5(b"7012:199.00:secret:RUB:order-1").hexdigest()


@pytest.mark.asyncio
async def test_only_a_paid_order_with_the_same_amount_counts(fk):
    provider = payments.FreekassaProvider()
    assert await provider.verify_succeeded("order-1", Decimal("100"), "RUB", "order-1") is True
    url, body = fk.calls[0]
    assert url == "https://api.fk.life/v1/orders" and body["paymentId"] == "order-1" and body["shopId"] == 7012
    assert body["signature"] == payments.FreekassaProvider.api_signature({k: v for k, v in body.items() if k != "signature"}, "api-key")
    assert await provider.verify_succeeded("order-1", Decimal("150"), "RUB", "order-1") is False, "another amount"
    fk.order["status"] = 0
    assert await provider.verify_succeeded("order-1", Decimal("100"), "RUB", "order-1") is False, "not paid yet"
    first, second = fk.calls[-2][1]["nonce"], fk.calls[-1][1]["nonce"]
    assert second > first, "the nonce grows with every request"


def test_notifications_are_accepted_only_from_freekassa_with_secret_two(fk):
    provider = payments.FreekassaProvider()
    params = {"MERCHANT_ID": "7012", "AMOUNT": "100", "intid": "555", "MERCHANT_ORDER_ID": "order-1"}
    params["SIGN"] = sign(params)
    assert provider.verify_notification(params, FK_IP)["intid"] == "555"
    for bad_params, ip in (({**params, "SIGN": sign(params, "secret")}, FK_IP), (params, "1.2.3.4"),
                           ({**params, "MERCHANT_ID": "1", "SIGN": sign({**params, "MERCHANT_ID": "1"})}, FK_IP)):
        with pytest.raises(payments.SignatureVerificationError):
            provider.verify_notification(bad_params, ip)


def notification(params, ip=FK_IP):
    query = "&".join(f"{k}={v}" for k, v in params.items()).encode()
    return Request({"type": "http", "method": "GET", "path": "/api/webhooks/freekassa", "client": (ip, 1), "query_string": query, "headers": []})


@pytest.mark.asyncio
async def test_a_paid_notification_fulfills_once_and_answers_yes(database, fk, monkeypatch):
    database.add(Payment(user_id=1, subscription_id=1, plan_id=1, provider="freekassa", order_id="order-1", provider_payment_id="order-1",
                         amount=Decimal("100"), currency="RUB", status="pending", idempotency_key="k-fk"))
    await database.commit()
    fulfilled, claimed = [], set()

    async def confirm(payment_id, db):
        fulfilled.append(payment_id)
        return {"ok": True}

    async def claim(db, provider, event_id, payment_id):
        return event_id not in claimed and not claimed.add(event_id)

    async def finish(*a, **k):
        return None
    monkeypatch.setattr(shop, "_confirm_and_fulfill_payment", confirm)
    monkeypatch.setattr(shop, "register_provider_event", claim)
    monkeypatch.setattr(shop, "finish_provider_event", finish)
    monkeypatch.setattr(shop, "engine", database.bind)
    monkeypatch.setattr(shop, "_client_ip", lambda request: request.client.host)
    params = {"MERCHANT_ID": "7012", "AMOUNT": "100", "intid": "555", "MERCHANT_ORDER_ID": "order-1"}
    params["SIGN"] = sign(params)
    assert (await shop.freekassa_webhook(notification(params), database)).body == b"YES"
    assert (await shop.freekassa_webhook(notification(params), database)).body == b"YES", "a repeat is answered and ignored"
    assert len(fulfilled) == 1
    with pytest.raises(HTTPException) as foreign:
        await shop.freekassa_webhook(notification(params, "8.8.8.8"), database)
    assert foreign.value.status_code == 403
    cheaper = {**params, "AMOUNT": "1"}
    cheaper["SIGN"] = sign(cheaper)
    with pytest.raises(HTTPException) as wrong_amount:
        await shop.freekassa_webhook(notification(cheaper), database)
    assert wrong_amount.value.status_code == 403


@pytest.mark.asyncio
async def test_freekassa_is_routable_when_configured(database, fk):
    order = await shop._payment_provider_order(database, None)
    assert "freekassa" in order
    created = await payments_api._checkout_provider("freekassa").create(Decimal("100"), "order-9", "VPN", "https://shop/paid")
    assert created["id"] == "order-9"
