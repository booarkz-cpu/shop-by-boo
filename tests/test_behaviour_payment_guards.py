"""Stage 19, C1: the money guards around a payment, checked by running the handlers.

Replaces three source-text checks of test_v44_5_18_deep_regressions.py:
- the YooKassa notification binds a provider payment only after the order matched and the gateway confirmed it;
- the admin «retry fulfilment» refuses refunded and unconfirmed payments;
- the reconciliation pass asks the gateway about the stored order, not about anything from outside.
"""
import asyncio
import json
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from starlette.requests import Request

from datetime import datetime, timedelta

from app import main as shop
from app.models import Payment
from test_subscription_commerce import database  # noqa: F401

ADMIN = SimpleNamespace(email="owner@corgi.test", role="admin")


def request(path: str, body: dict, ip="10.1.2.3"):
    raw = json.dumps(body).encode()

    async def receive():
        return {"type": "http.request", "body": raw, "more_body": False}
    return Request({"type": "http", "method": "POST", "path": path, "headers": [(b"content-type", b"application/json")],
                    "client": (ip, 443), "query_string": b""}, receive)


def yookassa_event(pid, order):
    return {"id": "evt-" + pid, "event": "payment.succeeded", "object": {"id": pid, "metadata": {"order_id": order}}}


async def add_payment(db, **values):
    data = dict(user_id=1, subscription_id=1, plan_id=1, provider="yookassa", amount=Decimal("100"), currency="RUB",
                status="pending")
    data.update(values)
    data.setdefault("idempotency_key", "idem-" + data["order_id"])
    payment = Payment(**data)
    db.add(payment)
    await db.commit()
    return payment


@pytest.fixture
def gateway(database, monkeypatch):
    """YooKassa as the webhook sees it: what it is asked, and what it answers."""
    monkeypatch.setattr(shop, "engine", database.bind)
    monkeypatch.setattr(shop.settings, "yookassa_webhook_ip_allowlist", "10.0.0.0/8")
    state = SimpleNamespace(paid=True, asked=[], fulfilled=[], events=[])

    async def verify(self, pid, amount, currency, order_id):
        state.asked.append((pid, amount, currency, order_id))
        return state.paid
    monkeypatch.setattr(shop.YooKassaProvider, "verify_succeeded", verify)

    async def claim(db, provider, event_id, payment_id):
        state.events.append(event_id)
        return True

    async def finish(db, provider, event_id, ok=True, error=None):
        return None

    async def confirm(payment_id, db):
        state.fulfilled.append(payment_id)
        return {"ok": True}
    monkeypatch.setattr(shop, "register_provider_event", claim)
    monkeypatch.setattr(shop, "finish_provider_event", finish)
    monkeypatch.setattr(shop, "_confirm_and_fulfill_payment", confirm)
    return state


@pytest.mark.asyncio
async def test_a_notification_for_another_order_is_refused(database, gateway):
    await add_payment(database, order_id="order-1", provider_payment_id="yk-1")
    with pytest.raises(HTTPException) as err:
        await shop.yookassa_webhook(request("/api/webhooks/yookassa", yookassa_event("yk-1", "order-2")), database)
    assert err.value.status_code == 403 and err.value.detail == "Order mismatch"
    assert gateway.asked == [] and gateway.fulfilled == [] and gateway.events == []


@pytest.mark.asyncio
async def test_an_unconfirmed_payment_is_never_bound(database, gateway):
    payment = await add_payment(database, order_id="order-3", status="creation_unknown")
    gateway.paid = False
    with pytest.raises(HTTPException) as err:
        await shop.yookassa_webhook(request("/api/webhooks/yookassa", yookassa_event("yk-3", "order-3")), database)
    assert err.value.status_code == 503
    assert gateway.asked == [("yk-3", Decimal("100"), "RUB", "order-3")], "the gateway is asked about the stored order"
    await database.refresh(payment)
    assert payment.provider_payment_id is None and payment.status == "creation_unknown", "nothing is bound before the gateway confirmed"
    assert gateway.fulfilled == []


