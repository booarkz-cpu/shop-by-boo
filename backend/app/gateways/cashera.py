"""**Cashera** (cards, SBP; api.cashera.cash v1): ``POST /integration/transactions`` with ``X-Api-Key`` (amounts in kopecks)
gives the payment page. The notification (``/api/webhooks/cashera``) carries the static ``X-Api-Key`` and ``X-Secret``,
compared in constant time; the transaction is re-read with ``GET /integration/transactions/{uuid}``. One-time payments
only: Cashera subscriptions are not used.
"""
from __future__ import annotations

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


class CasheraProvider(BasePaymentProvider):
    API_URL = "https://api.cashera.cash/api/v1"
    METHODS = {"sbp": "sbp", "card": "card"}

    @staticmethod
    def configured() -> bool:
        return bool(settings.cashera_api_key and settings.cashera_api_secret)

    async def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        headers = {"X-Api-Key": settings.cashera_api_key, "Accept": "application/json"}
        async with common._public_client(20) as client:
            r = await client.request(method, self.API_URL + path, json=body, headers=headers)
        r.raise_for_status()
        out = r.json()
        return out.get("data") if isinstance(out.get("data"), dict) else out

    async def create_payment(self, amount: float, currency: str, description: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        order_id = str(metadata.get("order_id") or "")
        if not order_id or not self.configured():
            raise PaymentError("Cashera is not configured")
        body: Dict[str, Any] = {"amount": int(Decimal(_money(amount)) * 100), "currency": (currency or "RUB").upper(),
                                "external_id": order_id, "description": description[:255] or "Подписка"}
        if self.METHODS.get(str(metadata.get("method") or "")):
            body["payment_method"] = self.METHODS[str(metadata["method"])]
        if metadata.get("return_url"):
            body["success_url"] = body["fail_url"] = metadata["return_url"]
        if settings.webhook_base_url:
            body["callback_url"] = f"{settings.webhook_base_url.rstrip('/')}/api/webhooks/cashera"
        out = await self._call("POST", "/integration/transactions", body)
        url = str(out.get("payment_url") or "")
        if url and not url.startswith(("https://", "http://")):
            url = "https://" + url.lstrip("/")  # Cashera sometimes answers without the scheme
        if not out.get("uuid") or not url:
            raise PaymentError(f"Cashera: {str(out.get('message') or 'no payment page')[:200]}")
        return {"id": str(out["uuid"]), "url": url, "status": "pending"}

    async def create(self, amount: Decimal, order_id: str, description: str, return_url: str, method: str = "") -> Dict[str, Any]:
        return await self.create_payment(float(amount), settings.default_currency, description, {"order_id": order_id, "return_url": return_url, "method": method})

    async def get_payment_status(self, payment_id: str) -> Dict[str, Any]:
        if not re.fullmatch(r"[A-Za-z0-9-]{1,64}", str(payment_id)):
            return {}
        return await self._call("GET", f"/integration/transactions/{payment_id}")

    async def verify_succeeded(self, payment_id: str, expected_amount: Decimal, currency: str, expected_order_id: str | None = None) -> bool:
        data = await self.get_payment_status(payment_id)
        if str(data.get("status") or "").lower() != "paid":
            return False
        if expected_order_id and data.get("external_id") not in (None, "", expected_order_id):
            return False
        if str(data.get("currency") or currency).upper() != str(currency).upper():
            return False
        return int(data.get("amount") or 0) == int((Decimal(str(expected_amount)) * 100).to_integral_value())

    async def probe(self) -> str:
        return await common.probe_http("GET", self.API_URL + "/integration/transactions/00000000-0000-0000-0000-000000000000",
                                       headers={"X-Api-Key": settings.cashera_api_key})

    def verify_webhook(self, headers, body: bytes, remote_addr: str | None = None) -> Dict[str, Any]:
        got = {k.lower(): v for k, v in dict(headers).items()}
        if not self.configured():
            raise SignatureVerificationError("Cashera is not configured")
        key_ok = hmac.compare_digest(str(got.get("x-api-key", "")).encode(), settings.cashera_api_key.encode())
        secret_ok = hmac.compare_digest(str(got.get("x-secret", "")).encode(), settings.cashera_api_secret.encode())
        if not (key_ok and secret_ok):
            raise SignatureVerificationError("Invalid Cashera credentials")
        try:
            data = json.loads(body)
        except ValueError as exc:
            raise SignatureVerificationError("Invalid Cashera body") from exc
        if not isinstance(data, dict):
            raise SignatureVerificationError("Invalid Cashera body")
        return data.get("transaction") if isinstance(data.get("transaction"), dict) else data


@router.post("/api/webhooks/cashera")
async def cashera_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    raw = await request.body()
    if len(raw) > 64 * 1024:
        raise HTTPException(413, "Payload too large")
    provider = CasheraProvider()
    try:
        data = provider.verify_webhook(request.headers, raw)
    except SignatureVerificationError:
        raise HTTPException(401, "Invalid credentials")
    order_id = str(data.get("external_id") or "")
    if str(data.get("status") or "").lower() != "paid" or not order_id:
        return {"status": "ok"}
    amount = Decimal(int(data["amount"])) / 100 if str(data.get("amount") or "").isdigit() else None
    await _settle(db, "cashera", provider, order_id, f"paid:{data.get('uuid') or order_id}", None if amount is None else str(amount))
    return {"status": "ok"}
