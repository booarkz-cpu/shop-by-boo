"""Transactional, repeat-safe reversal of a refunded wallet top-up."""
from decimal import Decimal

from sqlalchemy import select, update

from .models import FinancialLedger, Payment, User


async def reverse_wallet_topup(db, payment):
    # The savepoint also protects callers which catch a failed side effect and
    # commit the refund as pending. Never persist half of a balance reversal.
    async with db.begin_nested():
        current = (await db.execute(
            select(Payment).where(Payment.id == payment.id)
            .execution_options(populate_existing=True).with_for_update()
        )).scalar_one()
        if current.purpose != "topup":
            raise ValueError("Wallet reversal requires a top-up")
        if current.status not in {"refunded", "refunded_pending_revoke"}:
            raise ValueError("Wallet reversal requires a confirmed refund")
        key = f"wallet-topup-refund:{current.id}"
        existing = await db.scalar(select(FinancialLedger.id).where(FinancialLedger.operation_key == key))
        if existing is not None:
            return {"revoked": False, "reason": "wallet_already_reversed"}
        if current.fulfillment_status != "completed":
            return {"revoked": False, "reason": "wallet_not_credited"}
        amount = Decimal(str(current.amount))
        if not amount.is_finite() or amount <= 0:
            raise ValueError("Invalid top-up amount")
        # A spent balance becomes a debt; clamping to zero would create money.
        balance = (await db.execute(
            update(User).where(User.id == current.user_id)
            .values(wallet_balance=User.wallet_balance - amount)
            .returning(User.wallet_balance)
        )).scalar_one()
        db.add(FinancialLedger(
            operation_key=key, user_id=current.user_id, payment_id=current.id,
            kind="wallet_topup_refund", direction="debit", amount=amount,
            currency=current.currency, balance_after=balance,
        ))
        await db.flush()
    return {"revoked": False, "reason": "wallet_reversed", "wallet_balance": str(balance)}
