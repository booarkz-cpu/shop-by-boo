"""Stage 19, C1 (behaviour instead of source text), money first: YooKassa against a fake YooKassa API.

Replaces the source-text checks of tests/test_critical_audit_v2005.py and part of test_v15_production.py: what the
shop sends and how it reads the answers, not how the code is spelled."""
import json
from datetime import datetime, timezone
from decimal import Decimal

import httpx
import pytest

from app import payments
from app.config import settings


@pytest.fixture
def yookassa(monkeypatch):
    calls, pages = [], {}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        path = request.url.path
        if request.method == "POST" and path == "/v3/payments":
            body = json.loads(request.content)
            return httpx.Response(200, json={"id": "yk-new", "status": "pending", "metadata": body["metadata"]})
        if request.method == "GET" and path == "/v3/payments":
            return httpx.Response(200, json=pages.get(request.url.params.get("cursor") or "", {"items": []}))
        if request.method == "POST" and path == "/v3/refunds":
            return httpx.Response(200, json={"id": "rf-1", "status": "pending"})
        return httpx.Response(404, json={})

    monkeypatch.setattr(payments, "_public_client", lambda timeout: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(settings, "yookassa_api_url", "https://api.yookassa.test")
    monkeypatch.setattr(settings, "yookassa_shop_id", "shop")
    monkeypatch.setattr(settings, "yookassa_secret_key", "secret")
    return calls, pages


@pytest.mark.asyncio
async def test_a_repeated_create_reuses_the_order_as_the_idempotence_key(yookassa):
    calls, _ = yookassa
    provider = payments.YooKassaProvider()
    for _ in range(2):  # a lost answer: the shop asks again for the same order
        await provider.create_payment(100.0, "RUB", "Lucy Mini", {"order_id": "o-42", "email": "a@example.com"})
    keys = [c.headers["Idempotence-Key"] for c in calls]
    assert keys == ["o-42", "o-42"], "YooKassa returns the same payment, no second charge"
    body = json.loads(calls[0].content)
    assert body["amount"] == {"value": "100.00", "currency": "RUB"} and body["metadata"]["order_id"] == "o-42"
    assert body["receipt"]["customer"]["email"] == "a@example.com"
    # Without an order id each request is a new payment (a random key).
    await provider.create_payment(10.0, "RUB", "x", {})
    await provider.create_payment(10.0, "RUB", "x", {})
    assert calls[2].headers["Idempotence-Key"] != calls[3].headers["Idempotence-Key"]


@pytest.mark.asyncio
async def test_lookup_by_order_never_creates_and_follows_the_pages(yookassa):
    calls, pages = yookassa
    pages[""] = {"items": [{"id": "yk-1", "metadata": {"order_id": "other"}}], "next_cursor": "c2"}
    pages["c2"] = {"items": [{"id": "yk-2", "metadata": {"order_id": "o-7"}}]}
    found = await payments.YooKassaProvider().find_by_order_id("o-7", datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc))
    assert found["id"] == "yk-2"
    assert all(c.method == "GET" for c in calls), "the lookup never opens a payment"
    assert calls[0].url.params["created_at.gte"] == "2026-11-05T12:00:00.000Z"
    assert calls[1].url.params["cursor"] == "c2"
    calls.clear(); pages.clear()
    assert await payments.YooKassaProvider().find_by_order_id("o-8") is None
    assert "created_at.gte" not in calls[0].url.params


@pytest.mark.asyncio
async def test_lookup_stops_after_five_pages(yookassa):
    calls, pages = yookassa
    for i in range(10):
        pages["" if i == 0 else f"c{i}"] = {"items": [], "next_cursor": f"c{i + 1}"}
    assert await payments.YooKassaProvider().find_by_order_id("o-1") is None
    assert len(calls) == 5


@pytest.mark.asyncio
async def test_refund_has_its_own_idempotence_key_and_exact_amount(yookassa):
    calls, _ = yookassa
    out = await payments.YooKassaProvider().refund("yk-9", Decimal("99.9"), "RUB", "x" * 400)
    assert out == {"id": "rf-1", "status": "pending"}
    assert calls[0].headers["Idempotence-Key"] == "refund-yk-9"
    body = json.loads(calls[0].content)
    assert body["amount"] == {"value": "99.90", "currency": "RUB"} and len(body["description"]) == 250


def _gateway(monkeypatch, answer: dict, status: int = 200):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json=answer)
    monkeypatch.setattr(payments, "_public_client", lambda timeout: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    return seen


@pytest.mark.asyncio
@pytest.mark.parametrize("paid, amount, currency, order, expected", [
    ("CONFIRMED", "100.00", "RUB", "o-1", True),
    ("PENDING", "100.00", "RUB", "o-1", False),       # not paid yet
    ("CONFIRMED", "99.00", "RUB", "o-1", False),      # another amount
    ("CONFIRMED", "100.00", "USD", "o-1", False),     # another currency
    ("CONFIRMED", "100.00", "", "o-1", False),        # no currency cannot confirm money
    ("CONFIRMED", "100.00", "RUB", "o-2", False),     # someone else's order
])
async def test_platega_confirms_only_the_exact_paid_order(monkeypatch, paid, amount, currency, order, expected):
    monkeypatch.setattr(settings, "platega_api_url", "https://platega.test")
    monkeypatch.setattr(settings, "platega_merchant_id", "m-1")
    monkeypatch.setattr(settings, "platega_secret", "s-1")
    seen = _gateway(monkeypatch, {"status": paid, "payload": order, "paymentDetails": {"amount": amount, "currency": currency}})
    assert await payments.PlategaProvider().verify_succeeded("txn-9", Decimal("100"), "RUB", "o-1") is expected
    assert seen[0].url.path == "/transaction/txn-9" and seen[0].headers["X-MerchantId"] == "m-1" and seen[0].headers["X-Secret"] == "s-1"


@pytest.mark.asyncio
@pytest.mark.parametrize("paid, amount, currency, order, expected", [
    ("paid", "100", "RUB", "o-1", True),
    ("pending", "100", "RUB", "o-1", False),
    ("paid", "100.01", "RUB", "o-1", False),
    ("paid", "100", "EUR", "o-1", False),
    ("paid", "100", "RUB", "o-3", False),
])
async def test_rollypay_confirms_only_the_exact_paid_order(monkeypatch, paid, amount, currency, order, expected):
    monkeypatch.setattr(settings, "rollypay_api_url", "https://rollypay.test")
    monkeypatch.setattr(settings, "rollypay_api_key", "rpk")
    seen = _gateway(monkeypatch, {"status": paid, "amount": amount, "payment_currency": currency, "order_id": order})
    assert await payments.RollyPayProvider().verify_succeeded("p-5", Decimal("100"), "RUB", "o-1") is expected
    assert seen[0].url.path == "/api/v1/payments/p-5" and seen[0].headers["X-API-Key"] == "rpk" and seen[0].headers["X-Nonce"]


@pytest.mark.asyncio
async def test_a_gateway_error_never_confirms(monkeypatch):
    monkeypatch.setattr(settings, "platega_api_url", "https://platega.test")
    _gateway(monkeypatch, {"status": "CONFIRMED"}, status=500)
    assert await payments.PlategaProvider().verify_succeeded("t", Decimal("1"), "RUB") is False
    monkeypatch.setattr(settings, "rollypay_api_url", "https://rollypay.test")
    _gateway(monkeypatch, {"status": "paid"}, status=404)
    assert await payments.RollyPayProvider().verify_succeeded("t", Decimal("1"), "RUB") is False
