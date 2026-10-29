"""Extra payment gateways, one module each (v28.45), and the table of what each can do.

``GATEWAYS`` is the single place to look at a gateway: its class, the keys it needs, where notifications come, how a
notification is checked and how the payment is re-read before delivery, and whether refunds and recurring charges go
through the API. The routing maps (gateway queue, recovery, schedulers, operator alerts) are built from it, so a new
gateway is one module plus one line here; ``payment_policy`` and ``payment_methods`` keep their literal lists, and a
test checks they agree with this table.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..config import settings
from .anore import AnoreProvider
from .antilopay import AntilopayProvider
from .aurapay import AuraPayProvider
from .cashera import CasheraProvider
from .cloudpayments import CloudPaymentsProvider
from .lava import LavaProvider
from .mulenpay import MulenPayProvider
from .pal24 import Pal24Provider
from .paritypay import ParityPayProvider
from .wata import WataProvider


@dataclass(frozen=True)
class Gateway:
    name: str
    title: str
    cls: type
    keys: tuple[str, ...]
    signature: str
    recheck: str
    methods: frozenset = field(default_factory=lambda: frozenset({"sbp", "card"}))
    refunds: bool = False
    recurring: bool = False
    since: str = ""

    @property
    def webhook(self) -> str:
        return f"/api/webhooks/{self.name}"

    def configured(self) -> bool:
        return bool(self.cls.configured())

    def missing_keys(self) -> list[str]:
        return [k.upper() for k in self.keys if not getattr(settings, k, "")]


GATEWAYS: dict[str, Gateway] = {g.name: g for g in (
    Gateway("cloudpayments", "CloudPayments", CloudPaymentsProvider, ("cloudpayments_public_id", "cloudpayments_api_secret"),
            "Content-HMAC (HMAC-SHA256, base64)", "POST /payments/find", since="v28.38"),
    Gateway("lava", "Lava", LavaProvider, ("lava_shop_id", "lava_secret_key", "lava_webhook_secret"),
            "Authorization (HMAC-SHA256)", "POST /business/invoice/status", since="v28.38"),
    Gateway("pal24", "Pal24", Pal24Provider, ("pal24_shop_id", "pal24_api_token"),
            "SignatureValue (MD5)", "GET /bill/status", since="v28.39"),
    Gateway("mulenpay", "Mulen Pay", MulenPayProvider, ("mulenpay_shop_id", "mulenpay_api_key", "mulenpay_secret_key"),
            "sign (SHA-1), повторное чтение обязательно", "GET /v2/payments/{id}", since="v28.39"),
    Gateway("wata", "WATA", WataProvider, ("wata_access_token",),
            "X-Signature (RSA SHA-512)", "GET /transactions?orderId=", since="v28.40"),
    Gateway("antilopay", "Antilopay", AntilopayProvider, ("antilopay_project_id", "antilopay_secret_id", "antilopay_private_key", "antilopay_public_key"),
            "X-Apay-Callback (RSA SHA-256)", "POST /payment/check", since="v28.40"),
    Gateway("aurapay", "AuraPay", AuraPayProvider, ("aurapay_shop_id", "aurapay_api_key", "aurapay_secret_key"),
            "X-SIGNATURE (HMAC-SHA256 значений)", "POST /invoice/status", since="v28.41"),
    Gateway("anore", "Anore", AnoreProvider, ("anore_api_key", "anore_secret_key"),
            "Anore-Signature (HMAC-SHA256) + Anore-Event", "GET /payments/{id}", since="v28.41"),
    Gateway("cashera", "Cashera", CasheraProvider, ("cashera_api_key", "cashera_api_secret"),
            "X-Api-Key + X-Secret", "GET /integration/transactions/{uuid}", since="v28.43"),
    Gateway("paritypay", "ParityPay", ParityPayProvider, ("paritypay_shop_id", "paritypay_secret_key", "paritypay_callback_secret"),
            "X-SIGNATURE (HMAC-SHA256 значений)", "GET /v2/invoice/status", since="v28.43"),
)}


def factories() -> dict[str, type]:
    return {g.name: g.cls for g in GATEWAYS.values()}


def instances() -> dict:
    return {g.name: g.cls() for g in GATEWAYS.values()}


def configured_map() -> dict[str, bool]:
    return {g.name: g.configured() for g in GATEWAYS.values()}


__all__ = ["GATEWAYS", "Gateway", "factories", "instances", "configured_map", "AnoreProvider", "AntilopayProvider", "AuraPayProvider",
           "CasheraProvider", "CloudPaymentsProvider", "LavaProvider", "MulenPayProvider", "Pal24Provider", "ParityPayProvider", "WataProvider"]
