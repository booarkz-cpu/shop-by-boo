"""Hosted card checkout with a mock Overpay API and the shop's actual webhook and event journal."""
import base64
import copy
import json
import logging
from contextlib import asynccontextmanager
from decimal import Decimal

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi import FastAPI
from sqlalchemy import select

from app import main as shop
from app.config import settings
from app.db import get_db
from app.gateways import GATEWAYS, OverpayProvider, common
from app.models import PaymentProviderEvent
from app.payments import PaymentError
from test_payment_contract import _order
from test_subscription_commerce import database  # noqa: F401


@pytest.fixture
def merchant(monkeypatch):
    signing_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = signing_key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    for name, value in {"overpay_shop_id": "77", "overpay_secret_key": "test-shop-secret", "overpay_public_key": public.decode(),
                        "overpay_test_mode": True, "app_env": "test", "default_currency": "RUB",
                        "webhook_base_url": "https://shop.example"}.items():
        monkeypatch.setattr(settings, name, value)
    token = "c" * 64
    checkout = {"shop_id": 77, "test": True, "finished": True, "token": token, "transaction_type": "payment", "status": "successful",
                "order": {"tracking_id": "overpay-order-1", "amount": 19900, "currency": "RUB"},
                "gateway_response": {"payment": {"uid": "tx-001", "type": "payment", "status": "successful", "amount": 19900, "currency": "RUB"}}}
    state = {"checkout": checkout, "calls": [], "read_error": False,
             "create": {"token": token, "redirect_url": "https://checkout.overpay.io/v2/checkout?token=" + token}}
    basic = "Basic " + base64.b64encode(b"77:test-shop-secret").decode()

    def answer(req):
        assert req.url.host == "checkout.overpay.io" and req.headers["authorization"] == basic
        state["calls"].append(req)
        if req.method == "POST":
            assert req.url.path == "/ctp/api/checkouts"
            return httpx.Response(200, json={"checkout": state["create"]})
        assert req.method == "GET" and req.url.path == "/ctp/api/checkouts/" + token
        if state["read_error"]:
            return httpx.Response(503)
        return httpx.Response(200, json={"checkout": state["checkout"]})

    @asynccontextmanager
    async def client(_timeout):
        async with httpx.AsyncClient(transport=httpx.MockTransport(answer)) as api:
            yield api
    monkeypatch.setattr(common, "_public_client", client)

    def signed(data):
        raw = json.dumps(data, ensure_ascii=False, indent=1).encode()
        sig = signing_key.sign(raw, padding.PKCS1v15(), hashes.SHA256())
        return raw, {"Authorization": basic, "Content-Signature": base64.b64encode(sig).decode()}
    state["signed"] = signed
    return state


@pytest.mark.asyncio
async def test_checkout_persists_token_and_only_redirects_to_the_hosted_card_page(merchant):
    provider = GATEWAYS["overpay"].cls()
    result = await provider.create(Decimal("199.05"), "merchant-order", "Тариф", "https://shop.example/return", "card")
    assert result == {"id": merchant["checkout"]["token"], "url": merchant["create"]["redirect_url"], "status": "pending"}
    req = merchant["calls"][0]
    payload = json.loads(req.content)["checkout"]
    assert payload["order"] == {"amount": 19905, "currency": "RUB", "description": "Тариф", "tracking_id": "merchant-order"}
    assert payload["settings"]["notification_url"] == "https://shop.example/api/webhooks/overpay"
    assert (payload["test"], payload["attempts"], payload["payment_method"]) == (True, 1, {"types": ["credit_card"]})
    assert "RequestID" not in req.headers  # Overpay documents this for direct transactions only.
    merchant["create"]["redirect_url"] = "https://elsewhere.example/?token=" + merchant["checkout"]["token"]
    with pytest.raises(PaymentError):
        await provider.create(Decimal("199"), "other-order", "Тариф", "https://shop.example")
    with pytest.raises(ValueError):
        await provider.create(Decimal("5.001"), "fraction", "Тариф", "https://shop.example")
    with pytest.raises(PaymentError):
        await provider.create(Decimal("199"), "bad-method", "Тариф", "https://shop.example", "sbp")
    assert len(merchant["calls"]) == 2


