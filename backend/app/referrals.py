"""Referral binding shared by the cabinet and Telegram entry point."""
from fastapi import HTTPException
from sqlalchemy import select, text
from .models import User

async def bind_referrer(db, user, code: str):
    # Checkout/renewal already hold the buyer row before snapshotting the chain.
    # Use the same order here, including Telegram callers that hold no row lock.
    user=await db.scalar(select(User).where(User.id==user.id).with_for_update().execution_options(populate_existing=True))
    if not user or user.deleted_at or user.restricted_at:raise HTTPException(409,"Account unavailable")
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": 1400000005})
    await db.refresh(user)
    if user.referred_by_id:
        raise HTTPException(409, "Referral is already set")
    from .account_merge import referral_owner
    ref = await referral_owner(db, code.strip())
    if not ref or ref.id == user.id or ref.restricted_at:
        raise HTTPException(400, "Invalid referral code")
    # No cycles even when an existing customer's first referral is assigned later.
    ancestor = ref
    for _ in range(100):
        if ancestor.id == user.id:
            raise HTTPException(400, "Referral cycle is not allowed")
        if not ancestor.referred_by_id:
            user.referred_by_id = ref.id
            return ref.id
        ancestor = await db.scalar(select(User).where(User.id==ancestor.referred_by_id).execution_options(populate_existing=True))
        if ancestor is None:
            raise HTTPException(400, "Invalid referral chain")
    raise HTTPException(400, "Referral chain is too deep")
