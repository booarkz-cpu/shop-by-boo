"""AuraPay and Anore (payments_extra.py, v28.41): payment page, signed requests and notifications, the payment re-read
before delivery, and their place in the gateway queue and the payment methods."""
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

    def _answer(self, url, body_json):
        key = next(k for k in self.answers if url.endswith(k))
        body = self.answers[key]
        body = body(body_json) if callable(body) else body
        return type("R", (), {"raise_for_status": lambda self: None, "json": lambda self: body})()

    async def post(self, url, json=None, headers=None):
        self.calls.append({"method": "POST", "url": url, "json": json, "headers": headers or {}})
        return self._answer(url, json)

    async def request(self, method, url, content=None, headers=None):
        self.calls.append({"method": method, "url": url, "content": content, "headers": headers or {}})
        return self._answer(url, None)


def _patch(monkeypatch, api, values):
    @asynccontextmanager
    async def client(timeout):
        yield api
    monkeypatch.setattr(px.common, "_public_client", client)
    for k, v in values.items():
        monkeypatch.setattr(px.settings, k, v)


@pytest.fixture
def aura(monkeypatch):
    api = Api({"/invoice/create": {"id": "inv-5", "status": "NEW", "payment_data": {"url": "https://pay.aurapay.tech/inv-5"}},
               "/invoice/status": {"id": "inv-5", "order_id": "order-6", "status": "PAID", "amount": 199.0}})
    _patch(monkeypatch, api, {"aurapay_api_key": "ak", "aurapay_shop_id": "shop-uuid", "aurapay_secret_key": "s2",
                              "webhook_base_url": "https://api.corgi.test"})
    return api


@pytest.fixture
def anore(monkeypatch):
    paid = {"success": True, "id": "an_pay_1", "orderId": "order-7", "amount": "199.00", "rubAmount": "199.00", "currency": "RUB",
            "status": "paid", "paid": True}
    api = Api({"/payments": {"success": True, "id": "an_pay_1", "orderId": "order-7", "paymentUrl": "https://pay.anore.cc/an_pay_1",
                             "amount": "199.00", "currency": "RUB", "status": "new"},
               "/payments/an_pay_1": paid})
    _patch(monkeypatch, api, {"anore_api_key": "an_key", "anore_secret_key": "an-secret", "anore_shop_id": "12",
                              "webhook_base_url": "https://api.corgi.test"})
    api.paid = paid
    return api


def test_new_gateways_are_in_the_queue_and_the_methods():
    assert {"aurapay", "anore"} <= set(PAYMENT_AGENTS)
    assert PROVIDER_CAPABILITIES["anore"]["refunds"] is False and CAPABILITIES["aurapay"] == {"sbp", "card"}


def _aura_sig(data: dict) -> str:
    joined = "".join("" if data[k] is None else str(data[k]) for k in sorted(data))
    return hmac.new(b"s2", joined.encode(), hashlib.sha256).hexdigest()


@pytest.mark.asyncio
async def test_aurapay_invoice_status_and_signature(aura):
    out = await px.AuraPayProvider().create(Decimal("199"), "order-6", "VPN на месяц", "https://cabinet/paid", "sbp")
    call = aura.calls[0]
    assert out == {"id": "inv-5", "url": "https://pay.aurapay.tech/inv-5", "status": "pending"}
    assert call["url"] == "https://app.aurapay.tech/invoice/create"
    assert call["headers"]["X-ApiKey"] == "ak" and call["headers"]["X-ShopId"] == "shop-uuid"
    assert call["json"] == {"amount": 199.0, "order_id": "order-6", "comment": "VPN на месяц", "service": "sbp",
                            "success_url": "https://cabinet/paid", "fail_url": "https://cabinet/paid",
                            "callback_url": "https://api.corgi.test/api/webhooks/aurapay"}
    provider = px.AuraPayProvider()
    assert await provider.verify_succeeded("inv-5", Decimal("199"), "RUB", "order-6")
    assert aura.calls[-1]["json"] == {"order_id": "order-6"}
    assert not await provider.verify_succeeded("inv-5", Decimal("299"), "RUB", "order-6")
    assert not await provider.verify_succeeded("inv-5", Decimal("199"), "RUB", "order-other")
    note = {"id": "inv-5", "order_id": "order-6", "status": "PAID", "amount": 199.0, "custom_fields": None}
    body = json.dumps(note).encode()
    assert provider.verify_webhook({"X-SIGNATURE": _aura_sig(note)}, body)["status"] == "PAID"
    with pytest.raises(px.SignatureVerificationError):
        provider.verify_webhook({"X-SIGNATURE": _aura_sig({**note, "amount": 1.0})}, body)
    with pytest.raises(px.SignatureVerificationError):
        provider.verify_webhook({}, body)


