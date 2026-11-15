"""Customer history projections. Business operations stay in the existing core."""
from datetime import datetime

from fastapi import APIRouter, Depends, Request, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .models import FinancialLedger, GiftCode, GiftRedemption, Plan, SupportTicket
from .support_threads import append_message, read_thread

router = APIRouter()


class SupportMessageIn(BaseModel):
    message: str = Field(min_length=1, max_length=5000)
    attachment_ids: list[int] = Field(default_factory=list,max_length=3)


@router.get("/api/me/support/tickets/{ticket_id}/messages")
async def customer_support_messages(ticket_id: int, request: Request, after: int = Query(0, ge=0), db: AsyncSession = Depends(get_db)):
    from .main import user_from_token
    user = await user_from_token(request, db)
    ticket = await db.scalar(select(SupportTicket).where(SupportTicket.id == ticket_id, SupportTicket.user_id == user.id))
    if not ticket:
        raise HTTPException(404, "Обращение не найдено")
    return await read_thread(db, ticket, after)


@router.post("/api/me/support/tickets/{ticket_id}/messages")
async def customer_support_reply(ticket_id: int, payload: SupportMessageIn, request: Request, db: AsyncSession = Depends(get_db)):
    from .main import user_from_token
    user = await user_from_token(request, db)
    ticket = await db.scalar(select(SupportTicket).where(
        SupportTicket.id == ticket_id, SupportTicket.user_id == user.id).with_for_update())
    if not ticket:
        raise HTTPException(404, "Обращение не найдено")
    message, created = await append_message(db, ticket, "customer", payload.message, request.headers.get("Idempotency-Key"),payload.attachment_ids,f"customer:{user.id}")
    await db.commit()
    return {"id": message.id, "status": ticket.status, "created": created}


@router.get("/api/me/wallet/history")
async def wallet_history(request: Request, db: AsyncSession = Depends(get_db)):
    from .main import user_from_token

    user = await user_from_token(request, db)
    rows = (await db.execute(
        select(FinancialLedger).where(
            FinancialLedger.user_id == user.id,
            FinancialLedger.kind.in_(("wallet_topup", "wallet_spend", "gift_purchase", "wallet_topup_refund", "wallet_purchase_refund", "gift_card", "survey_reward", "giveaway_reward", "wallet_import")),
        ).order_by(FinancialLedger.id.desc()).limit(100)
    )).scalars().all()
    from .tribute import configured as tribute_ready
    from .config import settings as _settings
    tribute = {"url": _settings.tribute_donate_link, "telegram_linked": bool(user.telegram_id)} if tribute_ready() else None
    return {"balance": str(user.wallet_balance or 0), "tribute": tribute, "items": [
        {"id": x.id, "kind": x.kind, "direction": x.direction, "amount": str(x.amount),
         "currency": x.currency, "payment_id": x.payment_id, "created_at": x.created_at}
        for x in rows
    ]}


@router.get("/api/me/gifts")
async def purchased_gifts(request: Request, db: AsyncSession = Depends(get_db)):
    from .main import user_from_token

    user = await user_from_token(request, db)
    # No recipient identity or redeemable token is exposed after activation.
    rows = (await db.execute(
        select(GiftCode, Plan.name).outerjoin(Plan, Plan.id == GiftCode.plan_id)
        .where(GiftCode.purchaser_user_id == user.id)
        .order_by(GiftCode.id.desc()).limit(100)
    )).all()
    ids = [gift.id for gift, _ in rows]
    redemptions = (await db.execute(
        select(GiftRedemption).where(GiftRedemption.gift_code_id.in_(ids))
    )).scalars().all() if ids else []
    states = {x.gift_code_id: x.status for x in redemptions}
    now=datetime.utcnow()
    return [{"id": gift.id, "plan": title or f"Тариф #{gift.plan_id}",
             "code": gift.code if gift.enabled and not gift.used_count and gift.id not in states and (not gift.expires_at or gift.expires_at>now) else None,
             "status": states.get(gift.id, "used" if gift.used_count else "expired" if gift.expires_at and gift.expires_at<=now else "ready" if gift.enabled else "disabled"),
             "created_at": gift.created_at, "expires_at": gift.expires_at}
            for gift, title in rows]