@pytest.mark.asyncio
async def test_a_confirmed_payment_is_bound_then_fulfilled_once(database, gateway):
    payment = await add_payment(database, order_id="order-4", status="creation_unknown")
    answer = await shop.yookassa_webhook(request("/api/webhooks/yookassa", yookassa_event("yk-4", "order-4")), database)
    assert answer == {"ok": True}
    await database.refresh(payment)
    assert payment.provider_payment_id == "yk-4" and payment.status == "pending"
    assert gateway.asked == [("yk-4", Decimal("100"), "RUB", "order-4")] and gateway.fulfilled == [payment.id]
    # Somebody else's provider ID can never be bound over this one.
    with pytest.raises(HTTPException) as err:
        await shop.bind_provider_payment_id(database, payment, "yk-other")
    assert err.value.status_code == 409


@pytest.mark.asyncio
async def test_a_notification_from_outside_the_allowlist_is_refused(database, gateway):
    await add_payment(database, order_id="order-5")
    with pytest.raises(HTTPException) as err:
        await shop.yookassa_webhook(request("/api/webhooks/yookassa", yookassa_event("yk-5", "order-5"), ip="203.0.113.9"), database)
    assert err.value.status_code == 403
    shop.settings.yookassa_webhook_ip_allowlist = ""  # an empty allowlist fails closed (restored by monkeypatch)
    with pytest.raises(HTTPException):
        await shop.yookassa_webhook(request("/api/webhooks/yookassa", yookassa_event("yk-5", "order-5")), database)
    assert gateway.asked == [] and gateway.fulfilled == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status, fulfillment, code", [("refunded", "completed", 409), ("refunded_pending_revoke", "pending", 409),
                                                       ("pending", "pending", 409), ("creation_unknown", None, 409)])
async def test_retry_refuses_refunded_and_unconfirmed_payments(database, monkeypatch, status, fulfillment, code):
    payment = await add_payment(database, order_id="order-r", status=status, fulfillment_status=fulfillment)
    called = []

    async def fulfill(payment_id, db):
        called.append(payment_id)
    monkeypatch.setattr(shop, "fulfill", fulfill)
    with pytest.raises(HTTPException) as err:
        await shop.retry_payment(payment.id, database, ADMIN)
    assert err.value.status_code == code
    assert called == [], "no access is given"
    await database.refresh(payment)
    assert payment.status == status


@pytest.mark.asyncio
async def test_retry_fulfils_a_paid_payment_and_skips_a_completed_one(database, monkeypatch):
    waiting = await add_payment(database, order_id="order-p", status="paid", fulfillment_status="failed")
    done = await add_payment(database, order_id="order-d", status="paid", fulfillment_status="completed")
    called = []

    async def fulfill(payment_id, db):
        called.append(payment_id)
    monkeypatch.setattr(shop, "fulfill", fulfill)
    assert await shop.retry_payment(done.id, database, ADMIN) == {"ok": True, "status": "completed"}
    assert called == []
    assert await shop.retry_payment(waiting.id, database, ADMIN) == {"ok": True, "status": "completed"}
    assert called == [waiting.id]
    with pytest.raises(HTTPException) as err:
        await shop.retry_payment(999, database, ADMIN)
    assert err.value.status_code == 404


