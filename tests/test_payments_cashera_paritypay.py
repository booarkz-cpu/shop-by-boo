"""Cashera and ParityPay (payments_extra.py, v28.43): payment page, authenticated notifications, the payment re-read
before delivery; AuraPay and ParityPay signatures over the values exactly as sent."""
import hashlib
import hmac
import json
from contextlib import asynccontextmanager
from decimal import Decimal

import httpx
import pytest
from fastapi import FastAPI

from app import payments_extra as px
from app.db import get_db
from app.payment_methods import CAPABILITIES
from app.payment_policy import PAYMENT_AGENTS, PROVIDER_CAPABILITIES


class Api:
    def __init__(self, answers):
        self.calls = []
        self.answers = answers

    async def request(self, method, url, json=None, headers=None, params=None):
        self.calls.append({"method": method, "url": url, "json": json, "params": params, "headers": headers or {}})
        key = next(k for k in self.answers if url.endswith(k))
        body = self.answers[key]
        return type("R", (), {"status_code": 200, "raise_for_status": lambda self: None, "json": lambda self: body})()


def _patch(monkeypatch, api, values):
    @asynccontextmanager
    async def client(timeout):
        yield api
    monkeypatch.setattr(px, "_public_client", client)
    for k, v in values.items():
        monkeypatch.setattr(px.settings, k, v)


@pytest.fixture
def cashera(monkeypatch):
    tx = {"uuid": "0b6a6c1e-1111-4a5b-9c9d-222233334444", "external_id": "order-8", "status": "paid", "amount": 19900, "currency": "RUB"}
    api = Api({"/integration/transactions": {"uuid": tx["uuid"], "status": "pending", "payment_url": "pay.cashera.cash/t/0b6a"},
               "/integration/transactions/" + tx["uuid"]: {"data": tx}})
    _patch(monkeypatch, api, {"cashera_api_key": "ck", "cashera_api_secret": "cs", "webhook_base_url": "https://api.corgi.test"})
    api.tx = tx
    return api


@pytest.fixture
def parity(monkeypatch):
    api = Api({"/v2/invoice/create": {"id": "pp-1", "link": "https://pay.paritypay.net/pp-1", "status": "pending"},
               "/v2/invoice/status": {"id": "pp-1", "order_id": "order-9", "status": "PAID", "amount": 199}})
    _patch(monkeypatch, api, {"paritypay_shop_id": "shop-uuid", "paritypay_secret_key": "k1", "paritypay_callback_secret": "k2",
                              "webhook_base_url": "https://api.corgi.test"})
    return api


def _values_sig(raw: str, key: bytes) -> str:
    """What the gateway does: values in key order, exactly as written in the body."""
    data = json.loads(raw, parse_float=str, parse_int=str)
    joined = "".join("" if data[k] is None else ("true" if data[k] is True else "false" if data[k] is False else str(data[k])) for k in sorted(data))
    return hmac.new(key, joined.encode(), hashlib.sha256).hexdigest()


def test_new_gateways_are_in_the_queue_and_the_methods():
    assert {"cashera", "paritypay"} <= set(PAYMENT_AGENTS)
    assert PROVIDER_CAPABILITIES["cashera"]["recurring"] is False and CAPABILITIES["paritypay"] == {"sbp", "card"}


@pytest.mark.asyncio
async def test_cashera_transaction_kopecks_and_static_credentials(cashera):
    out = await px.CasheraProvider().create(Decimal("199"), "order-8", "VPN", "https://cabinet/paid", "sbp")
    call = cashera.calls[0]
    assert out == {"id": cashera.tx["uuid"], "url": "https://pay.cashera.cash/t/0b6a", "status": "pending"}, "the scheme is added"
    assert call["url"] == "https://api.cashera.cash/api/v1/integration/transactions" and call["headers"]["X-Api-Key"] == "ck"
    assert call["json"] == {"amount": 19900, "currency": "RUB", "external_id": "order-8", "description": "VPN", "payment_method": "sbp",
                            "success_url": "https://cabinet/paid", "fail_url": "https://cabinet/paid",
                            "callback_url": "https://api.corgi.test/api/webhooks/cashera"}
    provider = px.CasheraProvider()
    assert await provider.verify_succeeded(cashera.tx["uuid"], Decimal("199"), "RUB", "order-8")
    assert not await provider.verify_succeeded(cashera.tx["uuid"], Decimal("199.01"), "RUB", "order-8")
    assert not await provider.verify_succeeded(cashera.tx["uuid"], Decimal("199"), "RUB", "order-other")
    assert not await provider.verify_succeeded("../../x", Decimal("199"), "RUB", "order-8")
    body = json.dumps({"event": "transaction.paid", "transaction": cashera.tx}).encode()
    assert provider.verify_webhook({"X-Api-Key": "ck", "X-Secret": "cs"}, body)["external_id"] == "order-8"
    for bad in ({"X-Api-Key": "ck", "X-Secret": "wrong"}, {"X-Api-Key": "other", "X-Secret": "cs"}, {}):
        with pytest.raises(px.SignatureVerificationError):
            provider.verify_webhook(bad, body)


