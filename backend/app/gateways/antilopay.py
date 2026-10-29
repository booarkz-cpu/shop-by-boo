"""**Antilopay** (cards, SBP; lk.antilopay.com API v2): every request body is signed with the shop's RSA private key
(``X-Apay-Sign``, SHA-256, with ``X-Apay-Secret-Id``); ``POST /payment/create`` gives the payment page. The callback
(``/api/webhooks/antilopay``) is signed in ``X-Apay-Callback`` with Antilopay's RSA key (the public key from the
project settings); the payment is re-read with ``POST /payment/check``.
"""
from __future__ import annotations

import base64
import json
from decimal import Decimal
from typing import Any, Dict

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import get_db
from ..payments import BasePaymentProvider, PaymentError, SignatureVerificationError, _money
from . import common
from .common import _rsa_key, _rsa_verify, _settle, router


class AntilopayProvider(BasePaymentProvider):
    API_URL = "https://lk.antilopay.com/api/v2"
    METHODS = {"sbp": ["SBP"], "card": ["CARD_RU"]}

    @staticmethod
    def configured() -> bool:
        return bool(settings.antilopay_secret_id and settings.antilopay_private_key and settings.antilopay_public_key and settings.antilopay_project_id)

    @staticmethod
    def sign(body: bytes) -> str:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        return base64.b64encode(_rsa_key(settings.antilopay_private_key, True).sign(body, padding.PKCS1v15(), hashes.SHA256())).decode()

    async def _post(self, path: str, payload: dict) -> dict:
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
        headers = {"Content-Type": "application/json", "Accept": "application/json", "X-Apay-Secret-Id": settings.antilopay_secret_id,
                   "X-Apay-Sign": self.sign(body), "X-Apay-Sign-Version": "1"}
        async with common._public_client(20) as client:
            r = await client.post(self.API_URL + path, content=body, headers=headers)
        r.raise_for_status()
        return r.json()

    async def create_payment(self, amount: float, currency: str, description: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        order_id = str(metadata.get("order_id") or "")
        if not order_id or not self.configured():
            raise PaymentError("Antilopay is not configured")
        text = description[:200] or "Подписка"
        payload = {"project_identificator": settings.antilopay_project_id, "amount": float(_money(amount)), "order_id": order_id,
                   "currency": (currency or "RUB").upper(), "product_name": text, "product_type": "services", "description": text,
                   "customer": {"email": str(metadata.get("email") or settings.antilopay_customer_email or "customer@example.com")}}
        if self.METHODS.get(str(metadata.get("method") or "")):
            payload["prefer_methods"] = self.METHODS[str(metadata["method"])]
        if metadata.get("return_url"):
            payload["success_url"] = payload["fail_url"] = metadata["return_url"]
        out = await self._post("/payment/create", payload)
        if out.get("code") not in (0, "0") or not out.get("payment_url"):
            raise PaymentError(f"Antilopay: {str(out.get('error') or out.get('message') or 'no payment page')[:200]}")
        return {"id": str(out.get("payment_id") or order_id), "url": out["payment_url"], "status": "pending"}

    async def create(self, amount: Decimal, order_id: str, description: str, return_url: str, method: str = "") -> Dict[str, Any]:
        return await self.create_payment(float(amount), settings.default_currency, description, {"order_id": order_id, "return_url": return_url, "method": method})

    async def get_payment_status(self, payment_id: str) -> Dict[str, Any]:
        return await self._post("/payment/check", {"project_identificator": settings.antilopay_project_id, "order_id": str(payment_id)})

    async def verify_succeeded(self, payment_id: str, expected_amount: Decimal, currency: str, expected_order_id: str | None = None) -> bool:
        data = await self.get_payment_status(expected_order_id or payment_id)
        if str(data.get("status") or "").upper() != "SUCCESS":
            return False
        if expected_order_id and data.get("order_id") not in (None, "", expected_order_id):
            return False
        paid = data.get("original_amount") if data.get("original_amount") is not None else data.get("amount")
        return Decimal(str(paid or "0")).quantize(Decimal("0.01")) == Decimal(str(expected_amount)).quantize(Decimal("0.01"))

    async def probe(self) -> str:
        body = json.dumps({"project_identificator": settings.antilopay_project_id, "order_id": "probe"}, separators=(",", ":")).encode()
        try:
            sign = self.sign(body)
        except Exception:  # noqa: BLE001 — a key that does not load is the problem itself
            return "закрытый ключ не читается"
        return await common.probe_http("POST", self.API_URL + "/payment/check", content=body, headers={
            "Content-Type": "application/json", "X-Apay-Secret-Id": settings.antilopay_secret_id, "X-Apay-Sign": sign, "X-Apay-Sign-Version": "1"})

    def verify_webhook(self, headers, body: bytes, remote_addr: str | None = None) -> Dict[str, Any]:
        got = {k.lower(): v for k, v in dict(headers).items()}.get("x-apay-callback", "").strip()
        if not self.configured() or not got or not _rsa_verify(settings.antilopay_public_key, body, got, sha512=False):
            raise SignatureVerificationError("Invalid Antilopay signature")
        try:
            return json.loads(body)
        except ValueError as exc:
            raise SignatureVerificationError("Invalid Antilopay body") from exc


@router.post("/api/webhooks/antilopay")
async def antilopay_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    raw = await request.body()
    if len(raw) > 64 * 1024:
        raise HTTPException(413, "Payload too large")
    provider = AntilopayProvider()
    try:
        data = provider.verify_webhook(request.headers, raw)
    except SignatureVerificationError:
        raise HTTPException(403, "Invalid signature")
    order_id = str(data.get("order_id") or "")
    if data.get("type") != "payment" or str(data.get("status") or "").upper() != "SUCCESS" or not order_id:
        return {"ok": True}
    await _settle(db, "antilopay", provider, order_id, f"paid:{data.get('payment_id') or order_id}", data.get("original_amount"))
    return {"ok": True}
