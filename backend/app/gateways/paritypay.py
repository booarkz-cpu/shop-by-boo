"""**ParityPay** (cards, SBP; api.paritypay.net v2): ``POST /v2/invoice/create`` with ``X-ShopId`` and ``X-SecretKey``
(key #1) gives the payment link. The notification (``/api/webhooks/paritypay``) is signed in ``X-SIGNATURE`` like
AuraPay's (key #2); the invoice is re-read with ``GET /v2/invoice/status?order_id=``.

AuraPay and ParityPay sign the values as the sender wrote them, so the body is parsed with numbers kept as text and
booleans written as ``true``/``false`` (``199`` must not become ``199.0``).
"""
from __future__ import annotations

import hmac
import json
from decimal import Decimal
from typing import Any, Dict

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import get_db
from ..payments import BasePaymentProvider, PaymentError, SignatureVerificationError, _money
from . import common
from .common import _settle, _sorted_values_hmac, router


class ParityPayProvider(BasePaymentProvider):
    API_URL = "https://api.paritypay.net"
    METHODS = {"sbp": "sbp", "card": "card"}

    @staticmethod
    def configured() -> bool:
        return bool(settings.paritypay_shop_id and settings.paritypay_secret_key and settings.paritypay_callback_secret)

    async def _call(self, method: str, path: str, **kwargs) -> dict:
        headers = {"X-ShopId": settings.paritypay_shop_id, "X-SecretKey": settings.paritypay_secret_key, "Accept": "application/json"}
        async with common._public_client(20) as client:
            r = await client.request(method, self.API_URL + path, headers=headers, **kwargs)
        if r.status_code == 404:
            return {}
        r.raise_for_status()
        return r.json()

    async def create_payment(self, amount: float, currency: str, description: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        order_id = str(metadata.get("order_id") or "")
        if not order_id or not self.configured():
            raise PaymentError("ParityPay is not configured")
        body: Dict[str, Any] = {"order_id": order_id[:64], "amount": float(_money(amount)), "comment": description[:255] or "Подписка"}
        if self.METHODS.get(str(metadata.get("method") or "")):
            body["service"] = self.METHODS[str(metadata["method"])]
        if metadata.get("return_url"):
            body["success_url"] = body["fail_url"] = metadata["return_url"]
        if settings.webhook_base_url:
            body["callback_url"] = f"{settings.webhook_base_url.rstrip('/')}/api/webhooks/paritypay"
        out = await self._call("POST", "/v2/invoice/create", json=body)
        if not out.get("id") or not out.get("link"):
            raise PaymentError(f"ParityPay: {str(out.get('message') or out.get('error') or 'no payment link')[:200]}")
        return {"id": str(out["id"]), "url": out["link"], "status": "pending"}

    async def create(self, amount: Decimal, order_id: str, description: str, return_url: str, method: str = "") -> Dict[str, Any]:
        return await self.create_payment(float(amount), settings.default_currency, description, {"order_id": order_id, "return_url": return_url, "method": method})

    async def get_payment_status(self, payment_id: str) -> Dict[str, Any]:
        return await self._call("GET", "/v2/invoice/status", params={"id": str(payment_id)})

    async def verify_succeeded(self, payment_id: str, expected_amount: Decimal, currency: str, expected_order_id: str | None = None) -> bool:
        data = await (self._call("GET", "/v2/invoice/status", params={"order_id": expected_order_id}) if expected_order_id else self.get_payment_status(payment_id))
        if str(data.get("status") or "").upper() != "PAID":
            return False
        if expected_order_id and data.get("order_id") not in (None, "", expected_order_id):
            return False
        return Decimal(str(data.get("amount") or "0")).quantize(Decimal("0.01")) == Decimal(str(expected_amount)).quantize(Decimal("0.01"))

    async def probe(self) -> str:
        return await common.probe_http("GET", self.API_URL + "/v2/invoice/status", params={"order_id": "probe"},
                                       headers={"X-ShopId": settings.paritypay_shop_id, "X-SecretKey": settings.paritypay_secret_key})

    def verify_webhook(self, headers, body: bytes, remote_addr: str | None = None) -> Dict[str, Any]:
        got = {k.lower(): v for k, v in dict(headers).items()}.get("x-signature", "").strip().lower()
        try:
            data = json.loads(body, parse_float=str, parse_int=str)
        except ValueError as exc:
            raise SignatureVerificationError("Invalid ParityPay body") from exc
        if not isinstance(data, dict) or not self.configured() or not got or not hmac.compare_digest(_sorted_values_hmac(data, settings.paritypay_callback_secret), got):
            raise SignatureVerificationError("Invalid ParityPay signature")
        return data


@router.post("/api/webhooks/paritypay")
async def paritypay_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    raw = await request.body()
    if len(raw) > 64 * 1024:
        raise HTTPException(413, "Payload too large")
    provider = ParityPayProvider()
    try:
        data = provider.verify_webhook(request.headers, raw)
    except SignatureVerificationError:
        raise HTTPException(403, "Invalid signature")
    order_id = str(data.get("order_id") or "")
    if str(data.get("status") or "").upper() != "PAID" or not order_id:
        return {"status": True}
    await _settle(db, "paritypay", provider, order_id, f"paid:{data.get('id') or order_id}", data.get("amount"))
    return {"status": True}
