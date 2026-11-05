"""Stage 18 (docs/ru/new/ADMIN_VERIFICATION.md): changing admin routes of «Финансы», «Рефералы», «Устройства»."""
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app import fiscal, pnl, referral_contests, recovery_api, wg_pool
from app import main as shop
from app.models import FiscalReceipt, InfraCost, PayoutTransaction, ReferralContest, WgConfig, WithdrawalRequest
from test_subscription_commerce import database  # noqa: F401

ADMIN = SimpleNamespace(email="owner@corgi.test", role="admin")


@pytest.mark.asyncio
async def test_infra_cost_is_deleted_once(database):
    made = await pnl.add_cost(pnl.CostIn(month="2026-10", category="servers", vendor="Hetzner", amount=Decimal("12.50")), database, ADMIN)
    assert await pnl.delete_cost(made["id"], database, ADMIN) == {"ok": True}
    assert (await database.execute(select(InfraCost))).scalars().first() is None
    with pytest.raises(HTTPException) as err:
        await pnl.delete_cost(made["id"], database, ADMIN)
    assert err.value.status_code == 404


@pytest.mark.asyncio
async def test_fiscal_check_and_retry(database, monkeypatch):
    out = await fiscal.admin_fiscal_test(database, ADMIN)  # receipts are off: an answer, never an exception
    assert out.get("ok") is False and out.get("message")
    with pytest.raises(HTTPException) as err:
        await fiscal.admin_fiscal_retry(404404, database, ADMIN)
    assert err.value.status_code == 404
    done = FiscalReceipt(payment_id=1, kind="income", provider="npd", status="done", amount=Decimal("100"))
    failed = FiscalReceipt(payment_id=2, kind="income", provider="npd", status="failed", amount=Decimal("100"), attempts=5)
    database.add_all([done, failed])
    await database.commit()
    with pytest.raises(HTTPException) as err:
        await fiscal.admin_fiscal_retry(done.id, database, ADMIN)
    assert err.value.status_code == 409, "a formed receipt is never sent twice"
    sent = []

    async def send(db, receipt, config):
        sent.append(receipt.attempts)
        receipt.status = "sent"
    monkeypatch.setattr(fiscal, "send_receipt", send)
    out = await fiscal.admin_fiscal_retry(failed.id, database, ADMIN)
    assert sent == [0] and out["status"] == "sent", "the retry starts the attempts over"


@pytest.mark.asyncio
async def test_referral_contest_is_cancelled(database):
    now = datetime.utcnow()
    made = await referral_contests.create_contest(referral_contests.ContestIn(
        title="Осенний конкурс", starts_at=now, ends_at=now + timedelta(days=7), prizes=[referral_contests.PrizeIn(place=1, days=30)]), database, ADMIN)
    assert await referral_contests.cancel_contest(made["id"], database, ADMIN) == {"ok": True}
    assert (await database.get(ReferralContest, made["id"])).status == "cancelled"
    with pytest.raises(HTTPException) as err:  # only an active contest is cancelled
        await referral_contests.cancel_contest(made["id"], database, ADMIN)
    assert err.value.status_code == 404


@pytest.mark.asyncio
async def test_withdrawal_is_marked_paid_only_after_approval(database):
    if database.bind.dialect.name != "postgresql":
        pytest.skip("SELECT … FOR UPDATE: PostgreSQL only")
    x = WithdrawalRequest(user_id=1, amount=Decimal("500"), destination="card *4417")
    database.add(x)
    await database.commit()
    with pytest.raises(HTTPException) as err:
        await recovery_api.paid_withdrawal(x.id, database, ADMIN)
    assert err.value.status_code == 404, "no payout before approval"
    await recovery_api.approve_withdrawal(x.id, database, ADMIN)
    assert await recovery_api.paid_withdrawal(x.id, database, ADMIN) == {"ok": True, "status": "paid"}
    payout = (await database.execute(select(PayoutTransaction).where(PayoutTransaction.withdrawal_id == x.id))).scalar_one()
    assert payout.status == "paid" and payout.paid_at
    with pytest.raises(HTTPException) as err:
        await recovery_api.paid_withdrawal(x.id, database, ADMIN)
    assert err.value.status_code == 409


@pytest.mark.asyncio
async def test_free_wireguard_configs_are_dropped_given_ones_stay(database):
    database.add_all([WgConfig(kind="wg", name="free", config="x"), WgConfig(kind="awg", name="given", config="y", subscription_id=1)])
    await database.commit()
    assert await wg_pool.drop_free(database, ADMIN) == {"deleted": 1}
    left = (await database.execute(select(WgConfig))).scalars().all()
    assert [w.name for w in left] == ["given"]
    assert shop  # the app is imported, so every router is registered
