"""A refund made in the YooKassa dashboard is verified, recorded once and revokes access."""
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app import main
from app.models import AuditLog, FinancialLedger, Payment, RefundRequest, Subscription
from test_subscription_commerce import database


class Kassa:
    refunds = {}

    async def get_refund(self, refund_id):
        return Kassa.refunds[refund_id]

    async def get_refund_status(self, refund_id):
        return Kassa.refunds[refund_id]["status"]


class Panel:
    disabled = []

    async def disable_user(self, uuid):
        Panel.disabled.append(uuid)


async def paid(db, amount="100"):
    p = Payment(user_id=1, subscription_id=1, plan_id=1, provider="yookassa", provider_payment_id="yk-pay-1", order_id="ext-1",
                amount=Decimal(amount), currency="RUB", status="paid", fulfillment_status="completed", paid_at=datetime.utcnow())
    db.add(p)
    await db.commit()
    return p


@pytest.mark.asyncio
async def test_full_external_refund_revokes_once(database, monkeypatch):
    monkeypatch.setattr(main, "YooKassaProvider", Kassa)
    monkeypatch.setattr(main, "RemnawaveClient", Panel)
    Panel.disabled = []
    p = await paid(database)
    Kassa.refunds = {"rf-1": {"id": "rf-1", "status": "succeeded", "payment_id": "yk-pay-1", "amount": "100.00", "currency": "RUB"}}
    result = await main._external_refund("yookassa", "rf-1", database)
    assert result == {"ok": True, "refund": "refunded"}
    refund = (await database.execute(select(RefundRequest).where(RefundRequest.payment_id == p.id))).scalar_one()
    payment = await database.get(Payment, p.id, populate_existing=True)
    assert refund.status == "refunded" and refund.provider_refund_id == "rf-1" and payment.status == "refunded"
    assert Panel.disabled == ["remote-1"]
    ledger = (await database.execute(select(FinancialLedger).where(FinancialLedger.payment_id == p.id, FinancialLedger.kind == "refund"))).scalars().all()
    assert len(ledger) == 1 and ledger[0].direction == "debit"  # reconciled refunds are ledgered too
    assert (await main._external_refund("yookassa", "rf-1", database)) == {"ok": True, "duplicate": True}
    assert Panel.disabled == ["remote-1"]


@pytest.mark.asyncio
async def test_partial_or_unconfirmed_refund_does_not_revoke(database, monkeypatch):
    monkeypatch.setattr(main, "YooKassaProvider", Kassa)
    monkeypatch.setattr(main, "RemnawaveClient", Panel)
    Panel.disabled = []
    p = await paid(database)
    Kassa.refunds = {"rf-2": {"id": "rf-2", "status": "succeeded", "payment_id": "yk-pay-1", "amount": "30.00", "currency": "RUB"},
                     "rf-3": {"id": "rf-3", "status": "pending", "payment_id": "yk-pay-1", "amount": "100.00", "currency": "RUB"}}
    assert (await main._external_refund("yookassa", "rf-2", database))["partial"] is True
    assert (await main._external_refund("yookassa", "rf-3", database))["ignored"] is True
    payment = await database.get(Payment, p.id, populate_existing=True)
    assert payment.status == "paid" and Panel.disabled == []
    assert await database.scalar(select(func.count()).select_from(RefundRequest)) == 0
    assert await database.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "payment.refund.partial_external")) == 1
