"""Overpay hosted card checkout. Card data stays on the provider's payment page."""
from __future__ import annotations

import base64
import hmac
import json
import re
from dataclasses import dataclass
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

import httpx
from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import get_db
from ..payments import BasePaymentProvider, PaymentError, SignatureVerificationError
from . import common


@dataclass(frozen=True)
class PaidCard:
    order: str
    uid: str
    amount: int
    currency: str


def _token(value) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,255}", value) is not None


def _minor_units(amount) -> int:
    rubles = Decimal(str(amount))
    kopecks = rubles * 100
    if not kopecks.is_finite() or kopecks <= 0 or kopecks != kopecks.to_integral_value():
        raise ValueError("Invalid RUB amount")
    return int(kopecks)


def _card(data: dict, order_id) -> PaidCard:
    uid, amount, currency = data.get("uid"), data.get("amount"), data.get("currency")
    if not isinstance(uid, str) or not (0 < len(uid) <= 240):
        raise ValueError("Missing transaction UID")
    if not isinstance(order_id, str) or not (0 < len(order_id) <= 255):
        raise ValueError("Missing merchant order ID")
    if type(amount) is not int or amount <= 0 or currency != "RUB":
        raise ValueError("Unexpected amount or currency")
    return PaidCard(order_id, uid, amount, currency)


def _checkout_payment(data: dict) -> PaidCard | None:
    if data.get("transaction_type") != "payment" or data.get("status") != "successful":
        return None
    if (data.get("test") is not settings.overpay_test_mode or data.get("finished") is not True
            or str(data.get("shop_id")) != settings.overpay_shop_id or not _token(data.get("token"))):
        raise ValueError("Unexpected checkout identity or environment")
    order = data.get("order")
    response = data.get("gateway_response")
    payment = response.get("payment") if isinstance(response, dict) else None
    if not isinstance(order, dict) or not isinstance(payment, dict):
        raise ValueError("Missing order or confirmed card transaction")
    if payment.get("type") != "payment" or payment.get("status") != "successful":
        return None
    card = _card(payment, order.get("tracking_id"))
    if type(order.get("amount")) is not int or (order["amount"], order.get("currency")) != (card.amount, card.currency):
        raise ValueError("Order and transaction differ")
    return card


