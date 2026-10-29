"""v28.51 loyalty levels: a level by tenure or total paid, the discount on purchases and renewals, cashback after the
hold period (taken back on a refund), bonus days once per reached level."""
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app import loyalty as ly
from app.models import FinancialLedger, LoyaltyMember, Payment, User
from test_subscription_commerce import database  # noqa: F401

ADMIN = SimpleNamespace(email="owner@example.com")


async def _pay(db, n, amount, paid_at, status="paid"):
    db.add(Payment(user_id=1, subscription_id=1, plan_id=1, provider="yookassa", order_id=f"o-{n}", amount=Decimal(str(amount)),
                   original_amount=Decimal(str(amount)), discount_amount=Decimal("0"), currency="RUB", status=status, fulfillment_status="completed",
                   idempotency_key=f"o-{n}", purpose="subscription", bonus_days=0, paid_at=paid_at))
    await db.commit()


async def _enable(db, hold_days=0):
    levels = [ly.LevelIn(**lv) for lv in ly.LEVELS]
    return await ly.admin_loyalty_config(ly.LoyaltyIn(enabled=True, hold_days=hold_days, levels=levels), db, ADMIN)


def test_level_by_tenure_or_spent():
    levels = ly.LEVELS
    assert ly.level_for(levels, 0, Decimal(0))[1]["key"] == "bronze"
    assert ly.level_for(levels, 3, Decimal(0))[1]["key"] == "silver"
    assert ly.level_for(levels, 0, Decimal(1500))[1]["key"] == "silver"
    assert ly.level_for(levels, 1, Decimal(5000))[1]["key"] == "gold"
    assert ly.level_for(levels, 12, Decimal(10))[1]["key"] == "gold"


@pytest.mark.asyncio
async def test_current_level_and_discount(database):  # noqa: F811
    db = database
    user = await db.get(User, 1)
    assert await ly.current(db, 1) is None and await ly.renewal_discount(db, user, 100) == Decimal("0.00")
    await _enable(db)
    await _pay(db, 1, 1600, datetime.utcnow() - timedelta(days=10))
    lv = await ly.current(db, 1)
    assert lv["key"] == "silver" and lv["next"]["title"] == "Золото" and "3400.00" in lv["next"]["need"]
    assert await ly.renewal_discount(db, user, 100) == Decimal("0.00")  # silver: cashback only
    await _pay(db, 2, 4000, datetime.utcnow() - timedelta(days=5))
    assert (await ly.current(db, 1))["key"] == "gold"
    assert await ly.renewal_discount(db, user, Decimal("199")) == Decimal("9.95")
    mine = await ly.my_loyalty(SimpleNamespace(), db)
    assert mine["enabled"] and mine["title"] == "Золото" and mine["next"] is None


@pytest.mark.asyncio
async def test_cashback_after_hold_and_reversal_on_refund(database):  # noqa: F811
    db = database
    await _enable(db, hold_days=3)
    now = datetime.utcnow()
    await _pay(db, 1, 2000, now + timedelta(minutes=1))  # paid after the switch-on; silver (3 %) — still on hold
    assert (await ly.cashback_pass(db))["credited"] == 0
    assert (await ly.cashback_pass(db, now + timedelta(days=4)))["credited"] == 1
    assert (await ly.cashback_pass(db, now + timedelta(days=5)))["credited"] == 0  # once per order
    user = await db.get(User, 1)
    await db.refresh(user)
    assert user.wallet_balance == Decimal("1060.00")
    payment = await db.scalar(select(Payment).where(Payment.order_id == "o-1"))
    payment.status = "refunded"
    await db.commit()
    assert (await ly.cashback_pass(db, now + timedelta(days=6)))["reversed"] == 1
    await db.refresh(user)
    assert user.wallet_balance == Decimal("1000.00")
    kinds = sorted(r.kind for r in (await db.execute(select(FinancialLedger))).scalars())
    assert kinds == ["loyalty_cashback", "loyalty_cashback_reversal"]


@pytest.mark.asyncio
async def test_orders_before_switch_on_get_no_cashback(database):  # noqa: F811
    db = database
    await _pay(db, 1, 2000, datetime.utcnow() - timedelta(days=30))
    await _enable(db)
    assert (await ly.cashback_pass(db))["credited"] == 0


@pytest.mark.asyncio
async def test_level_up_gives_bonus_days_once(database):  # noqa: F811
    db = database
    await _enable(db)
    await _pay(db, 1, 1600, datetime.utcnow() - timedelta(days=2))
    user = await db.get(User, 1)
    user.telegram_id = 42
    await db.commit()
    granted, sent = [], []

    async def apply(session, key, uid, days, reason, title=None, body=None):
        granted.append((key, uid, days, reason))

    async def notify(chat, text):
        sent.append(text)
    assert await ly.levels_pass(db, apply, notify) == [(1, "silver")]
    assert granted == [("loyalty:1:silver", 1, 3, "loyalty")] and "Серебро" in sent[0]
    assert await ly.levels_pass(db, apply, notify) == []
    assert (await db.get(LoyaltyMember, 1)).level == "silver"
    overview = await ly.admin_loyalty(db, ADMIN)
    assert overview["members"]["silver"] == 1


@pytest.mark.asyncio
async def test_config_validation(database):  # noqa: F811
    db = database
    levels = [ly.LevelIn(**ly.LEVELS[0]), ly.LevelIn(**{**ly.LEVELS[1], "key": "bronze"})]
    with pytest.raises(HTTPException):
        await ly.admin_loyalty_config(ly.LoyaltyIn(enabled=True, levels=levels), db, ADMIN)
    cfg = await _enable(db)
    since = cfg["since"]
    cfg = await _enable(db)
    assert cfg["since"] == since  # the start of cashback does not move on later edits
