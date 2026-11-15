"""**CloudPayments** (cards, SBP): ``POST https://api.cloudpayments.ru/orders/create`` with HTTP Basic (Public ID : API
secret) gives the payment page. The «Pay» notification (``/api/webhooks/cloudpayments``, form body) is signed in
``Content-HMAC`` — base64 HMAC-SHA256 of the raw body with the API secret (``X-Content-HMAC`` — of the URL-decoded
body); the order is re-read with ``POST /payments/find`` (``InvoiceId``). The answer is ``{"code": 0}``.

**Refunds (v28.46).** ``refund`` finds the transaction by the order (``/payments/find``) and returns it with
``POST /payments/refund`` (``TransactionId``, amount), ``X-Request-ID`` = ``refund-<order>`` so a repeated call never
refunds twice. The refund id is ``cp-refund-<TransactionId>``; its state is read back with ``/payments/get``.

**Auto-renew (v28.46).** A card payment's «Pay» notification carries ``Token``. When the customer has auto-renew on, the
token is saved (encrypted) as the customer's renewal method unless a working YooKassa card is already saved. The
auto-renew pass charges it with ``POST /payments/tokens/charge`` (``AccountId`` = customer, ``InvoiceId`` = renewal
order, ``X-Request-ID`` = the order). Recurring payments must be switched on in the CloudPayments contract.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from decimal import Decimal
from typing import Any, Dict
from urllib.parse import parse_qsl, unquote_plus

from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import get_db
from ..payments import BasePaymentProvider, PaymentError, SignatureVerificationError, _money
from . import common
from .common import _settle, router


class CloudPaymentsProvider(BasePaymentProvider):
    API_URL = "https://api.cloudpayments.ru"

    @staticmethod
    def configured() -> bool:
        return bool(settings.cloudpayments_public_id and settings.cloudpayments_api_secret)

    def _auth(self) -> str:
        raw = f"{settings.cloudpayments_public_id}:{settings.cloudpayments_api_secret}".encode()
        return "Basic " + base64.b64encode(raw).decode()

    async def _post(self, path: str, body: dict, request_id: str = "") -> dict:
        headers = {"Authorization": self._auth()}
        if request_id:
            headers["X-Request-ID"] = request_id[:64]  # CloudPayments idempotency: the same id never charges twice
        async with common._public_client(20) as client:
            r = await client.post(self.API_URL + path, json=body, headers=headers)
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

    # ---------------------------------------------------------------- refunds (v28.46)
    async def refund(self, payment_id: str, amount, currency: str, reason: str = "") -> Dict[str, Any]:
        model = await self.get_payment_status(payment_id)
        tx = model.get("TransactionId")
        if not tx or str(model.get("Status") or "") not in {"Completed", "Authorized"}:
            raise PaymentError("CloudPayments: оплаченная транзакция по заказу не найдена")
        out = await self._post("/payments/refund", {"TransactionId": int(tx), "Amount": float(_money(amount))}, request_id=f"refund-{payment_id}")
        if not out.get("Success"):
            raise PaymentError(f"CloudPayments: {str(out.get('Message') or 'возврат не принят')[:200]}")
        return {"id": f"cp-refund-{tx}", "status": "succeeded"}

    async def get_refund_status(self, refund_id: str) -> str:
        tx = str(refund_id).removeprefix("cp-refund-")
        if not tx.isdigit():
            return "unknown"
        out = await self._post("/payments/get", {"TransactionId": int(tx)})
        model = (out or {}).get("Model") or {}
        return "succeeded" if model.get("Refunded") or str(model.get("Status") or "") == "Refunded" else "processing"

    # ---------------------------------------------------------------- auto-renew (v28.46)
    async def charge_recurring(self, amount: Decimal, order_id: str, description: str, token: str) -> Dict[str, Any]:
        # Renewal orders are «auto-renew-<customer id>-…»: the customer id is the CloudPayments AccountId of the token.
        account = order_id.split("-")[2] if order_id.startswith("auto-renew-") else order_id
        if token.startswith("{"):  # saved as {"t": token, "a": AccountId of the first payment}
            saved = json.loads(token)
            token, account = str(saved.get("t") or ""), str(saved.get("a") or account)
        body = {"Amount": float(_money(amount)), "Currency": settings.default_currency, "Token": token, "InvoiceId": order_id,
                "AccountId": account, "Description": description[:200]}
        out = await self._post("/payments/tokens/charge", body, request_id=order_id)
        model = out.get("Model") or {}
        if out.get("Success") and str(model.get("Status") or "") in {"Completed", "Authorized"}:
            return {"id": order_id, "status": "succeeded"}
        if model:  # declined by the bank: Success false with a reason
            return {"id": order_id, "status": "failed", "reason": str(model.get("CardHolderMessage") or model.get("Reason") or "")[:200]}
        raise PaymentError(f"CloudPayments: {str(out.get('Message') or 'списание не принято')[:200]}")

    async def recurring_status(self, payment_id: str) -> str:
        model = await self.get_payment_status(payment_id)
        status = str(model.get("Status") or "")
        return {"Completed": "succeeded", "Authorized": "succeeded", "Declined": "failed", "Cancelled": "canceled"}.get(status, "pending")

    async def find_by_order_id(self, order_id: str, since=None) -> Dict[str, Any] | None:
        model = await self.get_payment_status(order_id)
        return {"id": order_id} if model.get("TransactionId") else None

    async def probe(self) -> str:
        return await common.probe_http("POST", self.API_URL + "/test", json={}, headers={"Authorization": self._auth()})

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
    result = await _settle(db, "cloudpayments", provider, order_id, f"pay:{data.get('TransactionId') or order_id}", data.get("Amount"))
    if result == "paid" and data.get("Token"):
        await save_renewal_token(db, order_id, str(data["Token"]), str(data.get("AccountId") or ""))
    return JSONResponse({"code": 0})


async def save_renewal_token(db: AsyncSession, order_id: str, token: str, account: str = "") -> bool:
    """Keep the card token for auto-renew when the customer wants auto-renew; a working YooKassa card stays first."""
    from .. import main as shop
    p = (await db.execute(shop.select(shop.Payment).where(shop.Payment.order_id == order_id))).scalar_one_or_none()
    if not p or not token or (p.purpose or "subscription") == "topup":
        return False
    user = await db.get(shop.User, p.user_id)
    if not user or not user.auto_renew_enabled:
        return False
    method = (await db.execute(shop.select(shop.AutoRenewMethod).where(shop.AutoRenewMethod.user_id == user.id).with_for_update())).scalar_one_or_none()
    if method and method.provider == "yookassa" and method.enabled and method.status in {"active", "past_due"}:
        return False
    enc = shop.encrypt_secret(json.dumps({"t": token, "a": account or str(user.id)}))
    if method:
        method.provider = "cloudpayments"
        method.external_token_encrypted = enc
        method.enabled = True
        method.status = "active"
        method.failure_count = 0
        method.last_error = None
    else:
        db.add(shop.AutoRenewMethod(user_id=user.id, provider="cloudpayments", external_token_encrypted=enc, enabled=True))
    await shop.audit(db, "auto_renew.method.saved", str(user.id), "cloudpayments", {"order_id": order_id})
    await db.commit()
    return True
