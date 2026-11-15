"""Shared parts of the extra gateways (v28.45 package; before that ``payments_extra.py``).

Both follow the shop's rule for reserve gateways: a notification is trusted only when its signature is right **and**
the gateway's own API, asked again, says the order is paid with the same amount and currency — only then is the
subscription delivered. No recurring charges and no refunds through the API (refunds are made in the gateway's
dashboard and recorded by hand). Each gateway joins the gateway queue and the payment methods routing as soon as its
keys are set in «Настройки» (runtime settings, secrets stored encrypted).

``_public_client`` lives here so tests and the probe use one patch point; ``_settle`` is the common tail of a verified
notification.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
from decimal import Decimal

from fastapi import APIRouter, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..payments import _public_client  # noqa: F401 — the one HTTP client factory of all extra gateways

logger = logging.getLogger("vpnshop.gateways")
router = APIRouter()


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


async def _settle(db: AsyncSession, provider_name: str, provider, order_id: str, event_id: str, amount: str | None) -> str:
    """The common tail of a verified notification: find the order, check the amount, re-read the gateway, fulfil once."""
    from .. import main as shop
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


async def probe_http(method: str, url: str, **kwargs) -> str:
    """One cheap authenticated call to a gateway: «» when it answered and accepted the keys, else what is wrong.

    A «not found» for a made-up order is a good answer: the keys were accepted. Refused keys (401/403), gateway errors
    (5xx) and no connection are problems."""
    try:
        async with _public_client(15) as client:
            r = await client.request(method, url, **kwargs)
    except Exception as exc:  # noqa: BLE001 — any transport failure is «no connection»
        return f"нет связи: {type(exc).__name__}"
    code = int(getattr(r, "status_code", 200))
    if code in (401, 403):
        return f"ключи не приняты (HTTP {code})"
    if code >= 500:
        return f"касса отвечает ошибкой (HTTP {code})"
    return ""
