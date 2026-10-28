"""Pal24 and Mulen Pay (payments_extra.py, v28.39): payment page, signed notifications, the payment re-read before
delivery, and their place in the gateway queue and the payment methods."""
import hashlib
import json
from contextlib import asynccontextmanager
from decimal import Decimal
from urllib.parse import urlencode

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

    async def request(self, method, url, headers=None, json=None, params=None):
        self.calls.append({"method": method, "url": url, "json": json, "params": params, "headers": headers or {}})
        body = self.answers[next(k for k in self.answers if k in url)]
        return type("R", (), {"raise_for_status": lambda self: None, "json": lambda self: body})()


def _patch(monkeypatch, api, values):
    @asynccontextmanager
    async def client(timeout):
        yield api
    monkeypatch.setattr(px, "_public_client", client)
    for k, v in values.items():
        monkeypatch.setattr(px.settings, k, v)


@pytest.fixture
def pal(monkeypatch):
    api = Api({"/bill/create": {"success": True, "bill_id": "B-77", "link_url": "https://pal24.pro/l/B-77", "link_page_url": "https://pal24.pro/p/B-77"},
               "/bill/status": {"success": True, "id": "B-77", "status": "SUCCESS", "amount": "199.00", "currency_in": "RUB", "order_id": "order-5"}})
    _patch(monkeypatch, api, {"pal24_api_token": "pal-token", "pal24_shop_id": "shop-1", "pal24_signature_token": ""})
    return api


@pytest.fixture
def mulen(monkeypatch):
    api = Api({"/v2/payments/": {"success": True, "payment": {"id": 314, "status": 3, "amount": "199.00", "uuid": "order-8"}},
               "/v2/payments": {"success": True, "id": 314, "paymentUrl": "https://mulenpay.ru/payment/314"}})
    _patch(monkeypatch, api, {"mulenpay_api_key": "mp-key", "mulenpay_secret_key": "mp-secret", "mulenpay_shop_id": "55"})
    return api


def test_new_gateways_are_in_the_queue_and_the_methods():
    assert {"pal24", "mulenpay"} <= set(PAYMENT_AGENTS)
    assert PROVIDER_CAPABILITIES["pal24"]["refunds"] is False and CAPABILITIES["mulenpay"] == {"sbp", "card"}


@pytest.mark.asyncio
async def test_pal24_bill_status_and_signature(pal):
    out = await px.Pal24Provider().create(Decimal("199"), "order-5", "VPN на месяц", "https://cabinet/paid", "sbp")
    call = pal.calls[0]
    assert out == {"id": "B-77", "url": "https://pal24.pro/p/B-77", "status": "pending"}
    assert call["url"] == "https://pal24.pro/api/v1/bill/create" and call["headers"]["Authorization"] == "Bearer pal-token"
    assert call["json"] == {"amount": "199.00", "shop_id": "shop-1", "order_id": "order-5", "currency_in": "RUB", "type": "normal",
                            "description": "VPN на месяц", "payment_method": "SBP", "success_url": "https://cabinet/paid", "fail_url": "https://cabinet/paid"}
    provider = px.Pal24Provider()
    assert await provider.verify_succeeded("B-77", Decimal("199"), "RUB", "order-5")
    assert pal.calls[-1]["params"] == {"id": "B-77"}
    assert not await provider.verify_succeeded("B-77", Decimal("299"), "RUB", "order-5"), "less than the price"
    assert not await provider.verify_succeeded("B-77", Decimal("199"), "RUB", "order-other"), "another order"
    pal.answers["/bill/status"] = {"success": True, "status": "FAIL", "amount": "199.00"}
    assert not await provider.verify_succeeded("B-77", Decimal("199"), "RUB", "order-5")
    sig = hashlib.md5(b"199.00:order-5:pal-token").hexdigest().upper()
    form = urlencode({"InvId": "order-5", "OutSum": "199.00", "Status": "SUCCESS", "TrsId": "T1", "SignatureValue": sig}).encode()
    assert provider.verify_webhook({}, form)["InvId"] == "order-5"
    assert provider.verify_webhook({}, json.dumps({"InvId": "order-5", "OutSum": "199.00", "SignatureValue": sig.lower()}).encode())["OutSum"] == "199.00"
    with pytest.raises(px.SignatureVerificationError):
        provider.verify_webhook({}, form.replace(b"199.00", b"1.00"))