def test_aurapay_signature_is_values_in_key_order_with_null_as_empty(aura):
    data = {"status": "PAID", "amount": 10, "order_id": "o", "custom_fields": None}
    expected = hmac.new(b"s2", b"10o" + b"PAID", hashlib.sha256).hexdigest()  # amount, custom_fields(''), order_id, status
    assert px.AuraPayProvider.signature(data) == expected


@pytest.mark.asyncio
async def test_anore_signed_request_status_and_callback(anore):
    out = await px.AnoreProvider().create(Decimal("199"), "order-7", "VPN", "https://cabinet/paid", "card")
    call = anore.calls[0]
    sent = json.loads(call["content"])
    assert out == {"id": "an_pay_1", "url": "https://pay.anore.cc/an_pay_1", "status": "pending"}
    assert call["url"] == "https://api.anore.cc/v1/payments" and call["headers"]["Authorization"] == "Bearer an_key"
    assert call["headers"]["Anore-Signature"] == hmac.new(b"an-secret", call["content"], hashlib.sha256).hexdigest()
    assert sent == {"amount": 199.0, "currency": "RUB", "description": "VPN", "orderId": "order-7", "shopId": 12, "methods": ["card"],
                    "successurl": "https://cabinet/paid", "failurl": "https://cabinet/paid", "callbackUrl": "https://api.corgi.test/api/webhooks/anore"}
    provider = px.AnoreProvider()
    assert await provider.verify_succeeded("an_pay_1", Decimal("199"), "RUB", "order-7")
    assert anore.calls[-1]["method"] == "GET" and anore.calls[-1]["content"] is None
    assert "Anore-Signature" not in anore.calls[-1]["headers"], "no body, no signature"
    assert not await provider.verify_succeeded("an_pay_1", Decimal("199"), "RUB", "order-other")
    assert not await provider.verify_succeeded("../x", Decimal("199"), "RUB", "order-7"), "the payment id is checked"
    anore.paid["rubAmount"] = "1.00"
    assert not await provider.verify_succeeded("an_pay_1", Decimal("199"), "RUB", "order-7"), "the ruble amount must match too"
    note = {"event": "payment.succeeded", "id": "an_pay_1", "orderId": "order-7", "status": "paid", "amount": "199.00"}
    body = json.dumps(note).encode()
    sig = hmac.new(b"an-secret", body, hashlib.sha256).hexdigest()
    assert provider.verify_webhook({"Anore-Signature": sig, "Anore-Event": "payment.succeeded"}, body)["id"] == "an_pay_1"
    with pytest.raises(px.SignatureVerificationError):
        provider.verify_webhook({"Anore-Signature": sig, "Anore-Event": "payment.expired"}, body)
    with pytest.raises(px.SignatureVerificationError):
        provider.verify_webhook({"Anore-Signature": "0" * 64, "Anore-Event": "payment.succeeded"}, body)


@pytest.mark.asyncio
async def test_anore_refuses_a_page_for_another_order(anore):
    anore.answers["/payments"] = {"success": True, "id": "an_pay_2", "orderId": "order-other", "paymentUrl": "https://pay.anore.cc/x"}
    with pytest.raises(px.PaymentError):
        await px.AnoreProvider().create(Decimal("199"), "order-7", "VPN", "")


@pytest.mark.asyncio
async def test_webhooks_refuse_bad_signatures_and_ignore_unpaid(aura, anore):
    app = FastAPI()
    app.include_router(px.router)

    async def no_db():
        yield None
    app.dependency_overrides[get_db] = no_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://shop") as c:
        note = {"id": "inv-5", "order_id": "order-6", "status": "CANCELED", "amount": 199.0}
        r = await c.post("/api/webhooks/aurapay", content=json.dumps(note), headers={"X-SIGNATURE": "bad"})
        assert r.status_code == 403
        r = await c.post("/api/webhooks/aurapay", content=json.dumps(note), headers={"X-SIGNATURE": _aura_sig(note)})
        assert r.status_code == 200 and r.json() == {"status": True}
        body = json.dumps({"event": "payment.expired", "id": "an_pay_1", "orderId": "order-7", "status": "expired"}).encode()
        sig = hmac.new(b"an-secret", body, hashlib.sha256).hexdigest()
        r = await c.post("/api/webhooks/anore", content=body, headers={"Anore-Signature": "f" * 64, "Anore-Event": "payment.expired"})
        assert r.status_code == 403
        r = await c.post("/api/webhooks/anore", content=body, headers={"Anore-Signature": sig, "Anore-Event": "payment.expired"})
        assert r.status_code == 200 and r.json() == {"success": True}
