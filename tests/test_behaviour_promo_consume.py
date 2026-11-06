"""Stage 19, C1: a promo code use is reserved at checkout and consumed exactly once when the payment is fulfilled.

Replaces test_v15_production.test_promo_usage_is_reserved_then_consumed_safely, which looked for the lines
``reserve_promo(...)``, ``reserved_count=max(...)`` and ``used_count += 1`` in the source. Reserving and releasing
run in test_v44_5_7_deep_regressions.test_promo_uses_are_reserved_and_released."""
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app import main as shop
from app.models import Payment, PromoCode, PromoRedemption, PromoReservation, Subscription
from test_money_review import FakeRW
from test_subscription_commerce import database  # noqa: F401


async def paid_payment(db, order, promo_code):
    payment = Payment(user_id=1, subscription_id=1, plan_id=1, provider="yookassa", order_id=order, amount=90, currency="RUB",
                      status="paid", fulfillment_status="pending", duration_days_snapshot=30, traffic_limit_gb_snapshot=100,
                      device_limit_snapshot=2, purpose="subscription", promo_code=promo_code, idempotency_key="idem-" + order)
    db.add(payment)
    await db.commit()
    return payment


def panel(monkeypatch, db_sub):
    rw = FakeRW(status="ACTIVE")
    rw.expiry = db_sub.expires_at
    monkeypatch.setattr(shop, "RemnawaveClient", lambda: rw)
    monkeypatch.setattr(shop, "redis_client", object())
    return rw


async def counts(db, promo_id):
    promo = await db.get(PromoCode, promo_id, populate_existing=True)
    redemptions = await db.scalar(select(func.count(PromoRedemption.id)).where(PromoRedemption.promo_code_id == promo_id))
    return promo.reserved_count, promo.used_count, redemptions


@pytest.mark.asyncio
async def test_a_reserved_use_is_consumed_once_on_fulfilment(database, monkeypatch):
    db = database
    promo = PromoCode(code="CORGI10", kind="percent", value=Decimal("10"), usage_limit=2, used_count=0, enabled=True)
    db.add(promo)
    await db.commit()
    reservation = await shop.reserve_promo(db, promo, 1, "promo-1")
    payment = await paid_payment(db, "promo-1", "CORGI10")
    reservation.payment_id = payment.id
    await db.commit()
    assert await counts(db, promo.id) == (1, 0, 0)

    panel(monkeypatch, await db.get(Subscription, 1))
    await shop.fulfill(payment.id, db)
    assert await counts(db, promo.id) == (0, 1, 1), "the reservation turned into one use and one redemption"
    assert (await db.get(PromoReservation, reservation.id, populate_existing=True)).status == "consumed"

    # A repeated fulfilment (a retry, a second notification) does not count the use again.
    await shop.fulfill(payment.id, db)
    assert await counts(db, promo.id) == (0, 1, 1)
    # A released or consumed reservation is never released again.
    assert await shop.release_promo_reservation(db, reservation.id) is False
    assert await counts(db, promo.id) == (0, 1, 1)


@pytest.mark.asyncio
async def test_a_payment_without_a_reservation_counts_within_the_limit_only(database, monkeypatch):
    """Payments created before reservations existed: one use is counted, never past the limit."""
    db = database
    promo = PromoCode(code="OLD", kind="percent", value=Decimal("10"), usage_limit=1, used_count=0, enabled=True)
    db.add(promo)
    await db.commit()
    first = await paid_payment(db, "legacy-1", "OLD")
    sub = await db.get(Subscription, 1)
    panel(monkeypatch, sub)
    await shop.fulfill(first.id, db)
    assert await counts(db, promo.id) == (0, 1, 1)

    sub = await db.get(Subscription, 1, populate_existing=True)
    panel(monkeypatch, sub)
    second = await paid_payment(db, "legacy-2", "OLD")
    await shop.fulfill(second.id, db)
    assert await counts(db, promo.id) == (0, 1, 1), "the limit is never exceeded"


@pytest.mark.asyncio
async def test_an_expired_or_limited_code_cannot_be_reserved(database):
    db = database
    old = PromoCode(code="GONE", kind="percent", value=Decimal("10"), enabled=True, ends_at=shop.datetime.utcnow() - timedelta(days=1))
    once = PromoCode(code="ONCE", kind="percent", value=Decimal("10"), enabled=True, max_uses_per_user=1)
    off = PromoCode(code="OFF", kind="percent", value=Decimal("10"), enabled=False)
    db.add_all([old, once, off])
    await db.commit()
    with pytest.raises(shop.HTTPException) as err:
        await shop.reserve_promo(db, old, 1, "x-1")
    assert err.value.detail == "Срок промокода истёк"
    with pytest.raises(shop.HTTPException):
        await shop.reserve_promo(db, off, 1, "x-2")
    await shop.reserve_promo(db, once, 1, "x-3")
    with pytest.raises(shop.HTTPException) as err:
        await shop.reserve_promo(db, once, 1, "x-4")
    assert err.value.detail == "Лимит промокода для этого клиента исчерпан"
    assert (await shop.reserve_promo(db, once, 2, "x-5")).status == "reserved", "another client still can"
