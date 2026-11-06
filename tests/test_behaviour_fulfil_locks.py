"""Stage 19, C1: confirming and fulfilling a payment follow one lock order (customer, then payment), re-read the rows
under the locks, and never revive a refunded payment or serve a deleted account. Checked by running the code.

Replaces source-text checks of test_v1_0_4_critical_regressions.py, test_v1_0_8_critical_regression.py and
test_v1_0_9_critical_regressions.py (positions of lock lines and variable names in the source)."""
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import update

from app import main as shop
from app.models import Payment, Subscription, User
from test_money_review import FakeRW
from test_subscription_commerce import database  # noqa: F401


@pytest.fixture
def trace(database, monkeypatch):
    state = SimpleNamespace(events=[], on_user_lock=None, on_payment_lock=None, rw=None)

    async def user_lock(user_id, ttl=300):
        state.events.append("lock user")
        if state.on_user_lock:
            await state.on_user_lock()
        return "user-lock", "u"

    async def payment_lock(payment_id):
        state.events.append("lock payment")
        if state.on_payment_lock:
            await state.on_payment_lock()
        return "payment-lock", "p"

    async def release(lock, token):
        state.events.append("release " + lock.split("-")[0])
    monkeypatch.setattr(shop, "_acquire_user_fulfillment_lock", user_lock)
    monkeypatch.setattr(shop, "_acquire_payment_side_effect_lock", payment_lock)
    monkeypatch.setattr(shop, "_release_payment_side_effect_lock", release)
    monkeypatch.setattr(shop, "redis_client", object())
    monkeypatch.setattr(shop, "engine", database.bind)
    return state


def panel(monkeypatch, sub, state):
    rw = FakeRW(status="ACTIVE")
    rw.expiry = sub.expires_at
    monkeypatch.setattr(shop, "RemnawaveClient", lambda: rw)
    state.rw = rw
    return rw


async def payment(db, status, order="lock-1"):
    row = Payment(user_id=1, subscription_id=1, plan_id=1, provider="yookassa", order_id=order, provider_payment_id="yk-" + order,
                  amount=Decimal("100"), currency="RUB", status=status, fulfillment_status="pending", duration_days_snapshot=30,
                  traffic_limit_gb_snapshot=100, device_limit_snapshot=2, purpose="subscription", idempotency_key="idem-" + order)
    db.add(row)
    await db.commit()
    return row


@pytest.mark.asyncio
async def test_confirmation_takes_the_customer_lock_then_the_payment_lock(database, trace, monkeypatch):
    row = await payment(database, "pending")
    panel(monkeypatch, await database.get(Subscription, 1), trace)
    answer = await shop._confirm_and_fulfill_payment(row.id, database)
    assert answer == {"ok": True, "ignored": False, "reason": "fulfilled"}
    # Confirm: customer → payment, the payment lock is handed back before fulfilment takes it again;
    # fulfilment reuses the customer lock it was given and never releases it itself.
    assert trace.events == ["lock user", "lock payment", "release payment", "lock payment", "release payment", "release user"]
    await database.refresh(row)
    assert row.status == "paid" and row.paid_at and row.fulfillment_status == "completed"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["refunded", "refunded_pending_revoke", "creation_unknown"])
async def test_a_refund_that_won_the_lock_is_never_revived(database, trace, monkeypatch, status):
    """The caller saw «pending»; while it waited for the payment lock a refund moved the row on."""
    row = await payment(database, "pending")
    panel(monkeypatch, await database.get(Subscription, 1), trace)

    async def refund_wins():
        await database.execute(update(Payment).where(Payment.id == row.id).values(status=status).execution_options(synchronize_session=False))
    trace.on_payment_lock = refund_wins
    answer = await shop._confirm_and_fulfill_payment(row.id, database)
    assert answer == {"ok": True, "ignored": True, "reason": "payment_not_eligible"}
    assert trace.events == ["lock user", "lock payment", "release payment", "release user"]
    assert trace.rw.calls == [], "the panel is not touched"
    await database.refresh(row)
    assert row.status == status


@pytest.mark.asyncio
async def test_fulfilment_on_its_own_takes_and_returns_both_locks(database, trace, monkeypatch):
    row = await payment(database, "paid")
    panel(monkeypatch, await database.get(Subscription, 1), trace)
    await shop.fulfill(row.id, database)
    assert trace.events == ["lock user", "lock payment", "release payment", "release user"]


@pytest.mark.asyncio
async def test_a_held_customer_lock_is_reused_and_left_to_its_owner(database, trace, monkeypatch):
    row = await payment(database, "paid")
    panel(monkeypatch, await database.get(Subscription, 1), trace)
    await shop.fulfill(row.id, database, existing_user_lock_token="held")
    assert trace.events == ["lock payment", "release payment"]


@pytest.mark.asyncio
@pytest.mark.parametrize("held", [None, "held"])
async def test_an_account_deleted_while_waiting_gets_nothing(database, trace, monkeypatch, held):
    """The customer row is re-read under the customer lock, also when the caller already holds that lock."""
    row = await payment(database, "paid")
    panel(monkeypatch, await database.get(Subscription, 1), trace)

    async def deleted_meanwhile():
        await database.execute(update(User).where(User.id == 1).values(deleted_at=shop.datetime.utcnow()).execution_options(synchronize_session=False))
    if held:
        await deleted_meanwhile()
        await database.get(User, 1)  # the stale snapshot a caller could hold
    else:
        trace.on_user_lock = deleted_meanwhile
    with pytest.raises(RuntimeError, match="deleted"):
        await shop.fulfill(row.id, database, existing_user_lock_token=held)
    assert "lock payment" not in trace.events and trace.rw.calls == []
    assert trace.events == ([] if held else ["lock user", "release user"])


@pytest.mark.asyncio
async def test_the_admin_reconcile_confirms_through_the_same_locked_path(database, trace, monkeypatch):
    """Replaces test_v1_0_8_critical_regression.test_reconciliation_paths_use_atomic_confirmation_helper_…: the admin
    «reconcile payments» button cannot revive a payment refunded while it was asking the gateway."""
    fresh = await payment(database, "pending", order="lock-a")
    raced = await payment(database, "pending", order="lock-b")
    panel(monkeypatch, await database.get(Subscription, 1), trace)

    async def paid(self, *a, **k):
        return True
    monkeypatch.setattr(shop.YooKassaProvider, "verify_succeeded", paid)
    calls = {"n": 0}

    async def refund_wins_second():
        calls["n"] += 1
        if calls["n"] == 3:  # the first confirm takes it twice (confirm + fulfil); the second one is raced
            await database.execute(update(Payment).where(Payment.id == raced.id).values(status="refunded").execution_options(synchronize_session=False))
    trace.on_payment_lock = refund_wins_second
    answer = await shop.reconcile_payments(database, SimpleNamespace(email="owner@corgi.test", role="admin"))
    assert answer["checked"] == 2 and answer["confirmed"] == 1
    await database.refresh(fresh)
    await database.refresh(raced)
    assert fresh.status == "paid" and raced.status == "refunded"
