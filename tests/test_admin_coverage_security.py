"""Stage 18 (docs/ru/new/ADMIN_VERIFICATION.md): changing admin routes of «Безопасность», «Мониторинг», «Логи»,
«Автоматизация», «Рефералы»."""
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app import admin_api, automation, error_log, notifications_status_api, operations_api, payment_fraud, recovery_api, referral_program
from app import main as shop
from app.models import AdminUser, Campaign, Job, StatusComponent, SystemErrorLog
from test_subscription_commerce import database  # noqa: F401


async def owner(db):
    me = AdminUser(email="owner@corgi.test", password_hash="x", role="admin")
    db.add(me)
    await db.commit()
    return me


@pytest.mark.asyncio
async def test_administrators_and_the_last_active_admin(database):
    db = database
    me = await owner(db)
    made = await admin_api.create_admin(admin_api.AdminUserIn(email=" Ops@Corgi.Test ", password="long-enough-password", role="operator"), db, me)
    ops = await db.get(AdminUser, made["id"])
    assert ops.email == "ops@corgi.test" and ops.password_hash != "long-enough-password"
    with pytest.raises(HTTPException) as err:
        await admin_api.create_admin(admin_api.AdminUserIn(email="ops@corgi.test", password="long-enough-password"), db, me)
    assert err.value.status_code == 409
    with pytest.raises(HTTPException) as err:  # v28.77.0: the only active admin cannot demote themselves
        await admin_api.update_admin(me.id, admin_api.AdminUserIn(email=me.email, role="viewer"), db, me)
    assert err.value.status_code == 409
    await admin_api.update_admin(ops.id, admin_api.AdminUserIn(email=ops.email, role="admin"), db, me)
    await admin_api.update_admin(me.id, admin_api.AdminUserIn(email=me.email, role="viewer"), db, me)  # now there is another admin
    await db.refresh(me)
    assert me.role == "viewer"
    with pytest.raises(HTTPException) as err:  # …and that one is now the last
        await admin_api.delete_admin(ops.id, db, me)
    assert err.value.status_code == 409
    with pytest.raises(HTTPException) as err:
        await admin_api.delete_admin(me.id, db, me)
    assert err.value.status_code == 400, "nobody deletes themselves"


@pytest.mark.asyncio
async def test_incident_mode_and_payment_rules(database):
    me = await owner(database)
    assert await recovery_api.security_incident(shop.IncidentIn(enabled=True, severity="critical", reason="leak"), database, me) == {"ok": True, "enabled": True}
    assert await shop.get_setting(database, "incident_mode") == "1"
    await recovery_api.security_incident(shop.IncidentIn(enabled=False, reason="fixed"), database, me)
    assert await shop.get_setting(database, "incident_mode") == "0"
    out = await payment_fraud.put_rules(payment_fraud.RulesIn(block_ips=[" 203.0.113.9 ", "203.0.113.9", ""], block_emails=["A@x.test"]), database, me)
    assert out["block_ips"] == ["203.0.113.9"] and out["block_emails"] == ["a@x.test"]


@pytest.mark.asyncio
async def test_status_components_errors_campaigns_jobs(database):
    db = database
    me = await owner(db)
    made = await notifications_status_api.admin_status_component_create(shop.StatusComponentIn(slug="api", name="API"), db, me)
    with pytest.raises(HTTPException) as err:
        await notifications_status_api.admin_status_component_create(shop.StatusComponentIn(slug="api", name="API 2"), db, me)
    assert err.value.status_code == 409
    await notifications_status_api.admin_status_component_update(made["id"], shop.StatusComponentIn(slug="api", name="API", status="degraded", message="медленно"), db, me)
    row = await db.get(StatusComponent, made["id"])
    await db.refresh(row)
    assert row.status == "degraded"

    err_row = SystemErrorLog(fingerprint="f" * 64, level="ERROR", logger="app", message="boom")
    db.add(err_row)
    await db.commit()
    assert await error_log.resolve_error(err_row.id, db, me) == {"ok": True}
    await db.refresh(err_row)
    assert err_row.resolved is True

    draft = Campaign(name="Осень", status="draft")
    running = Campaign(name="Идёт", status="running")
    db.add_all([draft, running])
    await db.commit()
    with pytest.raises(HTTPException) as err:
        await automation.delete_campaign(running.id, db, me)
    assert err.value.status_code == 409, "a campaign being sent is not deleted"
    assert await automation.delete_campaign(draft.id, db, me) == {"ok": True}

    job = Job(job_key="fulfill:1", kind="fulfill", status="failed", attempts=8, error="timeout")
    db.add(job)
    await db.commit()
    assert await operations_api.retry_job(job.id, db, me) == {"ok": True}
    await db.refresh(job)
    assert job.status == "queued" and job.error is None


@pytest.mark.asyncio
async def test_referral_program_levels(database):
    me = await owner(database)
    out = await referral_program.set_program(referral_program.ProgramIn(percentages=[Decimal("10"), Decimal("5")]), database, me)
    assert out["percentages"] == ["10", "5"]
    assert (await referral_program.get_program(database, me))["percentages"] == ["10", "5"]
    assert select  # imported for symmetry with the other coverage files