@pytest.mark.asyncio
async def test_pal24_signature_token_wins(pal, monkeypatch):
    monkeypatch.setattr(px.settings, "pal24_signature_token", "sig-token")
    assert px.Pal24Provider.signature("10.00", "o") == hashlib.md5(b"10.00:o:sig-token").hexdigest().upper()


@pytest.mark.asyncio
async def test_mulenpay_payment_status_and_signatures(mulen):
    out = await px.MulenPayProvider().create(Decimal("199"), "order-8", "VPN", "https://cabinet/paid")
    call = mulen.calls[0]
    assert out == {"id": "314", "url": "https://mulenpay.ru/payment/314", "status": "pending"}
    assert call["url"] == "https://mulenpay.ru/api/v2/payments" and call["headers"]["Authorization"] == "Bearer mp-key"
    body = call["json"]
    assert body["uuid"] == "order-8" and body["amount"] == "199.00" and body["shopId"] == 55 and body["currency"] == "rub"
    assert body["sign"] == hashlib.sha1(b"rub199.0055mp-secret").hexdigest()
    assert body["items"][0]["price"] == 199.0 and body["items"][0]["quantity"] == 1
    provider = px.MulenPayProvider()
    assert await provider.verify_succeeded("314", Decimal("199"), "RUB", "order-8")
    assert mulen.calls[-1]["url"] == "https://mulenpay.ru/api/v2/payments/314"
    assert not await provider.verify_succeeded("order-8", Decimal("199"), "RUB", "order-8"), "only the numeric payment id is re-read"
    assert not await provider.verify_succeeded("314", Decimal("199"), "RUB", "order-other")
    mulen.answers["/v2/payments/"] = {"success": True, "payment": {"id": 314, "status": 2, "amount": "199.00", "uuid": "order-8"}}
    assert not await provider.verify_succeeded("314", Decimal("199"), "RUB", "order-8"), "cancelled"
    note = {"id": 314, "uuid": "order-8", "amount": "199.00", "payment_status": "success"}
    note["sign"] = hashlib.sha1(("".join(str(v) for v in note.values()) + "mp-secret").encode()).hexdigest()
    assert provider.verify_webhook({}, json.dumps(note).encode())["uuid"] == "order-8"
    unsigned = {k: v for k, v in note.items() if k != "sign"}
    assert provider.verify_webhook({}, json.dumps(unsigned).encode())["id"] == 314, "allowed: the payment is re-read anyway"
    with pytest.raises(px.SignatureVerificationError):
        provider.verify_webhook({}, json.dumps({**note, "sign": "0" * 40}).encode())


@pytest.mark.asyncio
async def test_webhooks_refuse_bad_signatures_and_ignore_unpaid(pal, mulen):
    app = FastAPI()
    app.include_router(px.router)

    async def no_db():
        yield None
    app.dependency_overrides[get_db] = no_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://shop") as c:
        r = await c.post("/api/webhooks/pal24", data={"InvId": "order-5", "OutSum": "199.00", "Status": "SUCCESS", "SignatureValue": "BAD"})
        assert r.status_code == 403
        sig = hashlib.md5(b"199.00:order-5:pal-token").hexdigest().upper()
        r = await c.post("/api/webhooks/pal24", data={"InvId": "order-5", "OutSum": "199.00", "Status": "FAIL", "SignatureValue": sig})
        assert r.status_code == 200 and r.json() == {"status": "ok"}
        r = await c.post("/api/webhooks/mulenpay", json={"uuid": "order-8", "payment_status": "success", "sign": "bad"})
        assert r.status_code == 403
        r = await c.post("/api/webhooks/mulenpay", json={"uuid": "order-8", "payment_status": "cancel"})
        assert r.status_code == 200 and r.json() == {"ok": True}