@pytest.mark.asyncio
async def test_paritypay_invoice_status_and_signature_over_raw_values(parity):
    out = await px.ParityPayProvider().create(Decimal("199"), "order-9", "VPN", "https://cabinet/paid", "card")
    call = parity.calls[0]
    assert out == {"id": "pp-1", "url": "https://pay.paritypay.net/pp-1", "status": "pending"}
    assert call["headers"]["X-ShopId"] == "shop-uuid" and call["headers"]["X-SecretKey"] == "k1"
    assert call["json"]["order_id"] == "order-9" and call["json"]["amount"] == 199.0 and call["json"]["service"] == "card"
    provider = px.ParityPayProvider()
    assert await provider.verify_succeeded("pp-1", Decimal("199"), "RUB", "order-9")
    assert parity.calls[-1]["params"] == {"order_id": "order-9"}
    assert not await provider.verify_succeeded("pp-1", Decimal("299"), "RUB", "order-9")
    raw = '{"id":"pp-1","order_id":"order-9","status":"PAID","amount":199,"commission":7.50,"test":false,"custom_fields":null}'
    sig = _values_sig(raw, b"k2")
    data = provider.verify_webhook({"X-SIGNATURE": sig}, raw.encode())
    assert data["amount"] == "199", "numbers stay as sent: 199, not 199.0"
    with pytest.raises(px.SignatureVerificationError):
        provider.verify_webhook({"X-SIGNATURE": sig}, raw.replace('"amount":199', '"amount":199.0').encode())


def test_aurapay_signature_keeps_numbers_and_booleans_as_sent(monkeypatch):
    monkeypatch.setattr(px.settings, "aurapay_api_key", "ak")
    monkeypatch.setattr(px.settings, "aurapay_shop_id", "shop")
    monkeypatch.setattr(px.settings, "aurapay_secret_key", "s2")
    raw = '{"id":"inv-5","order_id":"order-6","status":"PAID","amount":1200,"fee":12.50,"is_test":true}'
    data = px.AuraPayProvider().verify_webhook({"X-SIGNATURE": _values_sig(raw, b"s2")}, raw.encode())
    assert data["amount"] == "1200" and data["fee"] == "12.50"


@pytest.mark.asyncio
async def test_webhooks_refuse_bad_credentials_and_ignore_unpaid(cashera, parity):
    app = FastAPI()
    app.include_router(px.router)

    async def no_db():
        yield None
    app.dependency_overrides[get_db] = no_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://shop") as c:
        body = json.dumps({"transaction": {**cashera.tx, "status": "failed"}})
        r = await c.post("/api/webhooks/cashera", content=body, headers={"X-Api-Key": "ck", "X-Secret": "nope"})
        assert r.status_code == 401
        r = await c.post("/api/webhooks/cashera", content=body, headers={"X-Api-Key": "ck", "X-Secret": "cs"})
        assert r.status_code == 200 and r.json() == {"status": "ok"}
        raw = '{"id":"pp-1","order_id":"order-9","status":"CANCELED","amount":199}'
        r = await c.post("/api/webhooks/paritypay", content=raw, headers={"X-SIGNATURE": "0" * 64})
        assert r.status_code == 403
        r = await c.post("/api/webhooks/paritypay", content=raw, headers={"X-SIGNATURE": _values_sig(raw, b"k2")})
        assert r.status_code == 200 and r.json() == {"status": True}
