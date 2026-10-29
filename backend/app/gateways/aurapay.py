"""**AuraPay** (cards, SBP; app.aurapay.tech): ``POST /invoice/create`` with ``X-ApiKey`` and ``X-ShopId`` gives the
payment page. The notification (``/api/webhooks/aurapay``, JSON) is signed in ``X-SIGNATURE`` — HMAC-SHA256 hex with
secret key #2 of all values in alphabetical order of the keys (null as an empty string); the invoice is re-read with
``POST /invoice/status``. The answer is ``{"status": true}``.

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


class AuraPayProvider(BasePaymentProvider):
    API_URL = "https://app.aurapay.tech"
    METHODS = {"sbp": "sbp", "card": "card"}

    @staticmethod
    def configured() -> bool:
        return bool(settings.aurapay_api_key and settings.aurapay_shop_id and settings.aurapay_secret_key)

    @staticmethod
    def signature(data: dict) -> str:
        return _sorted_values_hmac(data, settings.aurapay_secret_key)

    async def _post(self, path: str, body: dict) -> dict:
        headers = {"X-ApiKey": settings.aurapay_api_key, "X-ShopId": settings.aurapay_shop_id, "Accept": "application/json"}
        async with common._public_client(20) as client:
            r = await client.post(self.API_URL + path, json=body, headers=headers)
        r.raise_for_status()
        return r.json()

    async def create_payment(self, amount: float, currency: str, description: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        order_id = str(metadata.get("order_id") or "")
        if not order_id or not self.configured():
            raise PaymentError("AuraPay is not configured")
        body = {"amount": float(_money(amount)), "order_id": order_id, "comment": description[:200] or "Подписка"}
        if self.METHODS.get(str(metadata.get("method") or "")):
            body["service"] = self.METHODS[str(metadata["method"])]
        if metadata.get("return_url"):
            body["success_url"] = body["fail_url"] = metadata["return_url"]
        if settings.webhook_base_url:
            body["callback_url"] = f"{settings.webhook_base_url.rstrip('/')}/api/webhooks/aurapay"
        out = await self._post("/invoice/create", body)
        page = out.get("payment_data") if isinstance(out.get("payment_data"), dict) else {}
        url = page.get("url") or out.get("url")
        if not out.get("id") or not url:
            raise PaymentError(f"AuraPay: {str(out.get('message') or out.get('error') or 'no payment page')[:200]}")
        return {"id": str(out["id"]), "url": url, "status": "pending"}

    async def create(self, amount: Decimal, order_id: str, description: str, return_url: str, method: str = "") -> Dict[str, Any]:
        return await self.create_payment(float(amount), settings.default_currency, description, {"order_id": order_id, "return_url": return_url, "method": method})

    async def get_payment_status(self, payment_id: str) -> Dict[str, Any]:
        return await self._post("/invoice/status", {"id": str(payment_id)})

    async def verify_succeeded(self, payment_id: str, expected_amount: Decimal, currency: str, expected_order_id: str | None = None) -> bool:
        data = await (self._post("/invoice/status", {"order_id": expected_order_id}) if expected_order_id else self.get_payment_status(payment_id))
        if str(data.get("status") or "").upper() != "PAID":
            return False
        if expected_order_id and data.get("order_id") not in (None, "", expected_order_id):
            return False
        return Decimal(str(data.get("amount") or "0")).quantize(Decimal("0.01")) == Decimal(str(expected_amount)).quantize(Decimal("0.01"))

    async def probe(self) -> str:
        return await common.probe_http("POST", self.API_URL + "/invoice/status", json={"order_id": "probe"},
                                       headers={"X-ApiKey": settings.aurapay_api_key, "X-ShopId": settings.aurapay_shop_id})

    def verify_webhook(self, headers, body: bytes, remote_addr: str | None = None) -> Dict[str, Any]:
        got = {k.lower(): v for k, v in dict(headers).items()}.get("x-signature", "").strip().lower()
        try:
            data = json.loads(body, parse_float=str, parse_int=str)
        except ValueError as exc:
            raise SignatureVerificationError("Invalid AuraPay body") from exc
        if not isinstance(data, dict) or not self.configured() or not got or not hmac.compare_digest(self.signature(data), got):
            raise SignatureVerificationError("Invalid AuraPay signature")
        return data


@router.post("/api/webhooks/aurapay")
async def aurapay_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    raw = await request.body()
    if len(raw) > 64 * 1024:
        raise HTTPException(413, "Payload too large")
    provider = AuraPayProvider()
    try:
        data = provider.verify_webhook(request.headers, raw)
    except SignatureVerificationError:
        raise HTTPException(403, "Invalid signature")
    order_id = str(data.get("order_id") or "")
    if str(data.get("status") or "").upper() != "PAID" or not order_id:
        return {"status": True}
    await _settle(db, "aurapay", provider, order_id, f"paid:{data.get('id') or order_id}", data.get("amount"))
    return {"status": True}
