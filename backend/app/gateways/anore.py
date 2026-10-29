"""**Anore** (cards, SBP; api.anore.cc v1): ``POST /payments`` with ``Authorization: Bearer`` and the body signed in
``Anore-Signature`` (HMAC-SHA256 hex with the secret key). The notification (``/api/webhooks/anore``) is signed the same
way, with ``Anore-Event`` equal to the body's ``event``; the payment is re-read with ``GET /payments/{id}``.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from decimal import Decimal
from typing import Any, Dict

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import get_db
from ..payments import BasePaymentProvider, PaymentError, SignatureVerificationError, _money
from . import common
from .common import _settle, router


class AnoreProvider(BasePaymentProvider):
    API_URL = "https://api.anore.cc/v1"
    METHODS = {"sbp": ["sbp"], "card": ["card"]}

    @staticmethod
    def configured() -> bool:
        return bool(settings.anore_api_key and settings.anore_secret_key)

    @staticmethod
    def signature(body: bytes) -> str:
        return hmac.new(settings.anore_secret_key.encode(), body, hashlib.sha256).hexdigest()

    async def _call(self, method: str, path: str, payload: dict | None = None) -> dict:
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode() if payload is not None else None
        headers = {"Authorization": f"Bearer {settings.anore_api_key}", "Content-Type": "application/json", "Accept": "application/json"}
        if body is not None:
            headers["Anore-Signature"] = self.signature(body)
        async with common._public_client(20) as client:
            r = await client.request(method, self.API_URL + path, content=body, headers=headers)
        r.raise_for_status()
        out = r.json()
        return out.get("data") if isinstance(out.get("data"), dict) else out

    async def create_payment(self, amount: float, currency: str, description: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        order_id = str(metadata.get("order_id") or "")
        if not order_id or not self.configured():
            raise PaymentError("Anore is not configured")
        payload: Dict[str, Any] = {"amount": float(_money(amount)), "currency": (currency or "RUB").upper(), "description": description[:200] or "Подписка", "orderId": order_id}
        if str(settings.anore_shop_id).isdigit():
            payload["shopId"] = int(settings.anore_shop_id)
        if self.METHODS.get(str(metadata.get("method") or "")):
            payload["methods"] = self.METHODS[str(metadata["method"])]
        if metadata.get("return_url"):
            payload["successurl"] = payload["failurl"] = metadata["return_url"]
        if settings.webhook_base_url:
            payload["callbackUrl"] = f"{settings.webhook_base_url.rstrip('/')}/api/webhooks/anore"
        out = await self._call("POST", "/payments", payload)
        url = str(out.get("paymentUrl") or "")
        if not out.get("id") or not url.startswith("https://") or (out.get("orderId") not in (None, order_id)):
            raise PaymentError(f"Anore: {str(out.get('message') or out.get('error') or 'no payment page')[:200]}")
        return {"id": str(out["id"]), "url": url, "status": "pending"}

    async def create(self, amount: Decimal, order_id: str, description: str, return_url: str, method: str = "") -> Dict[str, Any]:
        return await self.create_payment(float(amount), settings.default_currency, description, {"order_id": order_id, "return_url": return_url, "method": method})

    async def get_payment_status(self, payment_id: str) -> Dict[str, Any]:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", str(payment_id)):
            return {}
        return await self._call("GET", f"/payments/{payment_id}")

    async def verify_succeeded(self, payment_id: str, expected_amount: Decimal, currency: str, expected_order_id: str | None = None) -> bool:
        data = await self.get_payment_status(payment_id)
        if data.get("status") != "paid" or data.get("paid") is False:
            return False
        if expected_order_id and data.get("orderId") not in (None, "", expected_order_id):
            return False
        if str(data.get("currency") or currency).upper() != str(currency).upper():
            return False
        want = Decimal(str(expected_amount)).quantize(Decimal("0.01"))
        if "rubAmount" in data and Decimal(str(data["rubAmount"])).quantize(Decimal("0.01")) != want:
            return False
        return Decimal(str(data.get("amount") or "0")).quantize(Decimal("0.01")) == want

    async def probe(self) -> str:
        return await common.probe_http("GET", self.API_URL + "/payments/probe", headers={"Authorization": f"Bearer {settings.anore_api_key}"})

    def verify_webhook(self, headers, body: bytes, remote_addr: str | None = None) -> Dict[str, Any]:
        got = {k.lower(): v for k, v in dict(headers).items()}
        sig = str(got.get("anore-signature", "")).strip().lower()
        if not self.configured() or not re.fullmatch(r"[0-9a-f]{64}", sig) or not hmac.compare_digest(self.signature(body), sig):
            raise SignatureVerificationError("Invalid Anore signature")
        try:
            data = json.loads(body)
        except ValueError as exc:
            raise SignatureVerificationError("Invalid Anore body") from exc
        if not isinstance(data, dict) or str(got.get("anore-event", "")) != str(data.get("event") or ""):
            raise SignatureVerificationError("Anore event mismatch")
        return data


@router.post("/api/webhooks/anore")
async def anore_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    raw = await request.body()
    if len(raw) > 64 * 1024:
        raise HTTPException(413, "Payload too large")
    provider = AnoreProvider()
    try:
        data = provider.verify_webhook(request.headers, raw)
    except SignatureVerificationError:
        raise HTTPException(403, "Invalid signature")
    order_id = str(data.get("orderId") or "")
    if data.get("event") != "payment.succeeded" or data.get("status") != "paid" or not order_id:
        return {"success": True}
    await _settle(db, "anore", provider, order_id, f"paid:{str(data.get('id') or order_id)[:120]}", data.get("amount"))
    return {"success": True}
