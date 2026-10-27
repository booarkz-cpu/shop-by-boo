"""v2.0.0 product features, checked by running them: subscription cancel/resume, gift redemption,
refund dry run, Customer 360 permissions, the lifecycle scheduler and the refund lock order.
(Was: searches for code lines in main.py.)"""
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app import gift_orders
from app import main as shop
from app.models import AuditLog, GiftRedemption, Payment, RefundRequest, Subscription
from app_contract import ROOT, columns, permissions, tables
from test_money_review import FakeRW, _gift
from test_subscription_commerce import database  # noqa: F401


def test_v2_release_contract_and_migration_head():
    assert '"version": "2.0.0-realise"' in (ROOT / "release-manifest.template.json").read_text(), "the release history keeps 2.0.0"


def test_lifecycle_and_gift_tables_exist():
    assert {"lifecycle_status", "grace_until", "scheduled_cancel_at", "cancelled_at"} <= columns("subscriptions")
    assert {"gift_codes", "gift_redemptions"} <= set(tables())
    unique = {tuple(c.name for c in con.columns) for con in tables()["gift_redemptions"].constraints if con.__class__.__name__ == "UniqueConstraint"}
    assert ("gift_code_id", "user_id") in unique, "one redemption per code and customer"


def record_locks(monkeypatch):
    calls = []

    async def user_lock(user_id, ttl=None):
        calls.append(("user", user_id))
        return ("u", "t")

    async def payment_lock(payment_id, *a, **k):
        calls.append(("payment", payment_id))
        return ("p", "t")

    async def release(lock, token):
        calls.append(("release", lock))
    monkeypatch.setattr(shop, "_acquire_user_fulfillment_lock", user_lock)
    monkeypatch.setattr(shop, "_acquire_payment_side_effect_lock", payment_lock)
    monkeypatch.setattr(shop, "_release_payment_side_effect_lock", release)
    return calls


@pytest.mark.asyncio
async def test_cancel_and_resume_run_under_the_customer_lock(database, monkeypatch):
    calls = record_locks(monkeypatch)
    out = await shop.subscription_lifecycle(shop.SubscriptionActionIn(action="cancel", reason="price"), None, database)
    sub = await database.get(Subscription, 1)
    assert out["status"] == "cancel_scheduled" and sub.scheduled_cancel_at == sub.expires_at
    assert calls == [("user", 1), ("release", "u")], "the action holds the customer lock and releases it"
    out = await shop.subscription_lifecycle(shop.SubscriptionActionIn(action="resume"), None, database)
    assert out["status"] == "active" and (await database.get(Subscription, 1)).scheduled_cancel_at is None
    with pytest.raises(HTTPException) as again:
        await shop.subscription_lifecycle(shop.SubscriptionActionIn(action="resume"), None, database)
    assert again.value.status_code == 409, "an active subscription cannot be resumed"
    assert len(calls) == 6, "every call releases its lock, the refused one too"


@pytest.mark.asyncio
async def test_a_gift_is_redeemed_once_through_an_idempotent_panel_operation(database, monkeypatch):
    database.add(_gift("GIFT_ONCE"))
    await database.commit()
    rw = FakeRW(status="ACTIVE")
    monkeypatch.setattr(shop, "RemnawaveClient", lambda: rw)
    import app.subscription_commerce as commerce
    monkeypatch.setattr(commerce, "RemnawaveClient", lambda: rw)
    calls = record_locks(monkeypatch)
    payload = SimpleNamespace(code="gift_once", subscription_id=None, model_dump=lambda exclude=None: {})
    first = await gift_orders.redeem_gift(payload, None, database)
    assert first["ok"] and ("user", 1) in calls
    redemption = await database.scalar(select(GiftRedemption))
    assert redemption.status == "completed" and redemption.operation_key == f"gift:{redemption.gift_code_id}:1"
    assert [c for c in rw.calls if c[0] == "extend"] == [("extend", 30)]
    second = await gift_orders.redeem_gift(payload, None, database)
    assert second == {"ok": True, "status": "completed", "already_redeemed": True}
    assert [c for c in rw.calls if c[0] == "extend"] == [("extend", 30)], "a repeated code adds no days"
    assert await database.scalar(select(func.count(GiftRedemption.id))) == 1


