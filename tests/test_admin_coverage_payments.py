"""Stage 18 (docs/ru/new/ADMIN_VERIFICATION.md): changing admin routes of «Платежи»."""
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from starlette.requests import Request

from app import gateway_ops, payment_platform_api, recovery_api
from app import main as shop
from app.models import GiftCard, Payment, PaymentChargeback, PaymentPriceExperiment, PaymentRiskAssessment, RefundRequest
from test_subscription_commerce import database  # noqa: F401

ADMIN = SimpleNamespace(email="owner@corgi.test", role="admin")


def request():
    return Request({"type": "http", "method": "POST", "path": "/", "client": ("203.0.113.5", 1), "query_string": b"", "headers": []})


async def payment(db, order="o-1"):
    p = Payment(user_id=1, plan_id=1, provider="yookassa", order_id=order, amount=Decimal("100"), currency="RUB", status="paid",
                fulfillment_status="completed", purpose="subscription", idempotency_key="idem-" + order)
    db.add(p)
    await db.commit()
    return p


@pytest.mark.asyncio
async def test_gateway_probe_and_auto_priority(database, monkeypatch):
    async def probe_all(db):
        return {"yookassa": "ok"}
    monkeypatch.setattr(gateway_ops, "probe_all", probe_all)
    assert await gateway_ops.probe_now(database, ADMIN) == {"state": {"yookassa": "ok"}}
    with pytest.raises(HTTPException) as err:  # applying needs «Лучшая касса первой» switched on
        await gateway_ops.auto_priority_now(False, database, ADMIN)
    assert err.value.status_code == 409
    calls = []

    async def auto_priority(db, dry_run, actor):
        calls.append((dry_run, actor))
        return {"order": ["yookassa"], "applied": not dry_run}
    monkeypatch.setattr(gateway_ops, "auto_priority", auto_priority)
    assert (await gateway_ops.auto_priority_now(True, database, ADMIN))["applied"] is False and calls == [(True, ADMIN.email)]


@pytest.mark.asyncio
async def test_risk_recheck_chargeback_experiment_refund(database, monkeypatch):
    db = database
    p = await payment(db)

    async def risk(db_, user, amount, req):
        return 12, "allow", {"new_device": False}
    monkeypatch.setattr(shop, "_risk_score", risk)
    assert await payment_platform_api.payment_risk_recheck(p.id, request(), db, ADMIN) == {"score": 12, "decision": "allow", "signals": {"new_device": False}}
    assert (await db.execute(select(PaymentRiskAssessment))).scalar_one().score == 12
    with pytest.raises(HTTPException):
        await payment_platform_api.payment_risk_recheck(999999, request(), db, ADMIN)

    cb = PaymentChargeback(payment_id=p.id, provider="yookassa", external_id="cb-1", amount=Decimal("100"), currency="RUB")
    db.add(cb)
    await db.commit()
    await payment_platform_api.update_chargeback(cb.id, payment_platform_api.ChargebackUpdateIn(status="won", evidence={"doc": "receipt"}), db, ADMIN)
    await db.refresh(cb)
    assert cb.status == "won"

    out = await payment_platform_api.upsert_price_experiment("autumn", payment_platform_api.PriceExperimentIn(key="autumn", rules={"b": 0.9}, enabled=True), db, ADMIN)
    assert out == {"ok": True, "key": "autumn", "enabled": True}
    await payment_platform_api.upsert_price_experiment("autumn", payment_platform_api.PriceExperimentIn(key="autumn", rules={"b": 0.8}), db, ADMIN)
    row = (await db.execute(select(PaymentPriceExperiment))).scalar_one()
    assert row.rules == {"b": 0.8} and row.enabled is False, "the same key is updated, not duplicated"

    r = RefundRequest(payment_id=p.id, user_id=1, amount=Decimal("100"))
    db.add(r)
    await db.commit()
    assert await recovery_api.approve_refund(r.id, db, ADMIN) == {"ok": True, "status": "approved"}
    with pytest.raises(HTTPException) as err:
        await recovery_api.approve_refund(r.id, db, ADMIN)
    assert err.value.status_code == 400, "an approved refund is not approved again"


@pytest.mark.asyncio
async def test_gift_card_in_the_shop_currency_only(database, monkeypatch):
    monkeypatch.setattr(shop.settings, "default_currency", "RUB")
    out = await payment_platform_api.create_gift_card(payment_platform_api.GiftCardCreateIn(value=Decimal("500")), database, ADMIN)
    card = (await database.execute(select(GiftCard))).scalar_one()
    assert out["currency"] == "RUB" == card.currency and len(out["code"]) == 24
    assert card.code_hash != out["code"] and out["code"].startswith(card.code_prefix), "only a hash of the code is stored"
    with pytest.raises(HTTPException) as err:  # v28.77.0: an EUR card in a RUB shop could never be redeemed
        await payment_platform_api.create_gift_card(payment_platform_api.GiftCardCreateIn(value=Decimal("5"), currency="EUR"), database, ADMIN)
    assert err.value.status_code == 400
