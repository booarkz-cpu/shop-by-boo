"""**WATA** (cards, SBP; api.wata.pro H2H): ``POST /links`` with ``Authorization: Bearer`` (access token) gives a payment
link. The notification (``/api/webhooks/wata``, JSON) is signed in ``X-Signature`` — base64 RSA SHA-512 (PKCS#1 v1.5)
of the raw body; the public key comes from ``GET /public-key`` (cached for an hour). The payment is re-read with
``GET /transactions?orderId=&statuses=Paid``.
"""
from __future__ import annotations

import json
import time
from decimal import Decimal
from typing import Any, Dict

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import get_db
from ..payments import BasePaymentProvider, PaymentError, SignatureVerificationError, _money
from . import common
from .common import _rsa_verify, _settle, router


class WataProvider(BasePaymentProvider):
    API_URL = "https://api.wata.pro/api/h2h"
    KEY_TTL = 3600
    _key: tuple[float, str] | None = None

    @staticmethod
    def configured() -> bool:
        return bool(settings.wata_access_token)

    async def _call(self, method: str, path: str, auth: bool = True, **kwargs) -> dict:
        headers = {"Accept": "application/json"}
        if auth:
            headers["Authorization"] = f"Bearer {settings.wata_access_token}"
        async with common._public_client(20) as client:
            r = await client.request(method, self.API_URL + path, headers=headers, **kwargs)
        r.raise_for_status()
        return r.json()

    async def public_key(self) -> str:
        cached = WataProvider._key
        if cached and time.monotonic() - cached[0] < self.KEY_TTL:
            return cached[1]
        out = await self._call("GET", "/public-key", auth=False)
        value = str(out.get("value") or "")
        if value:
            WataProvider._key = (time.monotonic(), value)
        return value

    async def create_payment(self, amount: float, currency: str, description: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        order_id = str(metadata.get("order_id") or "")
        if not order_id or not self.configured():
            raise PaymentError("WATA is not configured")
        body = {"amount": float(_money(amount)), "currency": currency or "RUB", "description": description[:200] or "Подписка",
                "orderId": order_id, "type": "OneTime"}
        if metadata.get("return_url"):
            body["successRedirectUrl"] = body["failRedirectUrl"] = metadata["return_url"]
        out = await self._call("POST", "/links", json=body)
        if not out.get("id") or not out.get("url"):
            raise PaymentError(f"WATA: {str(out.get('message') or out.get('error') or 'no payment link')[:200]}")
        return {"id": str(out["id"]), "url": out["url"], "status": "pending"}

    async def create(self, amount: Decimal, order_id: str, description: str, return_url: str, method: str = "") -> Dict[str, Any]:
        return await self.create_payment(float(amount), settings.default_currency, description, {"order_id": order_id, "return_url": return_url})

    async def get_payment_status(self, payment_id: str) -> Dict[str, Any]:
        return await self._call("GET", f"/links/{payment_id}")

    async def verify_succeeded(self, payment_id: str, expected_amount: Decimal, currency: str, expected_order_id: str | None = None) -> bool:
        if not expected_order_id:
            return False
        out = await self._call("GET", "/transactions", params={"orderId": expected_order_id, "statuses": "Paid", "skipCount": 0, "maxResultCount": 20})
        want = Decimal(str(expected_amount)).quantize(Decimal("0.01"))
        for item in out.get("items") or []:
            if str(item.get("status")) != "Paid" or str(item.get("orderId") or expected_order_id) != expected_order_id:
                continue
            if str(item.get("currency") or currency).upper() != str(currency).upper():
                continue
            if Decimal(str(item.get("amount") or "0")).quantize(Decimal("0.01")) == want:
                return True
        return False

    async def probe(self) -> str:
        return await common.probe_http("GET", self.API_URL + "/transactions", params={"skipCount": 0, "maxResultCount": 1},
                                       headers={"Authorization": f"Bearer {settings.wata_access_token}"})

    async def verify_webhook_async(self, headers, body: bytes) -> Dict[str, Any]:
        got = {k.lower(): v for k, v in dict(headers).items()}.get("x-signature", "").strip()
        if not self.configured() or not got:
            raise SignatureVerificationError("Invalid WATA signature")
        key = await self.public_key()
        if not key or not _rsa_verify(key, body, got, sha512=True):
            raise SignatureVerificationError("Invalid WATA signature")
        try:
            return json.loads(body)
        except ValueError as exc:
            raise SignatureVerificationError("Invalid WATA body") from exc

    def verify_webhook(self, headers, body: bytes, remote_addr: str | None = None) -> Dict[str, Any]:
        cached = WataProvider._key
        got = {k.lower(): v for k, v in dict(headers).items()}.get("x-signature", "").strip()
        if not cached or not got or not _rsa_verify(cached[1], body, got, sha512=True):
            raise SignatureVerificationError("Invalid WATA signature")
        return json.loads(body)


@router.post("/api/webhooks/wata")
async def wata_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    raw = await request.body()
    if len(raw) > 64 * 1024:
        raise HTTPException(413, "Payload too large")
    provider = WataProvider()
    try:
        data = await provider.verify_webhook_async(request.headers, raw)
    except SignatureVerificationError:
        raise HTTPException(403, "Invalid signature")
    order_id = str(data.get("orderId") or "")
    if str(data.get("transactionStatus") or "") != "Paid" or not order_id:
        return {"status": "ok"}
    await _settle(db, "wata", provider, order_id, f"paid:{data.get('transactionId') or order_id}", data.get("amount"))
    return {"status": "ok"}
