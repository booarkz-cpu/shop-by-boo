"""«Кассы за период»: conversion, revenue and time to pay per gateway; the best one needs enough orders."""
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from app import provider_report
from app.models import Payment
from test_subscription_commerce import database  # noqa: F401


@pytest.mark.asyncio
async def test_each_gateway_is_measured_and_the_best_needs_enough_orders(database):  # noqa: F811
    now = datetime.utcnow()
    n = 0
    for provider, total, paid in (("yookassa", 20, 12), ("rollypay", 10, 9), ("freekassa", 2, 2)):
        for i in range(total):
            n += 1
            created = now - timedelta(days=1, minutes=n)
            database.add(Payment(user_id=1, plan_id=1, provider=provider, order_id=f"r{n}", idempotency_key=f"r{n}", amount=Decimal("100"),
                                 currency="RUB", status="paid" if i < paid else "pending", purpose="subscription",
                                 created_at=created, paid_at=created + timedelta(minutes=4) if i < paid else None))
    database.add(Payment(user_id=1, plan_id=1, provider="yookassa", order_id="old", idempotency_key="old", amount=Decimal("100"),
                         currency="RUB", status="paid", purpose="subscription", created_at=now - timedelta(days=60)))
    await database.commit()
    out = await provider_report.build_report(database, 30, now)
    by = {p["provider"]: p for p in out["providers"]}
    assert by["yookassa"]["orders"] == 20, "older orders are outside the period"
    assert (by["rollypay"]["conversion"], by["rollypay"]["revenue"], by["rollypay"]["median_minutes_to_pay"]) == (90.0, "900.00", 4.0)
    assert out["best"] == "rollypay", "Freekassa's 2 of 2 is too few to call it the best"
