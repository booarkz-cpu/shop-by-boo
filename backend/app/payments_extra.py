"""More payment gateways: CloudPayments and Lava (v28.38), Pal24 and Mulen Pay (v28.39), WATA and Antilopay (v28.40), AuraPay and Anore (v28.41), Cashera and ParityPay (v28.43).

Both follow the shop's rule for reserve gateways: a notification is trusted only when its signature is right **and**
the gateway's own API, asked again, says the order is paid with the same amount and currency — only then is the
subscription delivered. No recurring charges and no refunds through the API (refunds are made in the gateway's
dashboard and recorded by hand). Each gateway joins the gateway queue and the payment methods routing as soon as its
keys are set in «Настройки» (runtime settings, secrets stored encrypted).

**CloudPayments** (cards, SBP): ``POST https://api.cloudpayments.ru/orders/create`` with HTTP Basic (Public ID : API
secret) gives the payment page. The «Pay» notification (``/api/webhooks/cloudpayments``, form body) is signed in
``Content-HMAC`` — base64 HMAC-SHA256 of the raw body with the API secret (``X-Content-HMAC`` — of the URL-decoded
body); the order is re-read with ``POST /payments/find`` (``InvoiceId``). The answer is ``{"code": 0}``.

**Lava** (cards, SBP; api.lava.ru «business»): ``POST /business/invoice/create`` with the JSON body signed in the
``Signature`` header (HMAC-SHA256 hex with the secret key) gives the payment page. The notification
(``/api/webhooks/lava``, JSON) is signed in ``Authorization`` with the additional key — of the raw body or of the
same JSON with sorted keys (Lava does both); the invoice is re-read with ``POST /business/invoice/status``.

**Pal24** (PayPalych: cards, SBP): ``POST https://pal24.pro/api/v1/bill/create`` with ``Authorization: Bearer`` (API
token) gives a bill and its payment page. The Result URL notification (``/api/webhooks/pal24``, form or JSON) carries
``SignatureValue`` = upper-case MD5 of ``OutSum:InvId:token`` (the signature token, else the API token); the bill is
re-read with ``GET /bill/status?id=``.

**Mulen Pay** (cards, SBP): ``POST https://mulenpay.ru/api/v2/payments`` with ``Authorization: Bearer`` (API key) and
``sign`` = SHA-1 of ``currency + amount + shopId + secret key`` gives the payment page. The notification
(``/api/webhooks/mulenpay``, JSON) may carry ``sign`` (SHA-1 of all values in order + secret key): a wrong one is
refused, a missing one is allowed because the payment is always re-read with ``GET /v2/payments/{id}`` (status 3 —
paid) before anything is delivered.

**WATA** (cards, SBP; api.wata.pro H2H): ``POST /links`` with ``Authorization: Bearer`` (access token) gives a payment
link. The notification (``/api/webhooks/wata``, JSON) is signed in ``X-Signature`` — base64 RSA SHA-512 (PKCS#1 v1.5)
of the raw body; the public key comes from ``GET /public-key`` (cached for an hour). The payment is re-read with
``GET /transactions?orderId=&statuses=Paid``.

**Antilopay** (cards, SBP; lk.antilopay.com API v2): every request body is signed with the shop's RSA private key
(``X-Apay-Sign``, SHA-256, with ``X-Apay-Secret-Id``); ``POST /payment/create`` gives the payment page. The callback
(``/api/webhooks/antilopay``) is signed in ``X-Apay-Callback`` with Antilopay's RSA key (the public key from the
project settings); the payment is re-read with ``POST /payment/check``.

**AuraPay** (cards, SBP; app.aurapay.tech): ``POST /invoice/create`` with ``X-ApiKey`` and ``X-ShopId`` gives the
payment page. The notification (``/api/webhooks/aurapay``, JSON) is signed in ``X-SIGNATURE`` — HMAC-SHA256 hex with
secret key #2 of all values in alphabetical order of the keys (null as an empty string); the invoice is re-read with
``POST /invoice/status``. The answer is ``{"status": true}``.

**Anore** (cards, SBP; api.anore.cc v1): ``POST /payments`` with ``Authorization: Bearer`` and the body signed in
``Anore-Signature`` (HMAC-SHA256 hex with the secret key). The notification (``/api/webhooks/anore``) is signed the same
way, with ``Anore-Event`` equal to the body's ``event``; the payment is re-read with ``GET /payments/{id}``.

**Cashera** (cards, SBP; api.cashera.cash v1): ``POST /integration/transactions`` with ``X-Api-Key`` (amounts in kopecks)
gives the payment page. The notification (``/api/webhooks/cashera``) carries the static ``X-Api-Key`` and ``X-Secret``,
compared in constant time; the transaction is re-read with ``GET /integration/transactions/{uuid}``. One-time payments
only: Cashera subscriptions are not used.

**ParityPay** (cards, SBP; api.paritypay.net v2): ``POST /v2/invoice/create`` with ``X-ShopId`` and ``X-SecretKey``
(key #1) gives the payment link. The notification (``/api/webhooks/paritypay``) is signed in ``X-SIGNATURE`` like
AuraPay's (key #2); the invoice is re-read with ``GET /v2/invoice/status?order_id=``.

AuraPay and ParityPay sign the values as the sender wrote them, so the body is parsed with numbers kept as text and
booleans written as ``true``/``false`` (``199`` must not become ``199.0``).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import re
import time
from decimal import Decimal
from typing import Any, Dict
from urllib.parse import parse_qsl, unquote_plus

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import get_db
from .payments import BasePaymentProvider, PaymentError, SignatureVerificationError, _money, _public_client

logger = logging.getLogger("vpnshop.payments_extra")
router = APIRouter()


class CloudPaymentsProvider(BasePaymentProvider):
    API_URL = "https://api.cloudpayments.ru"

    @staticmethod
    def configured() -> bool:
        return bool(settings.cloudpayments_public_id and settings.cloudpayments_api_secret)

    def _auth(self) -> str:
        raw = f"{settings.cloudpayments_public_id}:{settings.cloudpayments_api_secret}".encode()
        return "Basic " + base64.b64encode(raw).decode()

    async def _post(self, path: str, body: dict) -> dict:
        async with _public_client(20) as client:
            r = await client.post(self.API_URL + path, json=body, headers={"Authorization": self._auth()})
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
        async with _public_client(20) as client:
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
        async with _public_client(20) as client:
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
        async with _public_client(20) as client:
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


def _rsa_key(text: str, private: bool):
    """A key from the dashboard: PEM, or base64 of DER (Antilopay gives the latter)."""
    from cryptography.hazmat.primitives import serialization
    raw = (text or "").strip().replace("\\n", "\n")
    if "BEGIN" in raw:
        data = raw.encode()
        return serialization.load_pem_private_key(data, None) if private else serialization.load_pem_public_key(data)
    der = base64.b64decode("".join(raw.split()))
    return serialization.load_der_private_key(der, None) if private else serialization.load_der_public_key(der)


def _rsa_verify(key_text: str, body: bytes, signature_b64: str, sha512: bool) -> bool:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    try:
        _rsa_key(key_text, False).verify(base64.b64decode(signature_b64), body, padding.PKCS1v15(), hashes.SHA512() if sha512 else hashes.SHA256())
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


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
        async with _public_client(20) as client:
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
        async with _public_client(20) as client:
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

    def verify_webhook(self, headers, body: bytes, remote_addr: str | None = None) -> Dict[str, Any]:
        got = {k.lower(): v for k, v in dict(headers).items()}.get("x-apay-callback", "").strip()
        if not self.configured() or not got or not _rsa_verify(settings.antilopay_public_key, body, got, sha512=False):
            raise SignatureVerificationError("Invalid Antilopay signature")
        try:
            return json.loads(body)
        except ValueError as exc:
            raise SignatureVerificationError("Invalid Antilopay body") from exc


def _text_value(value) -> str:
    """A body value as the sender wrote it, for value-concatenation signatures (AuraPay, ParityPay)."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    return str(value)