@pytest.mark.parametrize(("field", "value"), [("overpay_shop_id", ""), ("overpay_secret_key", ""),
    ("overpay_public_key", ""), ("default_currency", "JPY"), ("webhook_base_url", ""), ("app_env", "production"), ("app_env", "prod")])
def test_unconfigured_or_test_production_shop_stays_out_of_routing(merchant, monkeypatch, field, value):
    monkeypatch.setattr(settings, field, value)
    assert not OverpayProvider.configured()


@pytest.mark.asyncio
@pytest.mark.parametrize(("path", "value"), [
    (("shop_id",), 78), (("token",), "another-token"), (("transaction_type",), "authorization"),
    (("test",), False), (("test",), 1), (("finished",), False), (("status",), "pending"),
    (("order", "tracking_id"), "other-order"), (("order", "amount"), 1), (("order", "currency"), "USD"),
    (("gateway_response", "payment", "currency"), "USD"), (("gateway_response", "payment", "amount"), True),
    (("gateway_response", "payment", "status"), "pending"), (("gateway_response", "payment", "uid"), ""),
])
async def test_reconciliation_requires_the_exact_confirmed_payment(merchant, path, value):
    checkout = merchant["checkout"]
    token = checkout["token"]
    provider = OverpayProvider()
    assert await provider.verify_succeeded(token, Decimal("199"), "RUB", "overpay-order-1")
    leaf = checkout
    for part in path[:-1]:
        leaf = leaf[part]
    leaf[path[-1]] = value
    if path == ("token",):
        with pytest.raises(PaymentError):
            await provider.verify_succeeded(token, Decimal("199"), "RUB", "overpay-order-1")
    else:
        assert not await provider.verify_succeeded(token, Decimal("199"), "RUB", "overpay-order-1")


@pytest.mark.asyncio
@pytest.mark.parametrize(("code", "healthy"), [(404, True), (401, False), (429, False), (502, False)])
async def test_health_probe_uses_a_read_only_request(merchant, monkeypatch, code, healthy):
    def answer(request):
        assert request.method == "GET" and request.url.path.endswith("/" + "0" * 64)
        assert request.headers["authorization"].startswith("Basic ")
        return httpx.Response(code)
    @asynccontextmanager
    async def api(_timeout):
        async with httpx.AsyncClient(transport=httpx.MockTransport(answer)) as client:
            yield client
    monkeypatch.setattr(common, "_public_client", api)
    assert (await OverpayProvider().probe() == "") is healthy


@pytest.mark.asyncio
async def test_status_lookup_keeps_checkout_tokens_out_of_http_logs(merchant, caplog):
    caplog.set_level(logging.INFO, logger="httpx")
    token = merchant["checkout"]["token"]
    merchant["read_error"] = True
    with pytest.raises(PaymentError):
        await OverpayProvider().get_payment_status(token)
    messages = [record.getMessage() for record in caplog.records if record.name == "httpx"]
    assert messages and all(token not in msg for msg in messages)


@pytest.mark.asyncio
async def test_notification_authenticates_raw_bytes_and_shop_credentials_before_lookup(merchant):
    app = FastAPI()
    app.include_router(common.router)
    app.dependency_overrides[get_db] = lambda: None
    expired = {"transaction_type": "payment", "status": "error", "expired": True}
    raw, headers = merchant["signed"](expired)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://shop.test") as client:
        async def post(body, auth):
            return await client.post("/api/webhooks/overpay", content=body, headers=auth)
        assert (await post(raw + b" ", headers)).status_code == 403
        assert (await post(raw, {**headers, "Authorization": "Basic wrong"})).status_code == 403
        assert (await post(raw, {"Authorization": headers["Authorization"]})).status_code == 403
        assert (await post(raw, headers)).status_code == 200
    assert merchant["calls"] == []


