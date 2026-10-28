"""More payment gateways: CloudPayments and Lava (v28.38).

Both follow the shop's rule for reserve gateways: a notification is trusted only when its signature is right **and**
the gateway's own API, asked again, says the order is paid with the same amount and currency — only then is the
subscription delivered. No recurring charges and no refunds through the API (refunds are made in the gateway's
dashboard and recorded by hand). Each gateway joins the gateway queue and the payment methods routing as soon as its
keys are set in «Настройки» (runtime settings, secrets stored encrypted).

**CloudPayments** (cards, SBP): ``POST https://api.cloudpayments.ru/orders/create`` with HTTP Basic (Public ID : API
secret) gives the payment page. The «Pay» notification (``/api/webhooks/cloudpayments``, form body) is signed in
``Content-HMAC`` — base64 HMAC-SHA256 of the raw body with the API secret (``X-Content-HMAC`` — of the URL-decoded
body); the order is re-read with ``POST /payments/find`` (``InvoiceId``). The answer is ``{"code": 0}``.

**Lava** (cards, SBP; api.lava.ru «business»): ``POST /business/invoice/create`` with the JSON body signed in the
``Signature`` header (HMAC-SHA256 hex with the secret key) gives the payment page. The notification
(``/api/webhooks/lava``, JSON) is signed in ``Authorization`` with the additional key — of the raw body or of the
same JSON with sorted keys (Lava does both); the invoice is re-read with ``POST /business/invoice/status``.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
from decimal import Decimal
from typing import Any, Dict
from urllib.parse import parse_qsl, unquote_plus

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import get_db
from .payments import BasePaymentProvider, PaymentError, SignatureVerificationError, _money, _public_client

logger = logging.getLogger("vpnshop.payments_extra")
router = APIRouter()


class CloudPaymentsProvider(BasePaymentProvider):
    API_URL = "https://api.cloudpayments.ru"

    @staticmethod
    def configured() -> bool:
        return bool(settings.cloudpayments_public_id and settings.cloudpayments_api_secret)

    def _auth(self) -> str:
        raw = f"{settings.cloudpayments_public_id}:{settings.cloudpayments_api_secret}".encode()
        return "Basic " + base64.b64encode(raw).decode()

    async def _post(self, path: str, body: dict) -> dict:
        async with _public_client(20) as client:
            r = await client.post(self.API_URL + path, json=body, headers={"Authorization": self._auth()})
        r.raise_for_status()
        return r.json()

    async def create_payment(self, amount: float, currency: str, description: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        order_id = str(metadata.get("order_id") or "")
        if not order_id or not self.configured():
            raise PaymentError("CloudPayments is not configured")
        body = {"Amount": float(_money(amount)), "Currency": currency or "RUB", "Description": description[:200] or "Подписка",
                "InvoiceId": order_id, "JsonData": {"order_id": order_id}}
        if metadata.get("return_url"):
            body["SuccessRedirectUrl"] = metadata["return_url"]
        out = await self._post("/orders/create", body)
        url = ((out or {}).get("Model") or {}).get("Url")
        if not out.get("Success") or not url:
            raise PaymentError(f"CloudPayments: {str(out.get('Message') or 'no payment page')[:200]}")
        # The transaction id appears only after payment; the shop order id (InvoiceId) identifies the payment until then.
        return {"id": order_id, "url": url, "status": "pending"}

    async def create(self, amount: Decimal, order_id: str, description: str, return_url: str, method: str = "") -> Dict[str, Any]:
        return await self.create_payment(float(amount), settings.default_currency, description, {"order_id": order_id, "return_url": return_url})

    async def get_payment_status(self, payment_id: str) -> Dict[str, Any]:
        out = await self._post("/payments/find", {"InvoiceId": str(payment_id)})
        return (out or {}).get("Model") or {} if out.get("Success") else {}

    async def verify_succeeded(self, payment_id: str, expected_amount: Decimal, currency: str, expected_order_id: str | None = None) -> bool:
        model = await self.get_payment_status(expected_order_id or payment_id)
        if str(model.get("Status") or "") not in {"Completed", "Authorized"}:
            return False
        if str(model.get("Currency") or currency).upper() != str(currency).upper():
            return False
        return Decimal(str(model.get("Amount") or "0")).quantize(Decimal("0.01")) == Decimal(str(expected_amount)).quantize(Decimal("0.01"))

    def verify_webhook(self, headers, body: bytes, remote_addr: str | None = None) -> Dict[str, Any]:
        secret = settings.cloudpayments_api_secret.encode()
        sign = lambda data: base64.b64encode(hmac.new(secret, data, hashlib.sha256).digest()).decode()  # noqa: E731
        got = {k.lower(): v for k, v in dict(headers).items()}
        ok = False
        if got.get("content-hmac"):
            ok = hmac.compare_digest(sign(body), got["content-hmac"].strip())
        if not ok and got.get("x-content-hmac"):
            ok = hmac.compare_digest(sign(unquote_plus(body.decode("utf-8", "replace")).encode()), got["x-content-hmac"].strip())
        if not secret or not ok:
            raise SignatureVerificationError("Invalid CloudPayments signature")
        text = body.decode("utf-8", "replace")
        return json.loads(text) if text.lstrip().startswith("{") else dict(parse_qsl(text))


class LavaProvider(BasePaymentProvider):
    API_URL = "https://api.lava.ru"

    @staticmethod
    def configured() -> bool:
        return bool(settings.lava_shop_id and settings.lava_secret_key and settings.lava_webhook_secret)

    @staticmethod
    def signature(body: bytes, key: str) -> str:
        return hmac.new(key.encode(), body, hashlib.sha256).hexdigest()

    async def _post(self, path: str, payload: dict) -> dict:
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
        headers = {"Content-Type": "application/json", "Accept": "application/json", "Signature": self.signature(body, settings.lava_secret_key)}
        async with _public_client(20) as client:
            r = await client.post(self.API_URL + path, content=body, headers=headers)
        r.raise_for_status()
        return r.json()

    async def create_payment(self, amount: float, currency: str, description: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        order_id = str(metadata.get("order_id") or "")
        if not order_id or not self.configured():
            raise PaymentError("Lava is not configured")
        payload = {"sum": float(_money(amount)), "orderId": order_id, "shopId": settings.lava_shop_id, "comment": description[:255] or "Подписка",
                   "hookUrl": f"{settings.webhook_base_url.rstrip('/')}/api/webhooks/lava" if settings.webhook_base_url else None}
        if metadata.get("return_url"):
            payload["successUrl"] = str(metadata["return_url"]).split("?", 1)[0][:500]  # Lava refuses a query string here
        out = await self._post("/business/invoice/create", {k: v for k, v in payload.items() if v is not None})
        data = out.get("data") if isinstance(out.get("data"), dict) else out
        if str(out.get("status") or "").lower() == "error" or not data.get("url"):
            raise PaymentError(f"Lava: {str(out.get('error') or out.get('message') or 'no payment page')[:200]}")
        return {"id": order_id, "url": data["url"], "status": "pending"}

    async def create(self, amount: Decimal, order_id: str, description: str, return_url: str, method: str = "") -> Dict[str, Any]:
        return await self.create_payment(float(amount), settings.default_currency, description, {"order_id": order_id, "return_url": return_url})

    async def get_payment_status(self, payment_id: str) -> Dict[str, Any]:
        out = await self._post("/business/invoice/status", {"shopId": settings.lava_shop_id, "orderId": str(payment_id)})
        return out.get("data") if isinstance(out.get("data"), dict) else out

    async def verify_succeeded(self, payment_id: str, expected_amount: Decimal, currency: str, expected_order_id: str | None = None) -> bool:
        data = await self.get_payment_status(expected_order_id or payment_id)
        if str(data.get("status") or "").lower() != "success":
            return False
        return Decimal(str(data.get("amount") or data.get("sum") or "0")).quantize(Decimal("0.01")) == Decimal(str(expected_amount)).quantize(Decimal("0.01"))

    def verify_webhook(self, headers, body: bytes, remote_addr: str | None = None) -> Dict[str, Any]:
        got = {k.lower(): v for k, v in dict(headers).items()}.get("authorization", "").strip()
        key = settings.lava_webhook_secret
        try:
            data = json.loads(body)
        except ValueError as exc:
            raise SignatureVerificationError("Invalid Lava body") from exc
        canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        if not key or not got or not any(hmac.compare_digest(self.signature(b, key), got) for b in (body, canonical)):
            raise SignatureVerificationError("Invalid Lava signature")
        return data


async def _settle(db: AsyncSession, provider_name: str, provider, order_id: str, event_id: str, amount: str | None) -> str:
    """The common tail of a verified notification: find the order, check the amount, re-read the gateway, fulfil once."""
    from . import main as shop
    p = await shop.payment_by_provider_or_order(db, provider_name, order_id, order_id)
    if not p:
        return "unknown"
    if p.provider != provider_name:
        raise HTTPException(403, "Order mismatch")
    if amount is not None and Decimal(str(amount)).quantize(Decimal("0.01")) != Decimal(str(p.amount)).quantize(Decimal("0.01")):
        raise HTTPException(403, "Amount mismatch")
    if not await provider.verify_succeeded(order_id, Decimal(str(p.amount)), p.currency, p.order_id):
        raise HTTPException(503, "Payment verification unavailable")
    if not await shop.register_provider_event(db, provider_name, event_id, p.id):
        await db.rollback()
        return "duplicate"
    await db.commit()
    try:
        await shop._confirm_and_fulfill_payment(p.id, db)
        async with AsyncSession(shop.engine, expire_on_commit=False) as edb:
            await shop.finish_provider_event(edb, provider_name, event_id, ok=True)
            await edb.commit()
    except Exception as exc:
        async with AsyncSession(shop.engine, expire_on_commit=False) as edb:
            await shop.finish_provider_event(edb, provider_name, event_id, ok=False, error=str(exc))
            await edb.commit()
        raise
    return "paid"


@router.post("/api/webhooks/cloudpayments")
async def cloudpayments_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    raw = await request.body()
    if len(raw) > 64 * 1024:
        raise HTTPException(413, "Payload too large")
    provider = CloudPaymentsProvider()
    try:
        data = provider.verify_webhook(request.headers, raw)
    except SignatureVerificationError:
        raise HTTPException(403, "Invalid signature")
    status = str(data.get("Status") or "")
    order_id = str(data.get("InvoiceId") or "")
    if status not in {"Completed", "Authorized"} or not order_id:
        return JSONResponse({"code": 0})  # «Check», «Fail» and others: nothing to deliver
    await _settle(db, "cloudpayments", provider, order_id, f"pay:{data.get('TransactionId') or order_id}", data.get("Amount"))
    return JSONResponse({"code": 0})


@router.post("/api/webhooks/lava")
async def lava_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    raw = await request.body()
    if len(raw) > 64 * 1024:
        raise HTTPException(413, "Payload too large")
    provider = LavaProvider()
    try:
        data = provider.verify_webhook(request.headers, raw)
    except SignatureVerificationError:
        raise HTTPException(403, "Invalid signature")
    order_id = str(data.get("order_id") or data.get("orderId") or "")
    if str(data.get("status") or "").lower() != "success" or not order_id:
        return {"ok": True}
    await _settle(db, "lava", provider, order_id, f"paid:{data.get('invoice_id') or order_id}", data.get("amount"))
    return {"ok": True}
