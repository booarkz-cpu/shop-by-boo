"""Provider contract checks using documented request and response shapes."""
import hashlib
import hmac
import importlib
import json
import sys
import time
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "backend"))
@pytest.fixture
def pay():
    # Delay Settings initialization until per-test environment fixtures run.
    return importlib.import_module("app.payments")


def test_rollypay_webhook_signature_binds_timestamp_and_raw_body(monkeypatch, pay):
    monkeypatch.setattr(pay.settings, "rollypay_signing_secret", "test-secret")
    body = b'{"payment_id":"pay-1","status":"paid"}'
    stamp = str(int(time.time()))
    signature = hmac.new(b"test-secret", stamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    assert pay.verify_rollypay(body, stamp, signature)
    assert not pay.verify_rollypay(body, str(int(stamp) + 1), signature)
    assert not pay.verify_rollypay(body, stamp, hmac.new(b"test-secret", body, hashlib.sha256).hexdigest())


@pytest.mark.asyncio
async def test_rollypay_create_uses_api_key_nonce_and_documented_checkout(monkeypatch, pay):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"payment_id": "pay-1", "pay_url": "https://pay.example/1", "status": "created"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    provider = pay.RollyPayProvider()
    monkeypatch.setattr(provider, "_get_client", AsyncMock(return_value=client))
    monkeypatch.setattr(pay.settings, "rollypay_api_url", "https://rollypay.example")
    monkeypatch.setattr(pay.settings, "rollypay_api_key", "rpk-test")
    monkeypatch.setattr(pay.settings, "rollypay_test_mode", True)
    try:
        result = await provider.create(Decimal("100.00"), "order-1", "Test order", "https://shop.example/return")
    finally:
        await client.aclose()
    assert result["id"] == "pay-1" and result["url"] == "https://pay.example/1"
    request = requests[0]
    body = json.loads(request.content)
    assert request.url.path == "/api/v1/payments"
    assert request.headers["X-API-Key"] == "rpk-test" and request.headers["X-Nonce"]
    assert "Authorization" not in request.headers
    assert body["amount"] == "100.00" and body["payment_currency"] == "RUB"
    assert body["redirect_url"] == "https://shop.example/return" and body["test"] is True


@pytest.mark.asyncio
async def test_platega_create_uses_documented_transaction_schema(monkeypatch, pay):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"transactionId": "txn-1", "url": "https://pay.example/1", "status": "PENDING"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    provider = pay.PlategaProvider()
    monkeypatch.setattr(provider, "_get_client", AsyncMock(return_value=client))
    monkeypatch.setattr(pay.settings, "platega_api_url", "https://platega.example")
    monkeypatch.setattr(pay.settings, "platega_merchant_id", "merchant")
    monkeypatch.setattr(pay.settings, "platega_secret", "secret")
    try:
        result = await provider.create(Decimal("100.00"), "order-1", "Test order", "https://shop.example/return")
    finally:
        await client.aclose()
    assert result["id"] == "txn-1" and result["url"] == "https://pay.example/1"
    request = requests[0]
    body = json.loads(request.content)
    assert request.url.path == "/v2/transaction/process"
    assert body["paymentDetails"] == {"amount": 100.0, "currency": "RUB"}
    assert body["payload"] == "order-1" and body["return"] == "https://shop.example/return"
    assert request.headers["X-MerchantId"] == "merchant"


@pytest.mark.asyncio
@pytest.mark.parametrize("provider,response", [
    ("platega", {"status": "CONFIRMED", "paymentDetails": {"amount": 100, "currency": "RUB"}, "payload": "order-1"}),
    ("rollypay", {"status": "paid", "amount": "100.00", "payment_currency": "RUB", "order_id": "order-1"}),
])
async def test_staging_read_matches_provider_amount_currency_and_order(monkeypatch, provider, response, pay):
    main = importlib.import_module("app.main")
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=response)

    monkeypatch.setattr(main, "validate_public_url", lambda value, **_: value)
    monkeypatch.setattr(main, "_pinned_public_http_client", lambda _: httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    result = await pay.staging_read_payment(provider, {"api_url": "https://pay.example", "api_key": "test"}, "pay-1", Decimal("100"), "order-1")
    assert result["paid"] is True
    if provider == "rollypay":
        assert requests[0].headers["X-API-Key"] == "test" and requests[0].headers["X-Nonce"]
    response["payment_currency" if provider == "rollypay" else "paymentDetails"] = "USD" if provider == "rollypay" else {"amount": 100, "currency": "USD"}
    assert not (await pay.staging_read_payment(provider, {"api_url": "https://pay.example", "api_key": "test"}, "pay-1", Decimal("100"), "order-1"))["paid"]


def test_production_disallows_rollypay_sandbox_flag():
    from app.runtime_security import validate_configuration
    from app.config import settings
    config = settings.model_copy(update={"app_env": "production", "rollypay_test_mode": True})
    with pytest.raises(ValueError, match="ROLLYPAY_TEST_MODE"):
        validate_configuration(config)