@pytest.mark.asyncio
async def test_both_webhook_formats_share_one_settlement_and_recover_an_uncertain_order(database, monkeypatch, merchant):
    if database.bind.dialect.name != "postgresql":
        pytest.skip("production event journal uses PostgreSQL")
    payment = await _order(database, "overpay", 1)
    payment.status, payment.fulfillment_terminal = "creation_unknown", True
    await database.commit()
    pk = payment.id
    completed = []
    async def fulfilled(payment_id, db):
        completed.append(payment_id)
    monkeypatch.setattr(shop, "_confirm_and_fulfill_payment", fulfilled)
    monkeypatch.setattr(shop, "engine", database.bind)
    app = FastAPI()
    app.include_router(common.router)
    app.dependency_overrides[get_db] = lambda: database
    checkout = merchant["checkout"]
    tx = {**checkout["gateway_response"]["payment"], "tracking_id": payment.order_id,
          "payment_method_type": "credit_card", "test": True}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://shop.test") as client:
        async def send(data):
            raw, headers = merchant["signed"](data)
            return await client.post("/api/webhooks/overpay", content=raw, headers=headers)
        assert (await send({"transaction": tx})).status_code == 503  # card UID cannot stand in for a checkout token
        altered = copy.deepcopy(checkout)
        altered["order"]["amount"] = altered["gateway_response"]["payment"]["amount"] = 90
        assert (await send(altered)).status_code == 403
        altered = copy.deepcopy(checkout)
        altered["gateway_response"]["payment"]["uid"] = "another-tx"
        assert (await send(altered)).status_code == 503
        assert (await send({"transaction": {**tx, "test": False}})).status_code == 400
        merchant["read_error"] = True
        assert (await send(checkout)).status_code == 503
        assert payment.provider_payment_id is None and completed == []
        merchant["read_error"] = False
        assert (await send(checkout)).json() == {"ok": True, "result": "paid"}
        assert (await send({"transaction": tx})).json() == {"ok": True, "result": "duplicate"}
    await database.refresh(payment)
    assert payment.provider_payment_id == checkout["token"] and completed == [pk]
    events = (await database.scalars(select(PaymentProviderEvent))).all()
    assert [(event.event_id, event.status, event.attempts) for event in events] == [("paid:tx-001", "processed", 1)]


@pytest.mark.asyncio
async def test_wallet_checkout_and_duplicate_notification_credit_exactly_once(database, monkeypatch, merchant):
    from app.models import FinancialLedger, User
    from test_behaviour_payments_v2 import _checkout_env, checkout

    if database.bind.dialect.name != "postgresql":
        pytest.skip("production event journal uses PostgreSQL")
    await _checkout_env(database, monkeypatch, ["overpay"])
    monkeypatch.setattr(shop, "engine", database.bind)
    payload = {"amount": "199", "provider": "overpay"}
    request = checkout([(b"idempotency-key", b"overpay-wallet")])
    first = await shop.wallet_topup(payload, request, database)
    assert first["status"] == "pending" and first["id"] == merchant["checkout"]["token"]
    assert (await shop.wallet_topup(payload, request, database))["id"] == first["id"]
    created = [req for req in merchant["calls"] if req.method == "POST"]
    assert len(created) == 1
    order = json.loads(created[0].content)["checkout"]["order"]
    merchant["checkout"]["order"] = order
    raw, headers = merchant["signed"](merchant["checkout"])
    app = FastAPI()
    app.include_router(common.router)
    app.dependency_overrides[get_db] = lambda: database
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://shop.test") as client:
        for outcome in ("paid", "duplicate"):
            res = await client.post("/api/webhooks/overpay", content=raw, headers=headers)
            assert res.json() == {"ok": True, "result": outcome}
    after = await shop.wallet_topup(payload, request, database)
    assert after["status"] == "paid" and after["id"] == first["id"]
    user = await database.get(User, 1, populate_existing=True)
    assert user.wallet_balance == Decimal("1199")
    ledger = (await database.execute(select(FinancialLedger.kind, FinancialLedger.amount).order_by(FinancialLedger.id))).all()
    assert ledger == [("payment", Decimal("199")), ("wallet_topup", Decimal("199"))]
    assert [r.method for r in merchant["calls"]] == ["POST", "GET", "GET"]
