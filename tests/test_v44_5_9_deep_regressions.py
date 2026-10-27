"""v44.5.9: frozen trial terms, device re-activation, provider-event leases and auto-renew retries, checked by
running the code (was: code lines searched in main.py, worker.py and payments.py).
The retry of a lost trial extension is covered by test_integration_billing_vpn.py."""
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from starlette.requests import Request

import worker
from app import main as shop
from app.models import AutoRenewMethod, Payment, Plan, TrialGrant, User
from app_contract import columns
from test_integration_billing_vpn import customer, give_trial, panel  # noqa: F401
from test_money_review import _renewable, _scheduler_env
from test_subscription_commerce import database  # noqa: F401


@pytest.mark.asyncio
async def test_a_trial_keeps_the_terms_it_was_granted_with(customer, panel):  # noqa: F811
    db = customer
    await give_trial(db)
    trial = await db.scalar(select(TrialGrant))
    assert (trial.traffic_limit_gb_snapshot, trial.device_limit_snapshot) == (100, 2)
    plan = await db.get(Plan, 1)
    plan.traffic_limit_gb, plan.device_limit = 500, 9  # the plan changes before the worker runs
    await db.commit()
    await worker.run_next_job("test-worker")
    remote = next(iter(panel.users.values()))
    assert remote["trafficLimitBytes"] == 100 * 1024 ** 3, "the panel gets the terms frozen at the claim"
    assert {"expected_before_expires_at", "expected_after_expires_at"} <= columns("trial_grants")


def device_request():
    return Request({"type": "http", "method": "POST", "path": "/api/me/devices", "client": ("10.0.0.2", 1), "query_string": b"", "headers": []})


@pytest.mark.asyncio
async def test_a_revoked_device_counts_again_only_within_the_limit(database):
    register = lambda key: shop.register_device(shop.DeviceRegisterIn(device_key=key * 16, subscription_id=1), device_request(), database)  # noqa: E731
    phone = await register("a")
    await register("b")
    with pytest.raises(HTTPException) as third:
        await register("c")
    assert third.value.detail == "Достигнут лимит устройств тарифа", "plan limit: 2 devices"
    await shop.revoke_device(phone["id"], None, database)
    await register("c")
    with pytest.raises(HTTPException) as revived:
        await register("a")
    assert revived.value.status_code == 409, "bringing a revoked device back checks the limit again"
    assert (await register("b"))["status"] == "active", "an active device re-registers freely"


@pytest.mark.asyncio
async def test_a_stale_provider_event_lease_can_be_reclaimed(database):
    if database.bind.dialect.name != "postgresql":
        pytest.skip("provider event claims use PostgreSQL upserts")
    assert await shop.register_provider_event(database, "yookassa", "evt-lease", None) is True
    assert await shop.register_provider_event(database, "yookassa", "evt-lease", None) is False, "a fresh lease is respected"
    await database.execute(text("UPDATE payment_provider_events SET received_at = NOW() - INTERVAL '11 minutes' WHERE event_id = 'evt-lease'"))
    await database.commit()
    assert await shop.register_provider_event(database, "yookassa", "evt-lease", None) is True, "a crashed worker's event is taken over"


@pytest.mark.asyncio
async def test_auto_renew_tries_three_times_with_new_keys_then_stops(database, monkeypatch):
    charges = []
    _scheduler_env(monkeypatch, database, charges)

    async def cancelled(self, payment_id):
        return "canceled"

    async def charge(self, amount, order_id, desc, token):
        charges.append((amount, order_id))
        return {"id": f"yk-{len(charges)}"}
    monkeypatch.setattr(shop.YooKassaProvider, "get_payment_status", cancelled)
    monkeypatch.setattr(shop.YooKassaProvider, "charge_recurring", charge)
    await _renewable(database)

    await shop.run_auto_renew_pass(database)
    method = await database.scalar(select(AutoRenewMethod).execution_options(populate_existing=True))
    assert len(charges) == 1 and (method.failure_count, method.status) == (1, "past_due")
    assert timedelta(hours=1) < method.next_attempt_at - datetime.utcnow() <= timedelta(hours=2), "backoff 2 h"
    payment = await database.scalar(select(Payment).where(Payment.order_id == charges[0][1]))
    assert (payment.duration_days_snapshot, payment.traffic_limit_gb_snapshot, payment.device_limit_snapshot) == (30, 100, 2)

    sub = await database.get(shop.Subscription, 1)
    sub.next_renewal_at = datetime.utcnow() - timedelta(minutes=1)
    await database.commit()
    await shop.run_auto_renew_pass(database)  # the bank declined: the attempt fails, a new key is used
    method = await database.scalar(select(AutoRenewMethod).execution_options(populate_existing=True))
    orders = [o for _, o in charges]
    assert len(orders) == 2 and orders[1] == orders[0] + "-retry-2", "a failed attempt is retried under a new idempotency key"
    assert (method.failure_count, method.status, method.enabled) == (3, "payment_failed", False)
    assert (await database.get(User, 1, populate_existing=True)).auto_renew_enabled is False, "after three failures the customer pays by hand"

    sub = await database.get(shop.Subscription, 1)
    sub.next_renewal_at = datetime.utcnow() - timedelta(minutes=1)
    await database.commit()
    await shop.run_auto_renew_pass(database)
    assert len(charges) == 2, "no fourth charge"


@pytest.mark.asyncio
async def test_auto_renew_does_nothing_while_payments_are_closed(database, monkeypatch):
    charges = []
    _scheduler_env(monkeypatch, database, charges)

    async def closed(*a):
        return False
    monkeypatch.setattr(shop, "production_payments_allowed", closed)
    await _renewable(database)
    await shop.run_auto_renew_pass(database)
    assert charges == []


@pytest.mark.asyncio
async def test_an_error_for_one_customer_is_recorded_and_the_pass_goes_on(database, monkeypatch):
    charges = []
    _scheduler_env(monkeypatch, database, charges)

    async def broken(self, *a):
        raise RuntimeError("bank gateway 500")
    monkeypatch.setattr(shop.YooKassaProvider, "charge_recurring", broken)
    await _renewable(database)
    await shop.run_auto_renew_pass(database)  # must not raise
    method = await database.scalar(select(AutoRenewMethod).execution_options(populate_existing=True))
    assert (method.failure_count, method.status) == (1, "past_due") and "bank gateway 500" in method.last_error
