"""REQ-ADMIN-0011: a plan change records the result and only the fields that moved."""
import json
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app import admin_api
from app import main as shop
from app.models import AuditLog, Plan
from test_subscription_commerce import database  # noqa: F401

ADMIN = SimpleNamespace(email="root@example.test", role="admin")


@pytest.mark.asyncio
async def test_plan_update_records_the_result_and_only_changed_fields(database):
    plan = Plan(name="Базовый", price=Decimal("100.00"), duration_days=30, enabled=True, family_seats=0)
    database.add(plan)
    await database.commit()
    await database.refresh(plan)
    token = shop._REQUEST_ID.set("req-plan")
    try:
        payload = shop.PlanIn(name="Базовый", price=Decimal("120.00"), duration_days=30, enabled=True, family_seats=0)
        await admin_api.admin_update_plan(plan.id, payload, database, ADMIN)
    finally:
        shop._REQUEST_ID.reset(token)
    row = await database.scalar(select(AuditLog).where(AuditLog.action == "plan.updated"))
    body = json.loads(row.details)
    assert row.actor == ADMIN.email and row.target == str(plan.id) and row.request_id == "req-plan"
    assert body["result"] == "ok"
    assert body["changes"] == [{"field": "price", "before": "100.00", "after": "120.00"}]
    assert plan.price == Decimal("120.00")
    shown = (await admin_api.admin_audit(1, 50, database, ADMIN))[0]
    assert shown["result"] == "ok" and shown["changes"] == body["changes"] and shown["request_id"] == "req-plan"


@pytest.mark.asyncio
async def test_secret_fields_change_without_their_values(database):
    await shop.audit(
        database, "admin.updated", "a@b.c", "9", result="ok",
        before={"password": "old-secret-value", "role": "operator"},
        after={"password": "new-secret-value", "role": "admin"},
    )
    await database.commit()
    row = await database.scalar(select(AuditLog).where(AuditLog.action == "admin.updated"))
    assert "old-secret-value" not in row.details and "new-secret-value" not in row.details
    assert json.loads(row.details)["changes"] == [
        {"field": "password", "before": "unavailable", "after": "unavailable"},
        {"field": "role", "before": "operator", "after": "admin"},
    ]


@pytest.mark.asyncio
async def test_audit_without_a_diff_keeps_the_old_details(database):
    await shop.audit(database, "plan.created", "a@b.c", "1", {"price": Decimal("10.00")})
    await database.commit()
    row = await database.scalar(select(AuditLog).where(AuditLog.action == "plan.created"))
    assert json.loads(row.details) == {"price": "10.00"}
