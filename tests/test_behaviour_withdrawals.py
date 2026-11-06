"""Stage 19, C1: rejecting a referral withdrawal by behaviour (was: test_v44_5_15_deep_regressions looked for
'if x.status != "requested"', 'PayoutTransaction' and 'double-spend' in the source).

Only an untouched request gives the money back; once a payout is on its way the balance is not restored twice."""
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app import main as shop
from app.models import PayoutTransaction, ReferralLedger, User, WithdrawalRequest
from test_subscription_commerce import database  # noqa: F401

ADMIN = SimpleNamespace(email="boss@corgi.test")


async def balance(db, uid=1):
    db.expire_all()
    return (await db.get(User, uid)).referral_balance


async def withdrawal(db, status="requested", amount="300"):
    row = WithdrawalRequest(user_id=1, amount=Decimal(amount), destination="card *1234", status=status)
    db.add(row)
    await db.commit()
    return row.id


@pytest.mark.asyncio
async def test_rejecting_a_withdrawal_returns_the_money_once(database, monkeypatch):
    db = database
    if db.bind.dialect.name != "postgresql":
        pytest.skip("SELECT … FOR UPDATE: PostgreSQL (CI)")
    monkeypatch.setattr(shop, "audit", lambda *a, **k: _none())
    user = await db.get(User, 1)
    user.referral_balance = Decimal("0")
    await db.commit()

    wid = await withdrawal(db)
    out = await shop.reject_withdrawal(wid, None, db, ADMIN)
    assert out == {"ok": True, "status": "rejected"}
    assert await balance(db) == Decimal("300")
    ledger = (await db.execute(select(ReferralLedger).where(ReferralLedger.kind == f"withdrawal_reversal:{wid}"))).scalars().all()
    assert len(ledger) == 1 and ledger[0].amount == Decimal("300")
    with pytest.raises(HTTPException) as again:  # a second rejection does not pay again
        await shop.reject_withdrawal(wid, None, db, ADMIN)
    assert again.value.status_code == 409 and await balance(db) == Decimal("300")

    # Approved: the payout is in progress — no restoring the balance.
    wid2 = await withdrawal(db)
    await shop.approve_withdrawal(wid2, db, ADMIN)
    with pytest.raises(HTTPException) as approved:
        await shop.reject_withdrawal(wid2, None, db, ADMIN)
    assert approved.value.status_code == 409 and await balance(db) == Decimal("300")

    # Requested, but an active payout row exists (left from a crash): refused too; a failed one is cleaned up.
    wid3 = await withdrawal(db)
    db.add(PayoutTransaction(withdrawal_id=wid3, amount=Decimal("300"), status="processing"))
    await db.commit()
    with pytest.raises(HTTPException):
        await shop.reject_withdrawal(wid3, None, db, ADMIN)
    payout = (await db.execute(select(PayoutTransaction).where(PayoutTransaction.withdrawal_id == wid3))).scalar_one()
    payout.status = "failed"
    await db.commit()
    await shop.reject_withdrawal(wid3, None, db, ADMIN)
    assert await balance(db) == Decimal("600")
    assert (await db.execute(select(PayoutTransaction).where(PayoutTransaction.withdrawal_id == wid3))).scalar_one_or_none() is None


async def _none():
    return None
