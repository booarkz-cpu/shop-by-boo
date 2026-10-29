"""**Mulen Pay** (cards, SBP): ``POST https://mulenpay.ru/api/v2/payments`` with ``Authorization: Bearer`` (API key) and
``sign`` = SHA-1 of ``currency + amount + shopId + secret key`` gives the payment page. The notification
(``/api/webhooks/mulenpay``, JSON) may carry ``sign`` (SHA-1 of all values in order + secret key): a wrong one is
refused, a missing one is allowed because the payment is always re-read with ``GET /v2/payments/{id}`` (status 3 —
paid) before anything is delivered.
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


class MulenPayProvider(BasePaymentProvider):
    API_URL = "https://mulenpay.ru/api"

    @staticmethod
    def configured() -> bool:
        return bool(settings.mulenpay_api_key and settings.mulenpay_secret_key and settings.mulenpay_shop_id)

    @staticmethod
    def create_sign(currency: str, amount: str) -> str:
        return hashlib.sha1(f"{currency}{amount}{settings.mulenpay_shop_id}{settings.mulenpay_secret_key}".encode(), usedforsecurity=False).hexdigest()

    @staticmethod
    def notification_sign(data: dict) -> str:
        joined = "".join(str(v) for k, v in data.items() if k != "sign")
        return hashlib.sha1((joined + settings.mulenpay_secret_key).encode(), usedforsecurity=False).hexdigest()

    async def _call(self, method: str, path: str, **kwargs) -> dict:
        headers = {"Authorization": f"Bearer {settings.mulenpay_api_key}", "Accept": "application/json"}
        async with common._public_client(20) as client:
            r = await client.request(method, self.API_URL + path, headers=headers, **kwargs)
        r.raise_for_status()
        return r.json()

    async def create_payment(self, amount: float, currency: str, description: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        order_id = str(metadata.get("order_id") or "")
        if not order_id or not self.configured():
            raise PaymentError("Mulen Pay is not configured")
        cur = (currency or "RUB").lower()
        total = str(_money(amount))
        text = description[:128] or "Подписка"
        body = {"currency": cur, "amount": total, "uuid": order_id, "shopId": int(settings.mulenpay_shop_id) if str(settings.mulenpay_shop_id).isdigit() else settings.mulenpay_shop_id,
                "description": text, "language": "ru", "sign": self.create_sign(cur, total),
                "items": [{"description": text, "quantity": 1, "price": float(total), "vat_code": 0, "payment_subject": 4, "payment_mode": 4}]}
        if metadata.get("return_url"):
            body["website_url"] = metadata["return_url"]
        out = await self._call("POST", "/v2/payments", json=body)
        if not out.get("success") or not out.get("id") or not out.get("paymentUrl"):
            raise PaymentError(f"Mulen Pay: {str(out.get('message') or out.get('error') or 'no payment page')[:200]}")
        return {"id": str(out["id"]), "url": out["paymentUrl"], "status": "pending"}

    async def create(self, amount: Decimal, order_id: str, description: str, return_url: str, method: str = "") -> Dict[str, Any]:
        return await self.create_payment(float(amount), settings.default_currency, description, {"order_id": order_id, "return_url": return_url})

    async def get_payment_status(self, payment_id: str) -> Dict[str, Any]:
        out = await self._call("GET", f"/v2/payments/{payment_id}")
        if isinstance(out.get("payment"), dict):
            return out["payment"]
        return out if "status" in out else {}

    async def verify_succeeded(self, payment_id: str, expected_amount: Decimal, currency: str, expected_order_id: str | None = None) -> bool:
        if not str(payment_id).isdigit():
            return False  # the payment id from Mulen Pay is a number; the order id alone cannot be re-read
        data = await self.get_payment_status(payment_id)
        if str(data.get("status")) not in {"3", "success"}:
            return False
        if expected_order_id and data.get("uuid") not in (None, "", expected_order_id):
            return False
        return Decimal(str(data.get("amount") or "0")).quantize(Decimal("0.01")) == Decimal(str(expected_amount)).quantize(Decimal("0.01"))

    async def probe(self) -> str:
        return await common.probe_http("GET", self.API_URL + "/v2/payments", params={"limit": 1},
                                       headers={"Authorization": f"Bearer {settings.mulenpay_api_key}"})

    def verify_webhook(self, headers, body: bytes, remote_addr: str | None = None) -> Dict[str, Any]:
        try:
            data = json.loads(body)
        except ValueError as exc:
            raise SignatureVerificationError("Invalid Mulen Pay body") from exc
        if not isinstance(data, dict) or not self.configured():
            raise SignatureVerificationError("Invalid Mulen Pay notification")
        got = data.get("sign")
        if got and not hmac.compare_digest(self.notification_sign(data), str(got).lower()):
            raise SignatureVerificationError("Invalid Mulen Pay signature")
        return data


@router.post("/api/webhooks/mulenpay")
async def mulenpay_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    raw = await request.body()
    if len(raw) > 64 * 1024:
        raise HTTPException(413, "Payload too large")
    provider = MulenPayProvider()
    try:
        data = provider.verify_webhook(request.headers, raw)
    except SignatureVerificationError:
        raise HTTPException(403, "Invalid signature")
    order_id = str(data.get("uuid") or "")
    state = str(data.get("payment_status") or data.get("status") or "").lower()
    if state not in {"success", "3"} or not order_id:
        return {"ok": True}
    await _settle(db, "mulenpay", provider, order_id, f"paid:{data.get('id') or order_id}", data.get("amount"))
    return {"ok": True}