class OverpayProvider(BasePaymentProvider):
    CHECKOUT = "https://checkout.overpay.io/ctp/api/checkouts"

    @staticmethod
    def configured() -> bool:
        return bool(settings.overpay_shop_id.isascii() and settings.overpay_shop_id.isdecimal()
                    and settings.overpay_secret_key and settings.overpay_public_key
                    and settings.default_currency == "RUB" and settings.webhook_base_url
                    and (not settings.overpay_test_mode or settings.app_env.lower() in {"test", "testing", "dev", "development", "local", "staging"}))

    @staticmethod
    def _auth() -> tuple[str, str]:
        return settings.overpay_shop_id, settings.overpay_secret_key

    async def create_payment(self, amount, currency, description, metadata):
        order = metadata.get("order_id")
        if not self.configured() or currency != "RUB" or not isinstance(order, str) or not order:
            raise PaymentError("Overpay requires a configured RUB shop and an order ID")
        options = {"notification_url": settings.webhook_base_url.rstrip("/") + "/api/webhooks/overpay"}
        if metadata.get("return_url"):
            options["return_url"] = metadata["return_url"]
        payload = {"checkout": {"test": settings.overpay_test_mode, "transaction_type": "payment", "attempts": 1,
                                "order": {"tracking_id": order, "amount": _minor_units(amount), "currency": currency,
                                          "description": description or "Подписка"},
                                "settings": options, "payment_method": {"types": ["credit_card"]}}}
        try:
            async with common._public_client(20) as client:
                response = await client.post(self.CHECKOUT, auth=self._auth(), json=payload, headers={"Accept": "application/json"})
                response.raise_for_status()
                checkout = response.json()["checkout"]
                token, destination = checkout["token"], checkout["redirect_url"]
                url = urlsplit(destination)
                valid_url = (url.scheme == "https" and url.netloc == "checkout.overpay.io"
                             and parse_qs(url.query).get("token") == [token])
                if not _token(token) or not valid_url:
                    raise ValueError("Unexpected checkout redirect")
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise PaymentError("Overpay checkout could not be confirmed") from exc
        return {"id": token, "url": destination, "status": "pending"}

    async def create(self, amount: Decimal, order_id: str, description: str, return_url: str, method: str = ""):
        if method not in ("", "card"):
            raise PaymentError("Overpay hosted checkout supports the card method")
        return await self.create_payment(amount, settings.default_currency, description, {"order_id": order_id, "return_url": return_url})

    async def get_payment_status(self, payment_id: str) -> dict:
        if not self.configured() or not _token(payment_id):
            raise PaymentError("Invalid Overpay checkout")
        try:
            async with common._public_client(15) as client:
                response = await client.get(f"{self.CHECKOUT}/{payment_id}", auth=self._auth(), headers={"Accept": "application/json"})
                response.raise_for_status()
                data = response.json()["checkout"]
                if not isinstance(data, dict) or data.get("token") != payment_id:
                    raise ValueError("Checkout token mismatch")
                return data
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            # A status URL contains the checkout bearer token. Keep it out of the payment journal.
            raise PaymentError("Overpay status is unavailable") from None

    async def verified_payment(self, token: str, expected_amount: Decimal, currency: str, order_id: str | None) -> PaidCard | None:
        data = await self.get_payment_status(token)
        try:
            payment = _checkout_payment(data)
            if payment and (payment.amount, payment.currency, payment.order) == (_minor_units(expected_amount), currency, order_id):
                return payment
        except ValueError:
            return None
        return None

    async def verify_succeeded(self, payment_id: str, expected_amount: Decimal, currency: str, expected_order_id=None) -> bool:
        return await self.verified_payment(payment_id, expected_amount, currency, expected_order_id) is not None

    async def probe(self) -> str:
        if not self.configured():
            return "магазин Overpay не настроен"
        try:
            async with common._public_client(15) as client:
                response = await client.get(self.CHECKOUT + "/" + "0" * 64, auth=self._auth())
        except httpx.HTTPError:
            return "нет связи с Overpay"
        if response.status_code == 404 or response.is_success:
            return ""
        return f"Overpay вернул HTTP {response.status_code}"

    def verify_webhook(self, headers, body: bytes, remote_addr=None) -> dict:
        if not self.configured():
            raise SignatureVerificationError("Overpay is not configured")
        headers = {k.lower(): v for k, v in headers.items()}
        basic = b"Basic " + base64.b64encode(":".join(self._auth()).encode())
        credentials = headers.get("authorization", "").encode()
        if not hmac.compare_digest(credentials, basic) or not common._rsa_verify(
                settings.overpay_public_key, body, headers.get("content-signature", ""), sha512=False):
            raise SignatureVerificationError("Invalid Overpay webhook credentials")
        data = json.loads(body)
        if not isinstance(data, dict):
            raise ValueError("Invalid Overpay notification")
        return data


@common.router.post("/api/webhooks/overpay")
async def overpay_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    from .. import main as shop

    raw = await request.body()
    if len(raw) > 64 * 1024:
        raise HTTPException(413, "Payload too large")
    provider = OverpayProvider()
    try:
        data = provider.verify_webhook(request.headers, raw)
        token = None
        if "transaction" in data:
            tx = data["transaction"]
            if not isinstance(tx, dict):
                raise ValueError("Invalid card notification")
            if tx.get("type") != "payment" or tx.get("status") != "successful":
                return {"ok": True}
            if tx.get("test") is not settings.overpay_test_mode or tx.get("payment_method_type") != "credit_card":
                raise ValueError("Unexpected notification environment or method")
            notice = _card(tx, tx.get("tracking_id"))
        else:
            checkout = data.get("checkout", data)
            if not isinstance(checkout, dict):
                raise ValueError("Invalid checkout notification")
            notice = _checkout_payment(checkout)
            if notice is None:
                return {"ok": True}
            token = checkout["token"]
    except SignatureVerificationError:
        raise HTTPException(403, "Invalid webhook authentication") from None
    except (ValueError, TypeError):
        raise HTTPException(400, "Invalid Overpay notification") from None

    row = await shop.payment_by_provider_or_order(db, "overpay", None, notice.order)
    if row is None:
        return {"ok": True}
    if (_minor_units(row.amount), row.currency) != (notice.amount, notice.currency):
        raise HTTPException(403, "Payment amount or currency mismatch")
    if token and row.provider_payment_id and token != row.provider_payment_id:
        raise HTTPException(403, "Checkout token mismatch")
    token = row.provider_payment_id or token
    if not token:
        raise HTTPException(503, "Waiting for checkout identity")
    try:
        confirmed = await provider.verified_payment(token, row.amount, row.currency, row.order_id)
    except PaymentError:
        raise HTTPException(503, "Payment verification unavailable") from None
    if notice != confirmed:
        raise HTTPException(503, "Payment verification unavailable")
    await shop.bind_provider_payment_id(db, row, token)
    return {"ok": True, "result": await common.finish_verified_payment(db, row, f"paid:{notice.uid}")}
