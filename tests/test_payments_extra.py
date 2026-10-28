"""CloudPayments and Lava (payments_extra.py): payment page, signed notifications, the order re-read before delivery,
and their place in the gateway queue and the payment methods."""
import base64
import hashlib
import hmac
import json
from contextlib import asynccontextmanager
from decimal import Decimal
from urllib.parse import quote_plus

import pytest

from app import payments_extra as px
from app.payment_methods import CAPABILITIES
from app.payment_policy import PAYMENT_AGENTS, PROVIDER_CAPABILITIES


class Api:
    def __init__(self, answers):
        self.calls = []
        self.answers = answers

    async def post(self, url, json=None, content=None, headers=None):
        self.calls.append({"url": url, "json": json, "content": content, "headers": headers or {}})
        body = self.answers[next(k for k in self.answers if url.endswith(k))]
        return type("R", (), {"raise_for_status": lambda self: None, "json": lambda self: body})()


@pytest.fixture
def cp(monkeypatch):
    api = Api({"/orders/create": {"Success": True, "Model": {"Id": "f2K8", "Url": "https://orders.cloudpayments.ru/d/f2K8"}},
               "/payments/find": {"Success": True, "Model": {"Status": "Completed", "Amount": 199.0, "Currency": "RUB"}}})

    @asynccontextmanager
    async def client(timeout):
        yield api
    monkeypatch.setattr(px, "_public_client", client)
    monkeypatch.setattr(px.settings, "cloudpayments_public_id", "pk_test")
    monkeypatch.setattr(px.settings, "cloudpayments_api_secret", "api-secret")
    return api


@pytest.fixture
def lava(monkeypatch):
    api = Api({"/business/invoice/create": {"status": "success", "data": {"id": "inv-1", "url": "https://pay.lava.ru/invoice/inv-1"}},
               "/business/invoice/status": {"status": "success", "data": {"status": "success", "amount": 199.0}}})

    @asynccontextmanager
    async def client(timeout):
        yield api
    monkeypatch.setattr(px, "_public_client", client)
    for k, v in {"lava_shop_id": "shop-uuid", "lava_secret_key": "secret-key", "lava_webhook_secret": "add-key",
                 "webhook_base_url": "https://api.corgi.test"}.items():
        monkeypatch.setattr(px.settings, k, v)
    return api


def test_new_gateways_are_in_the_queue_and_the_methods():
    assert {"cloudpayments", "lava"} <= set(PAYMENT_AGENTS)
    assert PROVIDER_CAPABILITIES["lava"]["recurring"] is False and CAPABILITIES["cloudpayments"] == {"sbp", "card"}


@pytest.mark.asyncio
async def test_cloudpayments_page_status_and_signature(cp):
    out = await px.CloudPaymentsProvider().create(Decimal("199"), "order-7", "VPN на месяц", "https://cabinet/paid")
    call = cp.calls[0]
    assert out == {"id": "order-7", "url": "https://orders.cloudpayments.ru/d/f2K8", "status": "pending"}
    assert call["url"] == "https://api.cloudpayments.ru/orders/create" and call["json"]["InvoiceId"] == "order-7" and call["json"]["Amount"] == 199.0
    assert call["headers"]["Authorization"] == "Basic " + base64.b64encode(b"pk_test:api-secret").decode()
    provider = px.CloudPaymentsProvider()
    assert await provider.verify_succeeded("order-7", Decimal("199"), "RUB", "order-7")
    assert not await provider.verify_succeeded("order-7", Decimal("299"), "RUB", "order-7"), "another amount"
    cp.answers["/payments/find"] = {"Success": True, "Model": {"Status": "Declined", "Amount": 199.0, "Currency": "RUB"}}
    assert not await provider.verify_succeeded("order-7", Decimal("199"), "RUB", "order-7")
    body = f"TransactionId=42&Amount=199.00&Currency=RUB&InvoiceId=order-7&Status=Completed&Description={quote_plus('VPN на месяц')}".encode()
    good = base64.b64encode(hmac.new(b"api-secret", body, hashlib.sha256).digest()).decode()
    data = provider.verify_webhook({"Content-HMAC": good}, body)
    assert data["InvoiceId"] == "order-7" and data["Status"] == "Completed"
    from urllib.parse import unquote_plus
    decoded = base64.b64encode(hmac.new(b"api-secret", unquote_plus(body.decode()).encode(), hashlib.sha256).digest()).decode()
    assert provider.verify_webhook({"X-Content-HMAC": decoded}, body)["Status"] == "Completed", "the URL-decoded variant"
    with pytest.raises(px.SignatureVerificationError):
        provider.verify_webhook({"Content-HMAC": "AAAA"}, body)
    with pytest.raises(px.SignatureVerificationError):
        provider.verify_webhook({}, body)


@pytest.mark.asyncio
async def test_lava_signed_request_status_and_both_webhook_signatures(lava):
    out = await px.LavaProvider().create(Decimal("199"), "order-9", "VPN", "https://cabinet/paid?x=1")
    call = lava.calls[0]
    sent = json.loads(call["content"])
    assert out["url"] == "https://pay.lava.ru/invoice/inv-1" and sent["orderId"] == "order-9" and sent["sum"] == 199.0
    assert sent["successUrl"] == "https://cabinet/paid", "Lava refuses a query string in successUrl"
    assert sent["hookUrl"] == "https://api.corgi.test/api/webhooks/lava"
    assert call["headers"]["Signature"] == hmac.new(b"secret-key", call["content"], hashlib.sha256).hexdigest()
    provider = px.LavaProvider()
    assert await provider.verify_succeeded("order-9", Decimal("199"), "RUB", "order-9")
    assert not await provider.verify_succeeded("order-9", Decimal("1"), "RUB", "order-9")
    body = b'{"order_id": "order-9", "status": "success", "amount": 199.0, "invoice_id": "inv-1"}'
    raw_sig = hmac.new(b"add-key", body, hashlib.sha256).hexdigest()
    canonical = json.dumps(json.loads(body), sort_keys=True, separators=(",", ":")).encode()
    sorted_sig = hmac.new(b"add-key", canonical, hashlib.sha256).hexdigest()
    assert provider.verify_webhook({"Authorization": raw_sig}, body)["order_id"] == "order-9"
    assert provider.verify_webhook({"Authorization": sorted_sig}, body)["status"] == "success"
    with pytest.raises(px.SignatureVerificationError):
        provider.verify_webhook({"Authorization": hmac.new(b"other", body, hashlib.sha256).hexdigest()}, body)