@pytest.mark.asyncio
async def test_the_purchaser_cannot_redeem_their_own_gift(database, monkeypatch):
    code = _gift("OWN_GIFT")
    code.purchaser_user_id = 1
    database.add(code)
    await database.commit()
    record_locks(monkeypatch)
    with pytest.raises(HTTPException) as own:
        await gift_orders.redeem_gift(SimpleNamespace(code="OWN_GIFT", subscription_id=None, model_dump=lambda exclude=None: {}), None, database)
    assert own.value.status_code == 403


async def paid_refund(db):
    db.add(Payment(id=50, user_id=1, subscription_id=1, plan_id=1, provider="yookassa", order_id="o-50", provider_payment_id="yk-50",
                   amount=Decimal("100"), currency="RUB", status="paid", fulfillment_status="completed", idempotency_key="k-50"))
    db.add(RefundRequest(id=7, payment_id=50, user_id=1, amount=Decimal("100"), status="requested"))
    await db.commit()


@pytest.mark.asyncio
async def test_refund_dry_run_plans_without_changing_anything(database):
    await paid_refund(database)
    before = (await database.get(Subscription, 1)).expires_at
    out = await shop.refund_dry_run(7, database, SimpleNamespace(email="a@b.c"))
    assert out["safe_to_execute"] is True and out["planned_actions"][:2] == ["refund_provider", "revoke_subscription"]
    await database.rollback()
    assert (await database.get(RefundRequest, 7)).status == "requested"
    assert (await database.get(Payment, 50)).status == "paid"
    assert (await database.get(Subscription, 1)).expires_at == before
    assert await database.scalar(select(func.count(AuditLog.id))) == 0


def test_customer_360_and_refunds_require_their_permissions():
    assert permissions("GET", "/api/admin/customers/{user_id}/360") == {"users.read"}
    assert permissions("GET", "/api/admin/refunds/{refund_id}/dry-run") == {"payments.refund"}
    assert permissions("POST", "/api/admin/refunds/{refund_id}/execute") == {"payments.refund"}


@pytest.mark.asyncio
async def test_refund_takes_the_customer_lock_before_the_payment_lock(database, monkeypatch):
    if database.bind.dialect.name != "postgresql":
        pytest.skip("the refund claim uses SELECT … FOR UPDATE")
    await paid_refund(database)
    calls = record_locks(monkeypatch)

    async def refund(self, *a):
        raise RuntimeError("provider down")
    monkeypatch.setattr(shop.YooKassaProvider, "refund", refund)
    monkeypatch.setattr(shop, "engine", database.bind)
    with pytest.raises(Exception):
        await shop.execute_refund(7, database, SimpleNamespace(email="a@b.c"))
    taken = [c for c in calls if c[0] in ("user", "payment")]
    assert taken == [("user", 1), ("payment", 50)]


@pytest.mark.asyncio
async def test_an_ended_subscription_is_switched_off_and_a_panel_error_is_retried(database, monkeypatch):
    sub = await database.get(Subscription, 1)
    sub.expires_at = datetime.utcnow() - timedelta(days=4)
    sub.grace_until = datetime.utcnow() - timedelta(days=1)
    sub.lifecycle_status = "grace"
    await database.commit()

    class Panel:
        fail = True
        disabled = []

        async def disable_user(self, uid):
            if Panel.fail:
                raise RuntimeError("panel down")
            Panel.disabled.append(uid)
    monkeypatch.setattr(shop, "RemnawaveClient", Panel)
    calls = record_locks(monkeypatch)
    await shop.run_lifecycle_pass(database)
    assert (await database.get(Subscription, 1)).lifecycle_status == "revoke_pending", "a failed switch-off is kept for a retry"
    Panel.fail = False
    await shop.run_lifecycle_pass(database)
    assert (await database.get(Subscription, 1)).lifecycle_status == "expired" and Panel.disabled == ["remote-1"]
    assert ("user", 1) in calls and calls.count(("release", "u")) == calls.count(("user", 1))
