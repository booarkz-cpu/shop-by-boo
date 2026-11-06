"""Stage 19, C1: a refund takes access back inside the same locks as fulfilment, and the referral reward is reversed
only after access is really gone. Checked by running the admin retry and the refund scheduler.

Replaces test_v44_5_17_deep_regressions.py, which looked for the lock lines and ``if r.status == "refunded"`` in the
source."""
import asyncio
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import main as shop
from app.models import Payment, RefundRequest
from test_subscription_commerce import database  # noqa: F401

ADMIN = SimpleNamespace(email="owner@corgi.test", role="admin")


@pytest.fixture
def trace(database, monkeypatch):
    """Locks, the panel revoke and the referral reversal, in the order they happen."""
    state = SimpleNamespace(events=[], revoke_fails=False, status="succeeded")

    async def user_lock(user_id, ttl=300):
        state.events.append("lock user")
        return "user-lock", "u"

    async def payment_lock(payment_id):
        state.events.append("lock payment")
        return "payment-lock", "p"

    async def release(lock, token):
        state.events.append("release " + lock.split("-")[0])

    async def revoke(db, payment, actor, action):
        state.events.append("revoke")
        if state.revoke_fails:
            raise RuntimeError("panel is down")
        return {"revoked": True}

    async def reverse(db, payment, actor):
        state.events.append("reverse referral")
        return {"reversed": True}

    async def refund_status(self, refund_id):
        return state.status

    async def quiet(*a, **k):
        return None
    monkeypatch.setattr(shop, "_acquire_user_fulfillment_lock", user_lock)
    monkeypatch.setattr(shop, "_acquire_payment_side_effect_lock", payment_lock)
    monkeypatch.setattr(shop, "_release_payment_side_effect_lock", release)
    monkeypatch.setattr(shop, "_safe_revoke_for_refunded_payment", revoke)
    monkeypatch.setattr(shop, "_reverse_referral_reward_for_refund", reverse)
    monkeypatch.setattr(shop.YooKassaProvider, "get_refund_status", refund_status)
    monkeypatch.setattr(shop, "send_alert", quiet)
    monkeypatch.setattr(shop, "engine", database.bind)
    return state


async def refund(db, payment_status, refund_status, order="ref-1", provider_refund_id="rf-1"):
    payment = Payment(user_id=1, subscription_id=1, plan_id=1, provider="yookassa", order_id=order, provider_payment_id="yk-" + order,
                      amount=Decimal("100"), currency="RUB", status=payment_status, idempotency_key="idem-" + order)
    db.add(payment)
    await db.flush()
    request = RefundRequest(payment_id=payment.id, user_id=1, amount=Decimal("100"), status=refund_status, provider_refund_id=provider_refund_id)
    db.add(request)
    await db.commit()
    return payment, request


LOCKED = ["lock user", "lock payment", "revoke", "reverse referral", "release payment", "release user"]


@pytest.mark.asyncio
async def test_retry_revoke_runs_inside_both_locks(database, trace):
    payment, request = await refund(database, "refunded", "refunded_pending_revoke")
    answer = await shop.retry_refund_revoke(request.id, database, ADMIN)
    assert answer["status"] == "refunded" and answer["revoked"] and answer["reversed"]
    assert trace.events == LOCKED
    await database.refresh(request)
    assert request.status == "refunded"


@pytest.mark.asyncio
async def test_a_failed_retry_keeps_the_referral_and_releases_the_locks(database, trace):
    payment, request = await refund(database, "refunded", "refunded_pending_revoke")
    trace.revoke_fails = True
    with pytest.raises(HTTPException) as err:
        await shop.retry_refund_revoke(request.id, database, ADMIN)
    assert err.value.status_code == 503
    assert trace.events == ["lock user", "lock payment", "revoke", "release payment", "release user"], "no reversal before access is gone"
    await database.refresh(request)
    assert request.status == "refunded_pending_revoke" and "panel is down" in request.reason


@pytest.mark.asyncio
async def test_retry_revoke_only_for_a_refund_waiting_for_it(database, trace):
    _, done = await refund(database, "refunded", "refunded", order="ref-2")
    with pytest.raises(HTTPException) as err:
        await shop.retry_refund_revoke(done.id, database, ADMIN)
    assert err.value.status_code == 404 and trace.events == []


