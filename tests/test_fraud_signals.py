"""Fraud scan creates one open signal per user and kind; decisions are recorded."""
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app import main
from app.models import AuditLog, FraudSignal, Payment
from test_subscription_commerce import database

ADMIN = SimpleNamespace(email="root@example.test")


def _payment(i, user_id=7, fulfillment="completed"):
    return Payment(user_id=user_id, plan_id=1, provider="yookassa", order_id=f"fraud-{user_id}-{i}",
                   amount=Decimal("100"), currency="RUB", status="paid", fulfillment_status=fulfillment,
                   created_at=datetime.utcnow())


@pytest.mark.asyncio
async def test_scan_does_not_duplicate_open_signals(database):
    database.add_all([_payment(i) for i in range(10)] + [_payment(100 + i, user_id=8, fulfillment="failed") for i in range(3)])
    await database.commit()
    first = await main.fraud_scan(database, ADMIN)
    assert first == {"created": 2}
    again = await main.fraud_scan(database, ADMIN)
    assert again == {"created": 0}
    kinds = sorted((await database.execute(select(FraudSignal.kind))).scalars().all())
    assert kinds == ["fulfillment_failure_velocity", "payment_velocity"]


@pytest.mark.asyncio
async def test_decision_closes_signal_and_rescan_reopens_after_resolution(database):
    database.add_all([_payment(i) for i in range(10)])
    await database.commit()
    await main.fraud_scan(database, ADMIN)
    signal = (await database.execute(select(FraudSignal))).scalar_one()
    result = await main.fraud_decision(signal.id, main.FraudDecisionIn(status="resolved", note="family purchases"), database, ADMIN)
    assert result == {"ok": True, "status": "resolved"}
    rows = await main.admin_fraud(database, ADMIN)
    assert rows[0]["status"] == "resolved" and rows[0]["resolved_at"] is not None
    audit = (await database.execute(select(AuditLog).where(AuditLog.action == "fraud.signal.updated"))).scalar_one()
    assert audit.details == "family purchases"
    # A resolved signal no longer blocks a new one if the pattern continues.
    assert await main.fraud_scan(database, ADMIN) == {"created": 1}
    assert (await database.execute(select(func.count()).select_from(FraudSignal))).scalar() == 2