def _sorted_values_hmac(data: dict, key: str) -> str:
    joined = "".join(_text_value(data[k]) for k in sorted(data))
    return hmac.new(key.encode(), joined.encode(), hashlib.sha256).hexdigest()


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
        async with _public_client(20) as client:
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

    def verify_webhook(self, headers, body: bytes, remote_addr: str | None = None) -> Dict[str, Any]:
        got = {k.lower(): v for k, v in dict(headers).items()}.get("x-signature", "").strip().lower()
        try:
            data = json.loads(body, parse_float=str, parse_int=str)
        except ValueError as exc:
            raise SignatureVerificationError("Invalid AuraPay body") from exc
        if not isinstance(data, dict) or not self.configured() or not got or not hmac.compare_digest(self.signature(data), got):
            raise SignatureVerificationError("Invalid AuraPay signature")
        return data


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
        async with _public_client(20) as client:
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


class CasheraProvider(BasePaymentProvider):
    API_URL = "https://api.cashera.cash/api/v1"
    METHODS = {"sbp": "sbp", "card": "card"}

    @staticmethod
    def configured() -> bool:
        return bool(settings.cashera_api_key and settings.cashera_api_secret)

    async def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        headers = {"X-Api-Key": settings.cashera_api_key, "Accept": "application/json"}
        async with _public_client(20) as client:
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