async def one_pass(monkeypatch):
    async def sleep(seconds):
        raise asyncio.CancelledError  # one pass is enough
    monkeypatch.setattr(shop, "asyncio", SimpleNamespace(**{**vars(asyncio), "sleep": sleep}))
    with pytest.raises(asyncio.CancelledError):
        await shop.refund_revoke_scheduler()


@pytest.mark.asyncio
async def test_a_confirmed_refund_is_reconciled_inside_both_locks(database, trace, monkeypatch):
    payment, request = await refund(database, "paid", "processing")
    await one_pass(monkeypatch)
    assert trace.events == LOCKED
    await database.refresh(payment)
    await database.refresh(request)
    assert (payment.status, request.status, payment.fulfillment_terminal) == ("refunded", "refunded", True)


@pytest.mark.asyncio
async def test_reconciliation_reverses_the_referral_only_after_the_revoke(database, trace, monkeypatch):
    payment, request = await refund(database, "paid", "processing")
    trace.revoke_fails = True
    await one_pass(monkeypatch)
    # The first loop leaves the refund waiting for the revoke; the second loop of the same pass retries it and fails again.
    assert "reverse referral" not in trace.events
    assert trace.events[:3] == ["lock user", "lock payment", "revoke"] and trace.events.count("release payment") == trace.events.count("lock payment")
    await database.refresh(payment)
    await database.refresh(request)
    assert payment.status == "refunded" and request.status == "refunded_pending_revoke", "the money is back, access is retried"


@pytest.mark.asyncio
async def test_a_refused_refund_takes_nothing_back(database, trace, monkeypatch):
    payment, request = await refund(database, "paid", "processing")
    trace.status = "canceled"
    await one_pass(monkeypatch)
    assert trace.events == []
    await database.refresh(payment)
    await database.refresh(request)
    assert payment.status == "paid" and request.status == "failed"


@pytest.mark.asyncio
async def test_manual_reconcile_reverses_the_referral_once_and_only_after_the_revoke(database, trace):
    """Replaces test_v45_4_deep_regressions.test_refund_paths_reverse_referral_reward_once (the reconcile part)."""
    payment, request = await refund(database, "paid", "processing")
    answer = await shop.reconcile_refund(request.id, database, ADMIN)
    assert answer["status"] == "refunded" and trace.events == LOCKED
    trace.events.clear()
    again = await shop.reconcile_refund(request.id, database, ADMIN)
    assert again["already_reconciled"] and "reverse referral" not in trace.events and "revoke" not in trace.events

    payment, request = await refund(database, "paid", "processing", order="ref-3", provider_refund_id="rf-3")
    trace.events.clear()
    trace.revoke_fails = True
    answer = await shop.reconcile_refund(request.id, database, ADMIN)
    assert answer["status"] == "refunded_pending_revoke" and "reverse referral" not in trace.events
    assert trace.events[-2:] == ["release payment", "release user"]


@pytest.mark.asyncio
async def test_executed_refund_revokes_then_reverses_inside_both_locks(database, trace, monkeypatch):
    """Replaces the execute part of test_v45_4_deep_regressions.test_refund_paths_reverse_referral_reward_once."""
    if database.bind.dialect.name != "postgresql":
        pytest.skip("the refund claim is a PostgreSQL row lock (SELECT … FOR UPDATE)")
    payment, request = await refund(database, "paid", "approved", provider_refund_id=None)
    sent = []

    async def provider_refund(self, payment_id, amount, currency, description):
        sent.append((payment_id, Decimal(str(amount))))
        trace.events.append("gateway refund")
        return {"id": "rf-new", "status": "succeeded"}

    async def quiet(*a, **k):
        return None
    monkeypatch.setattr(shop.YooKassaProvider, "refund", provider_refund)
    answer = await shop.execute_refund(request.id, database, ADMIN)
    assert answer == {"ok": True, "status": "refunded", "provider_refund_id": "rf-new"}
    assert sent == [("yk-ref-1", Decimal("100"))]
    assert trace.events == ["lock user", "lock payment", "gateway refund", "revoke", "reverse referral", "release payment", "release user"]
    with pytest.raises(HTTPException) as err:
        await shop.execute_refund(request.id, database, ADMIN)
    assert err.value.status_code == 400 and len(sent) == 1, "a refund is sent to the gateway once"
