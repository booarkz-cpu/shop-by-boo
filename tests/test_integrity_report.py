"""v28.59.0 (stage 5, TECH-03): the integrity report finds rows whose customer, subscription, payment or plan is gone.

Foreign keys are not added yet: real installations may hold such rows, and a key would refuse the
migration. The report is the read-only first step and is shown in «Аналитика → Запуск и оповещения»."""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import integrity
from app.models import Base, Payment, Plan, Subscription, User
from app.security import require_permission
from test_subscription_commerce import database  # noqa: F401

ADMIN = SimpleNamespace(email="root@example.test", role="admin")


def test_relations_name_real_tables_and_columns():
    tables = Base.metadata.tables
    for child, column, parent, _ in integrity.RELATIONS:
        assert column in tables[child].c and parent in tables, (child, column, parent)


@pytest.mark.asyncio
async def test_orphans_are_counted_with_sample_ids(database):
    db = database
    clean = await integrity.integrity(db, ADMIN)
    baseline = {(c["table"], c["column"]): c["orphans"] for c in clean["checks"]}
    db.add(User(id=9101, referral_code="INTEG1"))
    db.add(Plan(id=9101, name="Integrity", price=1, duration_days=30))
    await db.flush()
    db.add(Subscription(id=9101, user_id=9101, plan_id=9101))
    db.add(Subscription(id=9102, user_id=9999999, plan_id=9101))  # its customer is gone
    db.add(Payment(user_id=9101, subscription_id=8888888, plan_id=9101, provider="sandbox", order_id="integrity-1",
                   amount=1, currency="RUB", status="paid"))  # its subscription is gone
    await db.commit()
    result = await integrity.integrity(db, ADMIN)
    checks = {(c["table"], c["column"]): c for c in result["checks"]}
    assert checks[("subscriptions", "user_id")]["orphans"] == baseline[("subscriptions", "user_id")] + 1
    assert 9102 in checks[("subscriptions", "user_id")]["sample_ids"]
    assert checks[("payments", "subscription_id")]["orphans"] == baseline[("payments", "subscription_id")] + 1
    assert checks[("subscriptions", "plan_id")]["orphans"] == baseline[("subscriptions", "plan_id")]
    assert result["ok"] is False and result["orphans"] >= 2


@pytest.mark.asyncio
async def test_only_diagnostics_permission_reads_the_report():
    check = require_permission("ops.diagnostics")
    with pytest.raises(HTTPException) as refused:
        await check(admin=SimpleNamespace(role="viewer"))
    assert refused.value.status_code == 403
