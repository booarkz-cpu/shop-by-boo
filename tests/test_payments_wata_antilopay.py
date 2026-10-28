"""WATA and Antilopay (payments_extra.py, v28.40): payment page, RSA-signed requests and notifications, the payment
re-read before delivery, and their place in the gateway queue and the payment methods."""
import base64
import json
import time
from contextlib import asynccontextmanager
from decimal import Decimal

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi import FastAPI

from app import payments_extra as px
from app.db import get_db
from app.payment_methods import CAPABILITIES
from app.payment_policy import PAYMENT_AGENTS, PROVIDER_CAPABILITIES


def _keys():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem_pub = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    der_pub = base64.b64encode(key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).decode()
    der_priv = base64.b64encode(key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())).decode()
    return key, pem_pub, der_pub, der_priv


def _sign(key, body: bytes, sha512: bool) -> str:
    return base64.b64encode(key.sign(body, padding.PKCS1v15(), hashes.SHA512() if sha512 else hashes.SHA256())).decode()


class Api:
    def __init__(self, answers):
        self.calls = []
        self.answers = answers

    def _answer(self, url):
        body = self.answers[next(k for k in self.answers if url.endswith(k))]
        return type("R", (), {"raise_for_status": lambda self: None, "json": lambda self: body})()

    async def request(self, method, url, headers=None, json=None, params=None):
        self.calls.append({"method": method, "url": url, "json": json, "params": params, "headers": headers or {}})
        return self._answer(url)

    async def post(self, url, content=None, headers=None, json=None):
        self.calls.append({"method": "POST", "url": url, "content": content, "headers": headers or {}})
        return self._answer(url)


def _patch(monkeypatch, api, values):
    @asynccontextmanager
    async def client(timeout):
        yield api
    monkeypatch.setattr(px, "_public_client", client)
    for k, v in values.items():
        monkeypatch.setattr(px.settings, k, v)


@pytest.fixture
def wata(monkeypatch):
    key, pem_pub, _, _ = _keys()
    api = Api({"/links": {"id": "L-1", "url": "https://payment.wata.pro/L-1"},
               "/public-key": {"value": pem_pub},
               "/transactions": {"items": [{"id": "T-1", "status": "Paid", "amount": 199.0, "currency": "RUB", "orderId": "order-3"}]}})
    _patch(monkeypatch, api, {"wata_access_token": "wata-token"})
    monkeypatch.setattr(px.WataProvider, "_key", None)
    api.key, api.pem = key, pem_pub
    return api


@pytest.fixture
def anti(monkeypatch):
    shop_key, _, _, shop_priv = _keys()
    apay_key, _, apay_pub, _ = _keys()
    api = Api({"/payment/create": {"code": 0, "payment_id": "AP-9", "payment_url": "https://pay.antilopay.com/AP-9"},
               "/payment/check": {"code": 0, "status": "SUCCESS", "order_id": "order-4", "amount": 190.0, "original_amount": 199.0}})
    _patch(monkeypatch, api, {"antilopay_project_id": "proj-1", "antilopay_secret_id": "sid-1", "antilopay_private_key": shop_priv,
                              "antilopay_public_key": apay_pub, "antilopay_customer_email": ""})
    api.shop_key, api.apay_key = shop_key, apay_key
    return api


def test_new_gateways_are_in_the_queue_and_the_methods():
    assert {"wata", "antilopay"} <= set(PAYMENT_AGENTS)
    assert PROVIDER_CAPABILITIES["wata"]["recurring"] is False and CAPABILITIES["antilopay"] == {"sbp", "card"}


@pytest.mark.asyncio
async def test_wata_link_transactions_and_rsa_signature(wata):
    out = await px.WataProvider().create(Decimal("199"), "order-3", "VPN на месяц", "https://cabinet/paid")
    call = wata.calls[0]
    assert out == {"id": "L-1", "url": "https://payment.wata.pro/L-1", "status": "pending"}
    assert call["url"] == "https://api.wata.pro/api/h2h/links" and call["headers"]["Authorization"] == "Bearer wata-token"
    assert call["json"]["orderId"] == "order-3" and call["json"]["amount"] == 199.0 and call["json"]["type"] == "OneTime"
    provider = px.WataProvider()
    assert await provider.verify_succeeded("L-1", Decimal("199"), "RUB", "order-3")
    assert wata.calls[-1]["params"]["orderId"] == "order-3" and wata.calls[-1]["params"]["statuses"] == "Paid"
    assert not await provider.verify_succeeded("L-1", Decimal("299"), "RUB", "order-3"), "another amount"
    assert not await provider.verify_succeeded("L-1", Decimal("199"), "RUB", None), "the order id is required"
    body = json.dumps({"transactionStatus": "Paid", "orderId": "order-3", "amount": 199.0, "transactionId": "T-1"}).encode()
    data = await provider.verify_webhook_async({"X-Signature": _sign(wata.key, body, True)}, body)
    assert data["orderId"] == "order-3"
    assert sum(1 for c in wata.calls if c["url"].endswith("/public-key")) == 1
    await provider.verify_webhook_async({"X-Signature": _sign(wata.key, body, True)}, body)
    assert sum(1 for c in wata.calls if c["url"].endswith("/public-key")) == 1, "the public key is cached"
    assert "Authorization" not in next(c for c in wata.calls if c["url"].endswith("/public-key"))["headers"]
    with pytest.raises(px.SignatureVerificationError):
        await provider.verify_webhook_async({"X-Signature": _sign(wata.key, body, False)}, body)  # SHA-256 is not WATA's
    with pytest.raises(px.SignatureVerificationError):
        await provider.verify_webhook_async({}, body)


