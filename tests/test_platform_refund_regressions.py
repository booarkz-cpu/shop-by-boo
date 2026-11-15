"""Provider refunds and delayed webhooks must preserve payment state."""
import importlib
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "services" / "backend"))
    shop = importlib.import_module("app.main")
    monkeypatch.setattr(shop, "register_provider_event", AsyncMock(return_value=True))
    monkeypatch.setattr(shop, "finish_provider_event", AsyncMock())
    return shop, importlib.import_module("app.payment_platform")


@pytest.mark.asyncio
async def test_stripe_refund_resolves_checkout_session_to_payment_intent(modules, monkeypatch):
    _, platform = modules
    monkeypatch.setattr(platform.settings, "stripe_secret_key", "test-secret")
    calls = []

    def respond(request):
        calls.append(request)
        if request.method == "GET":
            assert request.url.path.endswith("/v1/checkout/sessions/cs_order")
            return httpx.Response(200, json={"payment_status": "paid", "payment_intent": "pi_paid"})
        assert request.url.path.endswith("/v1/refunds")
        assert "payment_intent=pi_paid" in request.content.decode()
        assert "amount=1099" in request.content.decode()
        assert request.headers.get("idempotency-key", "").startswith("refund-")
        return httpx.Response(200, json={"id": "re_1", "status": "succeeded"})

    monkeypatch.setattr(platform, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    result = await platform.StripePlatform().refund("cs_order", Decimal("10.99"), "USD")
    assert result["id"] == "re_1"
    assert [request.method for request in calls] == ["GET", "POST"]


@pytest.mark.asyncio
async def test_stripe_refund_rejects_unpaid_checkout(modules, monkeypatch):
    _, platform = modules
    monkeypatch.setattr(platform.settings, "stripe_secret_key", "test-secret")
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, json={"payment_status": "unpaid", "payment_intent": "pi_unpaid"})

    monkeypatch.setattr(platform, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    with pytest.raises(platform.PlatformProviderError):
        await platform.StripePlatform().refund("cs_unpaid", Decimal("5"), "USD")
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["stripe", "paypal"])
async def test_late_provider_webhook_cannot_reactivate_refund(modules, monkeypatch, provider):
    shop, _ = modules
    payment = SimpleNamespace(id=4, amount=Decimal("10"), currency="USD", order_id="local-order", provider_payment_id="cs_1" if provider == "stripe" else "paypal-1", status="pending")
    db = SimpleNamespace(execute=AsyncMock(return_value=Mock(scalar_one_or_none=lambda: payment)), commit=AsyncMock())
    confirm = AsyncMock(return_value={"ignored": True})  # Refund wins while verification is in flight.
    monkeypatch.setattr(shop, "_confirm_and_fulfill_payment", confirm)
    metric = AsyncMock()
    monkeypatch.setattr(shop, "_record_provider_metric", metric)
    if provider == "stripe":
        event = {"id": "evt-test", "type": "checkout.session.completed", "data": {"object": {"metadata": {"order_id": "local-order"}, "payment_status": "paid", "amount_total": 1000, "currency": "usd"}}}
        monkeypatch.setattr(shop.StripePlatform, "verify_webhook", lambda self, body, sig: event)
        monkeypatch.setattr(shop.StripePlatform, "verify_succeeded", AsyncMock(return_value=True))
        handler = shop.stripe_webhook
    else:
        event = {"id": "evt-test", "event_type": "CHECKOUT.ORDER.COMPLETED", "resource": {"purchase_units": [{"reference_id": "local-order", "amount": {"currency_code": "USD", "value": "10.00"}}]}}
        monkeypatch.setattr(shop.PayPalPlatform, "verify_webhook", AsyncMock(return_value=event))
        monkeypatch.setattr(shop.PayPalPlatform, "verify_succeeded", AsyncMock(return_value=True))
        handler = shop.paypal_webhook
    request = SimpleNamespace(body=AsyncMock(return_value=b"{}"), headers={})
    assert (await handler(request, db))["received"] is True
    confirm.assert_awaited_once_with(payment.id, db)
    assert payment.status == "pending"
    assert db.commit.await_count == 2  # Event claim and completion; no payment mutation.
    metric.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("payment_status,should_capture", [("pending", True), ("paid", False), ("refunded", False)])
async def test_paypal_approval_only_captures_pending_local_order(modules, monkeypatch, payment_status, should_capture):
    shop, _ = modules
    event = {"id": "evt-test", "event_type": "CHECKOUT.ORDER.APPROVED", "resource": {"id": "paypal-order"}}
    monkeypatch.setattr(shop.PayPalPlatform, "verify_webhook", AsyncMock(return_value=event))
    capture = AsyncMock()
    monkeypatch.setattr(shop.PayPalPlatform, "capture", capture)
    pending = SimpleNamespace(status=payment_status) if should_capture else None
    db = SimpleNamespace(execute=AsyncMock(return_value=Mock(scalar_one_or_none=lambda: pending)), commit=AsyncMock(), rollback=AsyncMock())
    request = SimpleNamespace(body=AsyncMock(return_value=b"{}"), headers={})
    assert (await shop.paypal_webhook(request, db))["received"] is True
    assert capture.await_count == int(should_capture)


@pytest.mark.asyncio
async def test_paypal_refund_uses_stable_request_id_and_can_be_reconciled(modules, monkeypatch):
    _, platform = modules
    monkeypatch.setattr(platform.PayPalPlatform, "_token", AsyncMock(return_value="token"))
    sent = []

    def respond(request):
        sent.append(request)
        if request.url.path.endswith("/v2/checkout/orders/paypal-order"):
            return httpx.Response(200, json={"purchase_units": [{"payments": {"captures": [{"id": "capture-1"}]}}]})
        if request.method == "POST":
            assert request.url.path.endswith("/v2/payments/captures/capture-1/refund")
            return httpx.Response(200, json={"id": "refund-1", "status": "PENDING"})
        return httpx.Response(200, json={"id": "refund-1", "status": "COMPLETED"})

    monkeypatch.setattr(platform, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    provider = platform.PayPalPlatform()
    assert (await provider.refund("paypal-order", Decimal("10"), "USD"))["status"] == "PENDING"
    assert await provider.get_refund_status("refund-1") == "completed"
    assert sent[1].headers.get("paypal-request-id", "").startswith("refund-")
    assert sent[2].url.path.endswith("/v2/payments/refunds/refund-1")


@pytest.mark.asyncio
@pytest.mark.parametrize("status,expected", [("paid", "paid"), ("refunded", "refunded"), ("pending", "failed")])
async def test_late_paypal_denial_does_not_overwrite_final_payment(modules, monkeypatch, status, expected):
    shop, _ = modules
    event = {"id": "evt-test", "event_type": "PAYMENT.CAPTURE.DENIED", "resource": {"supplementary_data": {"related_ids": {"order_id": "paypal-order"}}}}
    monkeypatch.setattr(shop.PayPalPlatform, "verify_webhook", AsyncMock(return_value=event))
    payment = SimpleNamespace(status=status)
    db = SimpleNamespace(execute=AsyncMock(return_value=Mock(scalar_one_or_none=lambda: payment)), commit=AsyncMock())
    request = SimpleNamespace(body=AsyncMock(return_value=b"{}"), headers={})
    await shop.paypal_webhook(request, db)
    assert payment.status == expected
    assert db.commit.await_count == 2 + int(status == "pending")
