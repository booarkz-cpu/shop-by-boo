"""
Модуль интеграции с платежными системами.

Провайдеры: YooKassa, Platega, RollyPay.

Безопасность:
- YooKassa: проверка IP-адреса отправителя по allowlist.
- Platega: X-MerchantId / X-Secret по официальному протоколу + API verification.
- RollyPay: HMAC-SHA256 + проверка timestamp.
- Timestamp RollyPay проверяется, но не входит в HMAC тела; replay блокируется
  идемпотентностью события и платежа в обработчике.
- Идемпотентность по event_id в обработчиках провайдеров.
- HTTP-клиент с таймаутами и keep-alive.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from ipaddress import ip_address, ip_network
from typing import Any, Dict, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


def _public_client(timeout_seconds: int):
    """Исходящие запросы к платёжным API идут только через DNS-pinned клиент."""
    from .main import _pinned_public_http_client
    return _pinned_public_http_client(timeout_seconds)


def _money(amount) -> str:
    return f"{Decimal(str(amount)).quantize(Decimal('0.01')):.2f}"


def _currency_matches(data: dict, expected: str) -> bool:
    """Missing or mismatched currency cannot confirm a financial operation."""
    value = data.get("currency") or data.get("Currency")
    return isinstance(value, str) and bool(value.strip()) and value.strip().upper() == str(expected).strip().upper()


def _checkout(data: Dict[str, Any]) -> Dict[str, Any]:
    confirmation = data.get("confirmation") or {}
    url = confirmation.get("confirmation_url") or data.get("url") or data.get("pay_url") or data.get("redirect") or data.get("paymentUrl") or data.get("link")
    payment_id = data.get("id") or data.get("payment_id") or data.get("transactionId") or data.get("transaction_id")
    return {"id": payment_id, "url": url, "status": data.get("status") or data.get("Status")}


# ============================================================
# Исключения
# ============================================================

class PaymentError(Exception):
    """Базовое исключение для ошибок платежных систем."""


class SignatureVerificationError(PaymentError):
    """Ошибка проверки вебхука (подпись или IP)."""


class WebhookReplayError(PaymentError):
    """Ошибка повторного использования вебхука (replay attack)."""


class WebhookAlreadyProcessedError(PaymentError):
    """Вебхук с таким event_id уже был обработан."""


# ============================================================
# Базовый провайдер
# ============================================================

class BasePaymentProvider(ABC):
    """Абстрактный базовый класс для платежных провайдеров."""

    def __init__(self) -> None:
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Клиент с фиксацией DNS. Нельзя открывать прямой httpx.AsyncClient."""
        if self._client is None or self._client.is_closed:
            self._client = _public_client(20)
        return self._client

    async def close(self) -> None:
        """Закрыть HTTP-клиент."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    @abstractmethod
    async def create_payment(
        self,
        amount: float,
        currency: str,
        description: str,
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Создать платеж."""
        raise PaymentError(f"{type(self).__name__} does not implement payment creation")

    @abstractmethod
    async def get_payment_status(self, payment_id: str) -> Dict[str, Any]:
        """Получить статус платежа."""
        raise PaymentError(f"{type(self).__name__} does not implement status lookup")

    @abstractmethod
    def verify_webhook(
        self,
        headers: Dict[str, str],
        body: bytes,
        remote_addr: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Проверить вебхук и вернуть его данные."""
        raise SignatureVerificationError(f"{type(self).__name__} does not implement webhook verification")


# ============================================================
# YooKassa Provider
# ============================================================

class YooKassaProvider(BasePaymentProvider):
    """
    Провайдер YooKassa.

    Проверка вебхука выполняется по IP-адресу отправителя
    (allowlist из настроек) + идемпотентность по event_id.
    """

    def __init__(self) -> None:
        super().__init__()
        self._processed_events: Dict[str, datetime] = {}
        self._event_ttl = timedelta(hours=24)

    async def create_payment(
        self,
        amount: float,
        currency: str,
        description: str,
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        client = await self._get_client()
        # The shop order id is the idempotency key. A lost response must return the
        # same YooKassa payment instead of opening a second charge.
        idempotence_key = str(metadata.get("order_id") or uuid.uuid4())

        payload: Dict[str, Any] = {
            "amount": {"value": f"{amount:.2f}", "currency": currency},
            "capture": True,
            "confirmation": {
                "type": "redirect",
                "return_url": metadata.get(
                    "return_url", settings.public_base_url
                ),
            },
            "description": description,
            "metadata": metadata,
        }

        email = metadata.get("email")
        if email:
            payload["receipt"] = {
                "customer": {"email": email},
                "items": [
                    {
                        "description": description,
                        "quantity": "1.00",
                        "amount": {
                            "value": f"{amount:.2f}",
                            "currency": currency,
                        },
                        "vat_code": 1,
                    }
                ],
            }

        response = await client.post(
            f"{settings.yookassa_api_url}/v3/payments",
            auth=(settings.yookassa_shop_id, settings.yookassa_secret_key),
            headers={
                "Idempotence-Key": idempotence_key,
                "Content-Type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()
        return response.json()

    async def get_payment_status(self, payment_id: str) -> Dict[str, Any]:
        client = await self._get_client()
        response = await client.get(
            f"{settings.yookassa_api_url}/v3/payments/{payment_id}",
            auth=(settings.yookassa_shop_id, settings.yookassa_secret_key),
        )
        response.raise_for_status()
        data = response.json()
        return str(data.get("status") or "")

    async def refund_payment(
        self, payment_id: str, amount: float, currency: str
    ) -> Dict[str, Any]:
        client = await self._get_client()
        payload = {
            "payment_id": payment_id,
            "amount": {"value": f"{amount:.2f}", "currency": currency},
        }
        response = await client.post(
            f"{settings.yookassa_api_url}/v3/refunds",
            auth=(settings.yookassa_shop_id, settings.yookassa_secret_key),
            headers={"Idempotence-Key": str(uuid.uuid4())},
            json=payload,
        )
        response.raise_for_status()
        return response.json()

    def _verify_ip(self, remote_addr: Optional[str]) -> None:
        """Проверить IP-адрес отправителя по allowlist. Пустой список отклоняет вебхук."""
        if not settings.yookassa_webhook_ip_allowlist:
            raise SignatureVerificationError("YooKassa webhook IP allowlist is not configured")
        if not remote_addr:
            raise SignatureVerificationError("Missing remote address for YooKassa webhook")

        allowed = [
            ip_network(n.strip())
            for n in settings.yookassa_webhook_ip_allowlist.split(",")
            if n.strip()
        ]

        try:
            addr = ip_address(remote_addr)
        except ValueError:
            raise SignatureVerificationError(
                f"Некорректный IP: {remote_addr}"
            )

        if not any(addr in net for net in allowed):
            raise SignatureVerificationError(
                f"IP {remote_addr} не входит в allowlist YooKassa"
            )

    def verify_webhook(
        self,
        headers: Dict[str, str],
        body: bytes,
        remote_addr: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Проверить вебхук YooKassa:
        1. IP-адрес (allowlist).
        2. Парсинг JSON.
        3. Идемпотентность по event_id.
        """
        # 1. IP
        self._verify_ip(remote_addr)

        # 2. JSON
        try:
            data = json.loads(body)
        except json.JSONDecodeError as e:
            raise PaymentError(f"Невалидный JSON в вебхуке: {e}")

        # 3. Идемпотентность. Тип события ("payment.succeeded") одинаков у всех
        # уведомлений, поэтому ключом служит уникальный id уведомления или платежа.
        obj = data.get("object") or {}
        event_id = data.get("id") or obj.get("id")
        if event_id:
            self._cleanup_old_events()
            if event_id in self._processed_events:
                raise WebhookAlreadyProcessedError(
                    f"Событие {event_id} уже обработано"
                )
            self._processed_events[event_id] = datetime.now(timezone.utc)

        return data

    def _cleanup_old_events(self) -> None:
        """Удалить старые записи из кэша обработанных событий."""
        now = datetime.now(timezone.utc)
        expired = [
            eid
            for eid, ts in self._processed_events.items()
            if now - ts > self._event_ttl
        ]
        for eid in expired:
            del self._processed_events[eid]

    async def create(self, amount: Decimal, order_id: str, description: str, return_url: str) -> Dict[str, Any]:
        data = await self.create_payment(float(amount), settings.default_currency, description, {"order_id": order_id, "return_url": return_url})
        return _checkout(data)

    async def charge_recurring(self, amount: Decimal, order_id: str, description: str, payment_method_id: str) -> Dict[str, Any]:
        """Повторное списание сохранённым способом оплаты. Idempotence-Key = order_id."""
        payload = {
            "amount": {"value": _money(amount), "currency": settings.default_currency},
            "capture": True,
            "payment_method_id": payment_method_id,
            "description": description,
            "metadata": {"order_id": order_id},
        }
        async with _public_client(10) as client:
            response = await client.post(
                f"{settings.yookassa_api_url}/v3/payments",
                auth=(settings.yookassa_shop_id, settings.yookassa_secret_key),
                headers={"Idempotence-Key": order_id, "Content-Type": "application/json"},
                json=payload,
            )
        response.raise_for_status()
        return _checkout(response.json())

    async def verify_succeeded(self, payment_id: str, expected_amount: Decimal, currency: str, expected_order_id: str|None = None) -> bool:
        async with _public_client(10) as client:
            response = await client.get(
                f"{settings.yookassa_api_url}/v3/payments/{payment_id}",
                auth=(settings.yookassa_shop_id, settings.yookassa_secret_key),
            )
        if response.status_code >= 400:
            return False
        d = response.json()
        paid = str(d.get("status") or "").lower() in {"succeeded", "paid", "success"}
        amount_value = Decimal(str((d.get("amount") or {}).get("value") or "0"))
        currency_ok = str((d.get("amount") or {}).get("currency") or "").upper() == str(currency).upper()
        order = str((d.get("metadata") or {}).get("order_id") or "")
        if expected_order_id and order != expected_order_id:
            return False
        return paid and amount_value == Decimal(str(expected_amount)) and currency_ok

    async def find_by_order_id(self, order_id: str, created_after: datetime | None = None):
        """Find the payment already created for this shop order. Never creates one."""
        params: Dict[str, Any] = {"limit": 100}
        if created_after is not None:
            stamp = created_after if created_after.tzinfo else created_after.replace(tzinfo=timezone.utc)
            params["created_at.gte"] = stamp.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        cursor = None
        async with _public_client(10) as client:
            for _ in range(5):
                query = dict(params)
                if cursor:
                    query["cursor"] = cursor
                response = await client.get(
                    f"{settings.yookassa_api_url}/v3/payments",
                    auth=(settings.yookassa_shop_id, settings.yookassa_secret_key),
                    params=query,
                )
                response.raise_for_status()
                body = response.json()
                for item in body.get("items") or []:
                    if str((item.get("metadata") or {}).get("order_id") or "") == order_id:
                        return item
                cursor = body.get("next_cursor")
                if not cursor:
                    return None
        return None

    async def refund(self, payment_id: str, amount, currency: str, reason: str = "") -> Dict[str, Any]:
        idem=f"refund-{payment_id}"
        async with _public_client(20) as client:
            response = await client.post(
                f"{settings.yookassa_api_url}/v3/refunds",
                auth=(settings.yookassa_shop_id, settings.yookassa_secret_key),
                headers={"Idempotence-Key": idem, "Content-Type": "application/json"},
                json={"payment_id": payment_id, "amount": {"value": _money(amount), "currency": currency}, "description": (reason or "Refund")[:250]},
            )
        response.raise_for_status()
        data = response.json()
        return {"id": data.get("id"), "status": data.get("status")}

    async def get_refund_status(self, refund_id: str) -> str:
        async with _public_client(10) as client:
            response = await client.get(
                f"{settings.yookassa_api_url}/v3/refunds/{refund_id}",
                auth=(settings.yookassa_shop_id, settings.yookassa_secret_key),
            )
        response.raise_for_status()
        return str(response.json().get("status") or "")


# ============================================================
# Platega Provider
# ============================================================

class PlategaProvider(BasePaymentProvider):
    """Провайдер Platega."""

    def __init__(self) -> None:
        super().__init__()

    async def create_payment(
        self,
        amount: float,
        currency: str,
        description: str,
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        client = await self._get_client()
        payload = {
            "paymentDetails": {"amount": amount, "currency": currency},
            "description": description,
            "metadata": metadata,
            "payload": metadata.get("payload") or metadata.get("order_id") or "",
            "return": metadata.get(
                "return_url", settings.public_base_url
            ),
            "failedUrl": metadata.get("return_url", settings.public_base_url),
        }
        response = await client.post(
            f"{settings.platega_api_url.rstrip('/')}/v2/transaction/process",
            headers={
                "X-MerchantId": settings.platega_merchant_id,
                "X-Secret": settings.platega_secret,
                "Content-Type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()
        return response.json()

    async def get_payment_status(self, payment_id: str) -> Dict[str, Any]:
        client = await self._get_client()
        response = await client.get(
            f"{settings.platega_api_url.rstrip('/')}/transaction/{payment_id}",
            headers={
                "X-MerchantId": settings.platega_merchant_id,
                "X-Secret": settings.platega_secret,
            },
        )
        response.raise_for_status()
        data = response.json()
        return str(data.get("status") or data.get("Status") or "")

    async def create(self, amount: Decimal, order_id: str, description: str, return_url: str) -> Dict[str, Any]:
        data = await self.create_payment(float(amount), settings.default_currency, description, {"order_id": order_id, "return_url": return_url, "payload": order_id})
        return _checkout(data)

    async def verify_succeeded(self, payment_id: str, expected_amount: Decimal, currency: str, expected_order_id: str|None = None) -> bool:
        async with _public_client(10) as client:
            response = await client.get(
                f"{settings.platega_api_url}/transaction/{payment_id}",
                headers={"X-MerchantId": settings.platega_merchant_id, "X-Secret": settings.platega_secret},
            )
        if response.status_code >= 400:
            return False
        d = response.json()
        paid = str(d.get("status") or d.get("Status") or "").upper() in {"CONFIRMED", "SUCCESS", "SUCCEEDED", "PAID"}
        details = d.get("paymentDetails") or {}
        amount_value = Decimal(str(details.get("amount") or "0"))
        order = str(d.get("payload") or d.get("Payload") or "")
        if expected_order_id and order != expected_order_id:
            return False
        return paid and amount_value == Decimal(str(expected_amount)) and _currency_matches(details, currency)

    async def refund(self, payment_id: str, amount, currency: str, reason: str = "") -> Dict[str, Any]:
        if not settings.platega_refund_url:
            raise PaymentError("Platega refund URL is not configured")
        idem=f"refund-{payment_id}"
        async with _public_client(20) as client:
            response = await client.post(
                settings.platega_refund_url,
                headers={"X-MerchantId": settings.platega_merchant_id, "X-Secret": settings.platega_secret, "Idempotence-Key": idem},
                json={"id": payment_id, "amount": _money(amount), "currency": currency, "description": reason[:250]},
            )
        response.raise_for_status()
        data = response.json()
        return {"id": data.get("id") or data.get("refund_id") or payment_id, "status": data.get("status") or data.get("Status") or "processing"}

    async def get_refund_status(self, refund_id: str) -> str:
        url = settings.platega_refund_status_url or settings.platega_refund_url
        if not url:
            raise PaymentError("Platega refund status URL is not configured")
        async with _public_client(10) as client:
            response = await client.get(url.rstrip("/") + "/" + refund_id, headers={"X-MerchantId": settings.platega_merchant_id, "X-Secret": settings.platega_secret})
        response.raise_for_status()
        data = response.json()
        return str(data.get("status") or data.get("Status") or "")

    def verify_webhook(self, headers, body, remote_addr=None):
        """Platega's documented callback uses X-MerchantId and X-Secret, not HMAC."""
        lowered = {k.lower(): v for k, v in headers.items()}
        if not verify_platega_headers(lowered.get("x-merchantid"), lowered.get("x-secret")):
            raise SignatureVerificationError("Invalid Platega webhook credentials")
        data = json.loads(body)
        if not isinstance(data, dict):
            raise PaymentError("Invalid Platega event")
        return data


# ============================================================
# RollyPay Provider
# ============================================================

class RollyPayProvider(BasePaymentProvider):
    """Провайдер RollyPay."""

    def __init__(self) -> None:
        super().__init__()

    async def create_payment(
        self,
        amount: float,
        currency: str,
        description: str,
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        client = await self._get_client()
        payload = {
            "amount": _money(amount),
            "payment_currency": currency,
            "description": description,
            "metadata": metadata,
            "redirect_url": metadata.get(
                "return_url", settings.public_base_url
            ),
            "order_id": metadata.get("order_id") or "",
            "test": settings.rollypay_test_mode,
        }
        response = await client.post(
            f"{settings.rollypay_api_url.rstrip('/')}/api/v1/payments",
            headers={
                "X-API-Key": settings.rollypay_api_key,
                "X-Nonce": str(uuid.uuid4()),
                "Content-Type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()
        return response.json()

    async def get_payment_status(self, payment_id: str) -> Dict[str, Any]:
        client = await self._get_client()
        response = await client.get(
            f"{settings.rollypay_api_url.rstrip('/')}/api/v1/payments/{payment_id}",
            headers={
                "X-API-Key": settings.rollypay_api_key,
                "X-Nonce": str(uuid.uuid4()),
            },
        )
        response.raise_for_status()
        data = response.json()
        return str(data.get("status") or "")

    async def create(self, amount: Decimal, order_id: str, description: str, return_url: str) -> Dict[str, Any]:
        data = await self.create_payment(float(amount), settings.default_currency, description, {"order_id": order_id, "return_url": return_url})
        return _checkout(data)

    async def verify_succeeded(self, payment_id: str, expected_amount: Decimal, currency: str, expected_order_id: str|None = None) -> bool:
        async with _public_client(10) as client:
            response = await client.get(
                f"{settings.rollypay_api_url}/api/v1/payments/{payment_id}",
                headers={"X-API-Key": settings.rollypay_api_key, "X-Nonce": str(uuid.uuid4())},
            )
        if response.status_code >= 400:
            return False
        d = response.json()
        paid = str(d.get("status") or "").lower() in {"paid", "success", "succeeded"}
        amount_value = Decimal(str(d.get("amount") or "0"))
        order = str(d.get("order_id") or "")
        if expected_order_id and order != expected_order_id:
            return False
        return paid and amount_value == Decimal(str(expected_amount)) and _currency_matches({"currency": d.get("payment_currency")}, currency)

    async def refund(self, payment_id: str, amount, currency: str, reason: str = "") -> Dict[str, Any]:
        if not settings.rollypay_refund_url:
            raise PaymentError("RollyPay refund URL is not configured")
        nonce=str(uuid.uuid4())
        idem=f"refund-{payment_id}"
        body = json.dumps({"payment_id": payment_id, "amount": _money(amount), "currency": currency, "description": reason[:250]}).encode()
        signature = hmac.new(settings.rollypay_signing_secret.encode(), body, hashlib.sha256).hexdigest()
        async with _public_client(20) as client:
            response = await client.post(
                settings.rollypay_refund_url,
                content=body,
                headers={"Authorization": f"Bearer {settings.rollypay_api_key}", "X-Nonce":nonce, "X-Signature": signature, "Idempotence-Key": idem, "Content-Type": "application/json"},
            )
        response.raise_for_status()
        data = response.json()
        return {"id": data.get("id") or data.get("refund_id") or payment_id, "status": data.get("status") or "processing"}

    async def get_refund_status(self, refund_id: str) -> str:
        url = settings.rollypay_refund_status_url or settings.rollypay_refund_url
        if not url:
            raise PaymentError("RollyPay refund status URL is not configured")
        async with _public_client(10) as client:
            response = await client.get(url.rstrip("/") + "/" + refund_id, headers={"Authorization": f"Bearer {settings.rollypay_api_key}"})
        response.raise_for_status()
        return str(response.json().get("status") or "")

    def verify_webhook(self, headers, body, remote_addr=None):
        lowered = {k.lower(): v for k, v in headers.items()}
        stamp = lowered.get("x-timestamp") or lowered.get("x-rollypay-timestamp") or ""
        signature = lowered.get("x-signature") or lowered.get("x-rollypay-signature") or ""
        if not verify_rollypay(body, stamp, signature):
            raise SignatureVerificationError("Invalid RollyPay signature or timestamp")
        data = json.loads(body)
        if not isinstance(data, dict):
            raise PaymentError("Invalid RollyPay event")
        return data


class SandboxProvider:
    """Local payment provider for tests without live gateways."""

    async def close(self) -> None:
        return None

    async def create(self, amount, order_id: str, description: str, return_url: str):
        from .sandbox_mode import payments_sandbox_allowed
        if not payments_sandbox_allowed():
            raise PaymentError("Sandbox payments are disabled")
        payment_id = f"sandbox-{order_id}"
        url = f"{(settings.cabinet_url or settings.mini_app_url or return_url).rstrip('/')}/?sandbox_payment={payment_id}"
        return {"id": payment_id, "url": url, "status": "succeeded"}

    async def verify_succeeded(self, payment_id: str, expected_amount: Decimal, currency: str, expected_order_id: str | None = None):
        from .sandbox_mode import payments_sandbox_allowed
        if not payments_sandbox_allowed():
            return False
        # Exact id only. A substring of another order id must not count as paid,
        # and a zero amount is not a successful sandbox charge.
        if expected_order_id:
            if str(payment_id) != f"sandbox-{expected_order_id}":
                return False
        elif not str(payment_id).startswith("sandbox-"):
            return False
        try:
            if Decimal(str(expected_amount)) <= 0:
                return False
        except Exception:
            return False
        return True

    async def get_payment_status(self, payment_id: str) -> str:
        from .sandbox_mode import payments_sandbox_allowed
        return "succeeded" if payments_sandbox_allowed() and str(payment_id).startswith("sandbox-") else "canceled"

    async def refund(self, payment_id: str, amount: Decimal, currency: str = "RUB"):
        from .sandbox_mode import payments_sandbox_allowed
        if not payments_sandbox_allowed():
            raise PaymentError("Sandbox payments are disabled")
        return {"id": f"refund-{payment_id}", "status": "succeeded"}

    async def get_refund_status(self, refund_id: str) -> str:
        from .sandbox_mode import payments_sandbox_allowed
        if not payments_sandbox_allowed():
            raise PaymentError("Sandbox payments are disabled")
        return "succeeded"

    async def charge_recurring(self, *args, **kwargs):
        raise PaymentError("Sandbox does not support recurring charges")


# ============================================================
# Фабрика провайдеров
# ============================================================

_providers: Dict[str, BasePaymentProvider] = {}


def get_payment_provider(name: str) -> BasePaymentProvider:
    """Вернуть singleton-провайдер по имени."""
    if name not in _providers:
        if name == "yookassa":
            _providers[name] = YooKassaProvider()
        elif name == "platega":
            _providers[name] = PlategaProvider()
        elif name == "rollypay":
            _providers[name] = RollyPayProvider()
        elif name == "sandbox":
            _providers[name] = SandboxProvider()  # type: ignore[assignment]
        else:
            raise PaymentError(f"Неизвестный провайдер: {name}")
    return _providers[name]


async def close_all_providers() -> None:
    """Закрыть HTTP-клиенты всех провайдеров при остановке."""
    for provider in _providers.values():
        await provider.close()


def verify_platega_headers(merchant_id: str | None, secret: str | None) -> bool:
    if not merchant_id or not secret or not settings.platega_merchant_id or not settings.platega_secret:
        return False
    return hmac.compare_digest(merchant_id, settings.platega_merchant_id) and hmac.compare_digest(secret, settings.platega_secret)


def verify_rollypay(raw: bytes, timestamp: str, signature: str) -> bool:
    if not raw or not timestamp or not signature or not settings.rollypay_signing_secret:
        return False
    try:
        ts = int(timestamp)
    except ValueError:
        return False
    if abs(int(time.time()) - ts) > 300:
        return False
    expected = hmac.new(settings.rollypay_signing_secret.encode(), timestamp.encode() + b"." + raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _staging_paid(status: str) -> bool:
    value = str(status or "").strip().lower()
    return value in {"succeeded", "success", "paid", "confirmed"}


def _staging_refund_done(status: str) -> bool:
    return str(status or "").strip().lower() in {"succeeded", "success", "refunded", "completed"}


async def staging_read_payment(provider: str, creds: Dict[str, Any], payment_id: str, expected_amount: Decimal, expected_order_id: str) -> Dict[str, Any]:
    """Read a staging invoice with the staging credentials. Production settings are not used."""
    from .main import validate_public_url, _pinned_public_http_client
    provider = str(provider)
    api_url = validate_public_url(creds.get("api_url"), allow_empty=False)
    async with _pinned_public_http_client(20) as client:
        if provider == "yookassa":
            response = await client.get(f"{api_url}/v3/payments/{payment_id}", auth=(str(creds.get("shop_id") or ""), str(creds.get("secret_key") or "")))
        elif provider == "platega":
            response = await client.get(f"{api_url}/transaction/{payment_id}", headers={"X-MerchantId": str(creds.get("merchant_id") or ""), "X-Secret": str(creds.get("secret") or "")})
        elif provider == "rollypay":
            response = await client.get(f"{api_url}/api/v1/payments/{payment_id}", headers={"X-API-Key": str(creds.get("api_key") or ""), "X-Nonce": str(uuid.uuid4())})
        else:
            raise PaymentError(f"Неизвестный провайдер: {provider}")
    if response.status_code >= 400:
        return {"paid": False, "status": f"http_{response.status_code}"}
    data = response.json()
    status = str(data.get("status") or data.get("Status") or "")
    details = (data.get("paymentDetails") or {}) if provider == "platega" else {}
    if provider == "yookassa":
        amount_raw = (data.get("amount") or {}).get("value")
    elif provider == "platega":
        amount_raw = details.get("amount")
    else:
        amount_raw = data.get("amount")
    amount_value = Decimal(str(amount_raw if amount_raw is not None else "0"))
    if provider == "yookassa":
        order = str((data.get("metadata") or {}).get("order_id") or "")
        currency_ok = str((data.get("amount") or {}).get("currency") or "").upper() == "RUB"
    elif provider == "platega":
        order = str(data.get("payload") or data.get("Payload") or "")
        currency_ok = _currency_matches(details or {}, "RUB")
    else:
        order = str(data.get("order_id") or "")
        currency_ok = _currency_matches({"currency": data.get("payment_currency")}, "RUB")
    paid = _staging_paid(status) and amount_value == Decimal(str(expected_amount)) and order == expected_order_id and currency_ok
    return {"paid": paid, "status": status, "amount": str(amount_value), "order_id": order}


async def staging_refund_payment(provider: str, creds: Dict[str, Any], payment_id: str, amount: Decimal) -> Dict[str, Any]:
    """Refund a staging invoice with the staging credentials. Production settings are not used."""
    from .main import validate_public_url, _pinned_public_http_client
    provider = str(provider)
    async with _pinned_public_http_client(20) as client:
        if provider == "yookassa":
            api_url = validate_public_url(creds.get("api_url"), allow_empty=False)
            response = await client.post(
                f"{api_url}/v3/refunds",
                auth=(str(creds.get("shop_id") or ""), str(creds.get("secret_key") or "")),
                headers={"Idempotence-Key": f"staging-refund-{payment_id}", "Content-Type": "application/json"},
                json={"payment_id": payment_id, "amount": {"value": _money(amount), "currency": "RUB"}},
            )
        elif provider == "platega":
            refund_url = validate_public_url(creds.get("refund_url"), allow_empty=False)
            response = await client.post(refund_url, headers={"X-MerchantId": str(creds.get("merchant_id") or ""), "X-Secret": str(creds.get("secret") or ""), "Content-Type": "application/json"}, json={"id": payment_id, "amount": _money(amount), "currency": "RUB"})
        elif provider == "rollypay":
            refund_url = validate_public_url(creds.get("refund_url"), allow_empty=False)
            body = json.dumps({"payment_id": payment_id, "amount": _money(amount), "currency": "RUB"}).encode()
            signature = hmac.new(str(creds.get("signing_secret") or "").encode(), body, hashlib.sha256).hexdigest()
            response = await client.post(refund_url, content=body, headers={"Authorization": f"Bearer {creds.get('api_key') or ''}", "X-Signature": signature, "Content-Type": "application/json"})
        else:
            raise PaymentError(f"Неизвестный провайдер: {provider}")
    response.raise_for_status()
    data = response.json()
    status = str(data.get("status") or data.get("Status") or "")
    return {"id": data.get("id") or data.get("refund_id") or payment_id, "status": status, "done": _staging_refund_done(status)}


async def staging_refund_read(provider: str, creds: Dict[str, Any], refund_id: str) -> Dict[str, Any]:
    from .main import validate_public_url, _pinned_public_http_client
    provider = str(provider)
    async with _pinned_public_http_client(20) as client:
        if provider == "yookassa":
            api_url = validate_public_url(creds.get("api_url"), allow_empty=False)
            response = await client.get(f"{api_url}/v3/refunds/{refund_id}", auth=(str(creds.get("shop_id") or ""), str(creds.get("secret_key") or "")))
        elif provider == "platega":
            status_url = validate_public_url(creds.get("refund_status_url") or creds.get("refund_url"), allow_empty=False)
            response = await client.get(str(status_url).rstrip("/") + "/" + refund_id, headers={"X-MerchantId": str(creds.get("merchant_id") or ""), "X-Secret": str(creds.get("secret") or "")})
        elif provider == "rollypay":
            status_url = validate_public_url(creds.get("refund_status_url") or creds.get("refund_url"), allow_empty=False)
            response = await client.get(str(status_url).rstrip("/") + "/" + refund_id, headers={"Authorization": f"Bearer {creds.get('api_key') or ''}"})
        else:
            raise PaymentError(f"Неизвестный провайдер: {provider}")
    if response.status_code >= 400:
        return {"status": f"http_{response.status_code}", "done": False}
    data = response.json()
    status = str(data.get("status") or data.get("Status") or "")
    return {"status": status, "done": _staging_refund_done(status)}


async def staging_create_payment(provider: str, creds: Dict[str, Any], amount: Decimal, order_id: str, description: str, return_url: str) -> Dict[str, Any]:
    """Создать платёж только по переданным staging credentials.

    Production settings are deliberately never consulted.
    """
    from .main import validate_public_url, _pinned_public_http_client
    provider = str(provider)
    if provider == "yookassa":
        api_url = creds.get("api_url")
        api_url = validate_public_url(api_url, allow_empty=False)
        payload = {"amount": {"value": _money(amount), "currency": "RUB"}, "capture": True, "confirmation": {"type": "redirect", "return_url": return_url}, "description": description, "metadata": {"order_id": order_id}}
        auth = (str(creds.get("shop_id") or ""), str(creds.get("secret_key") or ""))
        headers = {"Idempotence-Key": order_id, "Content-Type": "application/json"}
        path = "/v3/payments"
    elif provider == "platega":
        api_url = creds.get("api_url")
        api_url = validate_public_url(api_url, allow_empty=False)
        payload = {"paymentDetails": {"amount": float(amount), "currency": "RUB"}, "description": description, "payload": order_id, "return": return_url, "failedUrl": return_url}
        auth = None
        headers = {"X-MerchantId": str(creds.get("merchant_id") or ""), "X-Secret": str(creds.get("secret") or ""), "Content-Type": "application/json"}
        path = "/v2/transaction/process"
    elif provider == "rollypay":
        api_url = creds.get("api_url")
        api_url = validate_public_url(api_url, allow_empty=False)
        payload = {"amount": _money(amount), "payment_currency": "RUB", "description": description, "order_id": order_id, "redirect_url": return_url}
        payload["test"] = True
        auth = None
        headers = {"X-API-Key": str(creds.get("api_key") or ""), "X-Nonce": str(uuid.uuid4()), "Content-Type": "application/json"}
        path = "/api/v1/payments"
    else:
        raise PaymentError(f"Неизвестный провайдер: {provider}")
    async with _pinned_public_http_client(20) as c:
        response = await c.post(str(api_url).rstrip("/") + path, headers=headers, json=payload, auth=auth)
    response.raise_for_status()
    return _checkout(response.json())