@pytest.mark.asyncio
async def test_reconciliation_asks_about_the_stored_order(database, monkeypatch):
    paid = await add_payment(database, order_id="order-a", provider_payment_id="yk-a")
    unpaid = await add_payment(database, order_id="order-b", provider_payment_id="yk-b")
    unknown = await add_payment(database, order_id="order-c", status="creation_unknown")  # no provider ID yet: skipped
    other = await add_payment(database, order_id="order-d", provider="platega", provider_payment_id="pl-d")
    settled = await add_payment(database, order_id="order-e", provider_payment_id="yk-paid", status="paid")
    stale = await add_payment(database, order_id="order-f", provider_payment_id="yk-old",
                              created_at=datetime.utcnow() - timedelta(hours=shop.RECONCILE_LOOKBACK_HOURS + 1))
    monkeypatch.setattr(shop, "engine", database.bind)
    asked, confirmed = [], []

    async def verify(self, pid, amount, currency, order_id):
        asked.append((pid, order_id))
        return pid == "yk-a"

    async def find(self, order_id, created_at):
        return None

    async def confirm(payment_id, db):
        confirmed.append(payment_id)
        return {"ok": True}

    async def no_cleanup(db, now):
        return 0
    monkeypatch.setattr(shop.YooKassaProvider, "verify_succeeded", verify)
    monkeypatch.setattr(shop.PlategaProvider, "verify_succeeded", verify)
    monkeypatch.setattr(shop.YooKassaProvider, "find_by_order_id", find)
    monkeypatch.setattr(shop, "_confirm_and_fulfill_payment", confirm)
    monkeypatch.setattr(shop, "cleanup_expired_promo_reservations", no_cleanup)
    sleeps = []

    async def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) > 1:
            raise asyncio.CancelledError  # one pass is enough
    monkeypatch.setattr(shop, "asyncio", SimpleNamespace(**{**vars(asyncio), "sleep": sleep}))
    with pytest.raises(asyncio.CancelledError):
        await shop.reconciliation_scheduler()
    assert shop.RECONCILE_INTERVAL == 600
    assert sleeps == [shop.RECONCILE_INTERVAL, shop.RECONCILE_INTERVAL]
    assert sorted(asked) == [("pl-d", "order-d"), ("yk-a", "order-a"), ("yk-b", "order-b")]
    assert ("yk-paid", "order-e") not in asked and ("yk-old", "order-f") not in asked
    assert confirmed == [paid.id]
    rows = {p.order_id: p.status for p in (await database.execute(select(Payment))).scalars()}
    assert rows[unpaid.order_id] == "pending" and rows[unknown.order_id] == "creation_unknown"
    assert rows[other.order_id] == "pending" and rows[settled.order_id] == "paid" and rows[stale.order_id] == "pending"


@pytest.mark.asyncio
async def test_reconciliation_visits_later_orders_and_restarts_a_bounded_sweep(database, monkeypatch):
    batch = shop.RECONCILE_BATCH
    original = [f"pending-{i}" for i in range(batch + 1)]
    for order in original:
        await add_payment(database, order_id=order, provider_payment_id=order)

    ticks = []

    async def sleep(seconds):
        assert seconds == shop.RECONCILE_INTERVAL
        if len(ticks) == 4:
            raise asyncio.CancelledError
        if len(ticks) == 1:
            await add_payment(database, order_id="new-arrival", provider_payment_id="new-arrival")
        ticks.append([])

    async def still_pending(self, pid, amount, currency, order_id):
        ticks[-1].append(order_id)
        return False

    monkeypatch.setattr(shop, "engine", database.bind)
    monkeypatch.setattr(shop, "asyncio", SimpleNamespace(**{**vars(asyncio), "sleep": sleep}))
    monkeypatch.setattr(shop.YooKassaProvider, "verify_succeeded", still_pending)
    with pytest.raises(asyncio.CancelledError):
        await shop.reconciliation_scheduler()

    assert ticks == [original[:batch], original[batch:], original[:batch], [original[-1], "new-arrival"]]


@pytest.mark.asyncio
async def test_reconciliation_keeps_the_original_lookback_boundary_across_pages(database, monkeypatch):
    started = datetime.utcnow()
    for i in range(shop.RECONCILE_BATCH):
        await add_payment(database, order_id=f"fresh-{i}", provider_payment_id=f"fresh-{i}", created_at=started)
    boundary = await add_payment(
        database,
        order_id="near-boundary",
        provider_payment_id="near-boundary",
        created_at=started - timedelta(hours=shop.RECONCILE_LOOKBACK_HOURS) + timedelta(minutes=5),
    )
    asked = []

    async def still_pending(self, pid, amount, currency, order_id):
        asked.append(order_id)
        return False

    async def no_cleanup(db, now):
        return 0

    monkeypatch.setattr(shop.YooKassaProvider, "verify_succeeded", still_pending)
    monkeypatch.setattr(shop, "cleanup_expired_promo_reservations", no_cleanup)

    _, cursor = await shop._reconcile_page(database, started, cursor=None)
    assert cursor is not None and len(cursor) == 3
    assert asked == [f"fresh-{i}" for i in range(shop.RECONCILE_BATCH)]

    _, cursor = await shop._reconcile_page(database, started + timedelta(minutes=10), cursor=cursor)
    assert cursor is None
    assert asked[-1] == boundary.order_id