@pytest.mark.asyncio
async def test_antilopay_signed_request_check_and_callback(anti):
    out = await px.AntilopayProvider().create(Decimal("199"), "order-4", "VPN", "https://cabinet/paid", "sbp")
    call = anti.calls[0]
    sent = json.loads(call["content"])
    assert out == {"id": "AP-9", "url": "https://pay.antilopay.com/AP-9", "status": "pending"}
    assert call["url"] == "https://lk.antilopay.com/api/v2/payment/create" and call["headers"]["X-Apay-Secret-Id"] == "sid-1"
    assert sent["project_identificator"] == "proj-1" and sent["order_id"] == "order-4" and sent["amount"] == 199.0
    assert sent["prefer_methods"] == ["SBP"] and sent["customer"]["email"]
    anti.shop_key.public_key().verify(base64.b64decode(call["headers"]["X-Apay-Sign"]), call["content"], padding.PKCS1v15(), hashes.SHA256())
    provider = px.AntilopayProvider()
    assert await provider.verify_succeeded("AP-9", Decimal("199"), "RUB", "order-4"), "original_amount, not the net amount"
    assert json.loads(anti.calls[-1]["content"]) == {"project_identificator": "proj-1", "order_id": "order-4"}
    assert not await provider.verify_succeeded("AP-9", Decimal("190"), "RUB", "order-4")
    assert not await provider.verify_succeeded("AP-9", Decimal("199"), "RUB", "order-other")
    body = json.dumps({"type": "payment", "order_id": "order-4", "status": "SUCCESS", "payment_id": "AP-9", "original_amount": 199.0}).encode()
    assert provider.verify_webhook({"X-Apay-Callback": _sign(anti.apay_key, body, False)}, body)["payment_id"] == "AP-9"
    with pytest.raises(px.SignatureVerificationError):
        provider.verify_webhook({"X-Apay-Callback": _sign(anti.shop_key, body, False)}, body)  # signed by another key
    with pytest.raises(px.SignatureVerificationError):
        provider.verify_webhook({"X-Apay-Callback": "not-base64!"}, body)


def test_rsa_keys_as_pem_with_escaped_newlines():
    key, pem_pub, der_pub, _ = _keys()
    body = b'{"a":1}'
    sig = _sign(key, body, True)
    assert px._rsa_verify(pem_pub.replace("\n", "\\n"), body, sig, sha512=True)
    assert px._rsa_verify(der_pub, body, sig, sha512=True)


@pytest.mark.asyncio
async def test_webhooks_refuse_bad_signatures_and_ignore_unpaid(wata, anti, monkeypatch):
    monkeypatch.setattr(px.WataProvider, "_key", (time.monotonic(), wata.pem))  # the anti fixture replaced the HTTP client
    app = FastAPI()
    app.include_router(px.router)

    async def no_db():
        yield None
    app.dependency_overrides[get_db] = no_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://shop") as c:
        body = json.dumps({"transactionStatus": "Declined", "orderId": "order-3"}).encode()
        r = await c.post("/api/webhooks/wata", content=body, headers={"X-Signature": _sign(anti.shop_key, body, True)})
        assert r.status_code == 403
        r = await c.post("/api/webhooks/wata", content=body, headers={"X-Signature": _sign(wata.key, body, True)})
        assert r.status_code == 200 and r.json() == {"status": "ok"}
        body = json.dumps({"type": "payment", "order_id": "order-4", "status": "FAIL"}).encode()
        r = await c.post("/api/webhooks/antilopay", content=body, headers={"X-Apay-Callback": _sign(wata.key, body, False)})
        assert r.status_code == 403
        r = await c.post("/api/webhooks/antilopay", content=body, headers={"X-Apay-Callback": _sign(anti.apay_key, body, False)})
        assert r.status_code == 200 and r.json() == {"ok": True}