class ParityPayProvider(BasePaymentProvider):
    API_URL = "https://api.paritypay.net"
    METHODS = {"sbp": "sbp", "card": "card"}

    @staticmethod
    def configured() -> bool:
        return bool(settings.paritypay_shop_id and settings.paritypay_secret_key and settings.paritypay_callback_secret)

    async def _call(self, method: str, path: str, **kwargs) -> dict:
        headers = {"X-ShopId": settings.paritypay_shop_id, "X-SecretKey": settings.paritypay_secret_key, "Accept": "application/json"}
        async with _public_client(20) as client:
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

    def verify_webhook(self, headers, body: bytes, remote_addr: str | None = None) -> Dict[str, Any]:
        got = {k.lower(): v for k, v in dict(headers).items()}.get("x-signature", "").strip().lower()
        try:
            data = json.loads(body, parse_float=str, parse_int=str)
        except ValueError as exc:
            raise SignatureVerificationError("Invalid ParityPay body") from exc
        if not isinstance(data, dict) or not self.configured() or not got or not hmac.compare_digest(_sorted_values_hmac(data, settings.paritypay_callback_secret), got):
            raise SignatureVerificationError("Invalid ParityPay signature")
        return data


async def _settle(db: AsyncSession, provider_name: str, provider, order_id: str, event_id: str, amount: str | None) -> str:
    """The common tail of a verified notification: find the order, check the amount, re-read the gateway, fulfil once."""
    from . import main as shop
    p = await shop.payment_by_provider_or_order(db, provider_name, order_id, order_id)
    if not p:
        return "unknown"
    if p.provider != provider_name:
        raise HTTPException(403, "Order mismatch")
    if amount is not None and Decimal(str(amount)).quantize(Decimal("0.01")) != Decimal(str(p.amount)).quantize(Decimal("0.01")):
        raise HTTPException(403, "Amount mismatch")
    if not await provider.verify_succeeded(p.provider_payment_id or order_id, Decimal(str(p.amount)), p.currency, p.order_id):
        raise HTTPException(503, "Payment verification unavailable")
    if not await shop.register_provider_event(db, provider_name, event_id, p.id):
        await db.rollback()
        return "duplicate"
    await db.commit()
    try:
        await shop._confirm_and_fulfill_payment(p.id, db)
        async with AsyncSession(shop.engine, expire_on_commit=False) as edb:
            await shop.finish_provider_event(edb, provider_name, event_id, ok=True)
            await edb.commit()
    except Exception as exc:
        async with AsyncSession(shop.engine, expire_on_commit=False) as edb:
            await shop.finish_provider_event(edb, provider_name, event_id, ok=False, error=str(exc))
            await edb.commit()
        raise
    return "paid"


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
    await _settle(db, "cloudpayments", provider, order_id, f"pay:{data.get('TransactionId') or order_id}", data.get("Amount"))
    return JSONResponse({"code": 0})


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
