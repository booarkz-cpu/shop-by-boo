"""20.0.3 audit: unpaid and zero-amount checkouts cannot grant a plan."""
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import HTTPException

from app import main as shop
from test_subscription_commerce import database  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]


def _slice(text: str, start: str, end: str) -> str:
    i = text.index(start)
    return text[i:text.index(end, i)]


@pytest.mark.asyncio
async def test_zero_amount_checkout_is_refused_before_the_gateway(database, monkeypatch):
    from app.models import PromoCode
    from test_behaviour_payments_v2 import checkout
    from test_v44_5_7_deep_regressions import checkout_env
    await checkout_env(database, monkeypatch)
    calls = []

    class Gateway:
        async def create(self, *a, **k):
            calls.append(a)
            return {"id": "yk-free", "url": "https://pay"}
    monkeypatch.setattr(shop, "YooKassaProvider", Gateway)
    database.add(PromoCode(code="FREE100", kind="percent", value=Decimal("100"), enabled=True))
    await database.commit()
    with pytest.raises(HTTPException) as free:
        await shop.create_payment({"plan_id": 1, "provider": "yookassa", "promo_code": "FREE100"}, checkout([(b"idempotency-key", b"free")]), database)
    assert free.value.status_code == 400 and calls == [], "a zero amount never reaches the gateway"


def test_crypto_webhooks_need_a_fresh_signature(monkeypatch):
    import hashlib
    import hmac
    import time

    from app import payment_platform
    monkeypatch.setattr(payment_platform.settings, "crypto_gateway_key", "crypto-key")
    gateway = payment_platform.CryptoGatewayPlatform()
    body, now = b'{"id":"c-1","status":"paid"}', str(int(time.time()))
    good = hmac.new(b"crypto-key", now.encode() + b"." + body, hashlib.sha256).hexdigest()
    assert gateway.verify_webhook(body, now, good)["id"] == "c-1"
    for stamp, sig in ((now, "0" * 64), (str(int(time.time()) - 900), good), ("", good)):
        with pytest.raises(Exception):
            gateway.verify_webhook(body, stamp, sig)
    for cls in (payment_platform.StripePlatform, payment_platform.PayPalPlatform, payment_platform.CryptoGatewayPlatform):
        assert callable(getattr(cls, "verify_succeeded", None)), cls.__name__


@pytest.mark.asyncio
async def test_admin_retry_refuses_an_unpaid_payment(database):
    from types import SimpleNamespace

    from app.models import Payment
    database.add(Payment(id=97, user_id=1, plan_id=1, provider="yookassa", order_id="o-97", amount=Decimal("100"), currency="RUB",
                         status="pending", idempotency_key="k-97"))
    await database.commit()
    with pytest.raises(HTTPException) as unpaid:
        await shop.retry_payment(97, database, SimpleNamespace(email="a@b.c"))
    assert (unpaid.value.status_code, unpaid.value.detail) == (409, "Payment is not confirmed")
