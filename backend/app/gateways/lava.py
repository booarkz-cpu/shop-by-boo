"""**Lava** (cards, SBP; api.lava.ru «business»): ``POST /business/invoice/create`` with the JSON body signed in the
``Signature`` header (HMAC-SHA256 hex with the secret key) gives the payment page. The notification
(``/api/webhooks/lava``, JSON) is signed in ``Authorization`` with the additional key — of the raw body or of the
same JSON with sorted keys (Lava does both); the invoice is re-read with ``POST /business/invoice/status``.
"""
from __future__ import annotations

import hashlib
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
from .common import _settle, router


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
        async with common._public_client(20) as client:
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

    async def probe(self) -> str:
        body = json.dumps({"shopId": settings.lava_shop_id, "orderId": "probe"}, separators=(",", ":")).encode()
        return await common.probe_http("POST", self.API_URL + "/business/invoice/status", content=body,
                                       headers={"Content-Type": "application/json", "Signature": self.signature(body, settings.lava_secret_key)})

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
