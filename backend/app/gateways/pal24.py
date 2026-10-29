"""**Pal24** (PayPalych: cards, SBP): ``POST https://pal24.pro/api/v1/bill/create`` with ``Authorization: Bearer`` (API
token) gives a bill and its payment page. The Result URL notification (``/api/webhooks/pal24``, form or JSON) carries
``SignatureValue`` = upper-case MD5 of ``OutSum:InvId:token`` (the signature token, else the API token); the bill is
re-read with ``GET /bill/status?id=``.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from decimal import Decimal
from typing import Any, Dict
from urllib.parse import parse_qsl

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import get_db
from ..payments import BasePaymentProvider, PaymentError, SignatureVerificationError, _money
from . import common
from .common import _settle, router


class Pal24Provider(BasePaymentProvider):
    API_URL = "https://pal24.pro/api/v1"
    PAID = {"SUCCESS", "OVERPAID"}
    METHODS = {"sbp": "SBP", "card": "BANK_CARD"}

    @staticmethod
    def configured() -> bool:
        return bool(settings.pal24_api_token and settings.pal24_shop_id)

    @staticmethod
    def signature(out_sum: str, inv_id: str) -> str:
        token = settings.pal24_signature_token or settings.pal24_api_token
        # MD5 and SHA-1 here are fixed by the gateways' protocols, not chosen by the shop.
        return hashlib.md5(f"{out_sum}:{inv_id}:{token}".encode(), usedforsecurity=False).hexdigest().upper()

    async def _call(self, method: str, path: str, **kwargs) -> dict:
        headers = {"Authorization": f"Bearer {settings.pal24_api_token}", "Accept": "application/json"}
        async with common._public_client(20) as client:
            r = await client.request(method, self.API_URL + path, headers=headers, **kwargs)
        r.raise_for_status()
        return r.json()

    async def create_payment(self, amount: float, currency: str, description: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        order_id = str(metadata.get("order_id") or "")
        if not order_id or not self.configured():
            raise PaymentError("Pal24 is not configured")
        body = {"amount": str(_money(amount)), "shop_id": settings.pal24_shop_id, "order_id": order_id, "currency_in": currency or "RUB",
                "type": "normal", "description": description[:200] or "Подписка"}
        if self.METHODS.get(str(metadata.get("method") or "")):
            body["payment_method"] = self.METHODS[str(metadata["method"])]
        if metadata.get("return_url"):
            body["success_url"] = body["fail_url"] = metadata["return_url"]
        out = await self._call("POST", "/bill/create", json=body)
        url = out.get("link_page_url") or out.get("link_url")
        if not out.get("success", True) or not out.get("bill_id") or not url:
            raise PaymentError(f"Pal24: {str(out.get('message') or out.get('error') or 'no payment page')[:200]}")
        return {"id": str(out["bill_id"]), "url": url, "status": "pending"}

    async def create(self, amount: Decimal, order_id: str, description: str, return_url: str, method: str = "") -> Dict[str, Any]:
        return await self.create_payment(float(amount), settings.default_currency, description, {"order_id": order_id, "return_url": return_url, "method": method})

    async def get_payment_status(self, payment_id: str) -> Dict[str, Any]:
        out = await self._call("GET", "/bill/status", params={"id": str(payment_id)})
        return out if out.get("success", True) else {}

    async def verify_succeeded(self, payment_id: str, expected_amount: Decimal, currency: str, expected_order_id: str | None = None) -> bool:
        bill = await self.get_payment_status(payment_id)
        if str(bill.get("status") or "").upper() not in self.PAID:
            return False
        if expected_order_id and bill.get("order_id") not in (None, "", expected_order_id):
            return False
        if str(bill.get("currency_in") or currency).upper() != str(currency).upper():
            return False
        return Decimal(str(bill.get("amount") or "0")).quantize(Decimal("0.01")) >= Decimal(str(expected_amount)).quantize(Decimal("0.01"))

    async def probe(self) -> str:
        return await common.probe_http("GET", self.API_URL + "/merchant/balance", headers={"Authorization": f"Bearer {settings.pal24_api_token}"})

    def verify_webhook(self, headers, body: bytes, remote_addr: str | None = None) -> Dict[str, Any]:
        text = body.decode("utf-8", "replace")
        try:
            data = json.loads(text) if text.lstrip().startswith("{") else dict(parse_qsl(text))
        except ValueError as exc:
            raise SignatureVerificationError("Invalid Pal24 body") from exc
        data = {str(k): str(v) for k, v in data.items()}
        got = data.get("SignatureValue", "")
        if not self.configured() or not got or not hmac.compare_digest(self.signature(data.get("OutSum", ""), data.get("InvId", "")), got.upper()):
            raise SignatureVerificationError("Invalid Pal24 signature")
        return data


@router.post("/api/webhooks/pal24")
async def pal24_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    raw = await request.body()
    if len(raw) > 64 * 1024:
        raise HTTPException(413, "Payload too large")
    provider = Pal24Provider()
    try:
        data = provider.verify_webhook(request.headers, raw)
    except SignatureVerificationError:
        raise HTTPException(403, "Invalid signature")
    order_id = data.get("InvId", "")
    if data.get("Status", "").upper() not in Pal24Provider.PAID or not order_id:
        return {"status": "ok"}  # FAIL and others: nothing to deliver
    await _settle(db, "pal24", provider, order_id, f"paid:{data.get('TrsId') or order_id}", None)
    return {"status": "ok"}
