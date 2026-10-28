"""V24-V28 customer/support/security operations: admin and customer endpoints moved out of main.py (v28.28.0).

Names that belong to main are read through ``shop.<name>`` at call time, so tests and
operators that patch ``app.main`` keep affecting this code exactly as before."""
from .db import get_db
from fastapi import Depends
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from . import main as shop

# ---------- V24-V28 customer/support/security operations ----------
# Store support is canonical; Support Pro uses the scoped bridge API.
@shop.app.post("/api/me/support/tickets")
async def create_support_ticket(payload:shop.TicketIn, request:Request, db:AsyncSession=Depends(get_db)):
    user=await shop.user_from_token(request,db)
    if not payload.subject.strip() or not payload.message.strip(): raise shop.HTTPException(400,"Укажите тему и сообщение")
    t=shop.SupportTicket(user_id=user.id, subject=payload.subject.strip(), message=payload.message.strip())
    db.add(t); await db.commit(); await db.refresh(t)
    from .node_health import _load
    from .support_autoreply import DEFAULT as AUTOREPLY, KEY as AUTOREPLY_KEY, after_ticket
    if (await _load(db, AUTOREPLY_KEY, AUTOREPLY))["enabled"]:
        shop._track_task(after_ticket(t.id))  # an answer from the knowledge base when it clearly fits
    return {"id":t.id,"status":t.status}

# Store support is canonical; Support Pro uses the scoped bridge API.
@shop.app.get("/api/me/support/tickets")
async def my_support_tickets(request:Request,db:AsyncSession=Depends(get_db)):
    user=await shop.user_from_token(request,db)
    rows=(await db.execute(shop.select(shop.SupportTicket).where(shop.SupportTicket.user_id==user.id).order_by(shop.SupportTicket.id.desc()).limit(100))).scalars().all()
    return [{"id":x.id,"subject":x.subject,"message":x.message,"status":x.status,"admin_reply":x.admin_reply,"merged_into_id":x.merged_into_id,"created_at":x.created_at,"updated_at":x.updated_at} for x in rows]

@shop.app.post("/api/me/referral/withdrawals")
async def request_withdrawal(payload:shop.WithdrawalIn,request:Request,db:AsyncSession=Depends(get_db)):
    user=await shop.user_from_token(request,db)
    from .app_config import load_overrides
    if not (await load_overrides(db)).referral.withdraw_enabled: raise shop.HTTPException(409,"Вывод реферальных средств отключён администратором")
    amount=payload.amount.quantize(shop.Decimal("0.01"))
    if amount < shop.Decimal("1.00"): raise shop.HTTPException(400,"Minimum withdrawal is 1.00")
    destination=payload.destination.strip()
    if not destination or len(destination)>255: raise shop.HTTPException(400,"Invalid withdrawal destination")
    idem=request.headers.get("Idempotency-Key")
    if idem is not None:
        if not idem.strip() or len(idem)>128: raise shop.HTTPException(400,"Invalid Idempotency-Key")
        key=int.from_bytes(shop.hashlib.sha256(f"withdrawal:{user.id}:{idem}".encode()).digest()[:8],"big",signed=True)
        await shop._advisory_lock(db, key)
        existing=(await db.execute(shop.select(shop.WithdrawalRequest).where(shop.WithdrawalRequest.user_id==user.id,shop.WithdrawalRequest.idempotency_key==idem))).scalar_one_or_none()
        if existing:
            if existing.amount!=amount or existing.destination!=destination: raise shop.HTTPException(409,"Idempotency-Key уже использован для другой выплаты")
            return {"id":existing.id,"status":existing.status,"amount":str(existing.amount)}
    result=await db.execute(shop.sql_text("UPDATE users SET referral_balance=referral_balance-:amount WHERE id=:uid AND referral_balance>=:amount"),{"amount":amount,"uid":user.id})
    if result.rowcount != 1: raise shop.HTTPException(400,"Insufficient referral balance")
    row=shop.WithdrawalRequest(user_id=user.id,amount=amount,destination=destination,status="requested",idempotency_key=idem)
    db.add(row); await db.flush()
    db.add(shop.ReferralLedger(user_id=user.id,source_user_id=None,payment_id=None,amount=-amount,kind=f"withdrawal:{row.id}"))
    await shop.audit(db,"referral.withdrawal.requested",f"user:{user.id}",str(row.id),{"amount":str(amount)}); await db.commit(); await db.refresh(row)
    return {"id":row.id,"status":row.status,"amount":str(row.amount)}

@shop.app.get("/api/me/referral/withdrawals")
async def my_withdrawals(request:Request,db:AsyncSession=Depends(get_db)):
    user=await shop.user_from_token(request,db)
    rows=(await db.execute(shop.select(shop.WithdrawalRequest).where(shop.WithdrawalRequest.user_id==user.id).order_by(shop.WithdrawalRequest.id.desc()).limit(100))).scalars().all()
    return [{"id":x.id,"amount":str(x.amount),"destination":x.destination,"status":x.status,"created_at":x.created_at} for x in rows]

@shop.app.get("/api/me/dashboard")
async def customer_dashboard(request:Request,db:AsyncSession=Depends(get_db)):
    user=await shop.user_from_token(request,db)
    sub=(await db.execute(shop.select(shop.Subscription).where(shop.Subscription.user_id==user.id,shop.Subscription.is_primary.is_(True)))).scalar_one_or_none()
    payments=(await db.execute(shop.select(shop.Payment).where(shop.Payment.user_id==user.id).order_by(shop.Payment.id.desc()).limit(10))).scalars().all()
    tickets=(await db.execute(shop.select(shop.SupportTicket).where(shop.SupportTicket.user_id==user.id).order_by(shop.SupportTicket.id.desc()).limit(5))).scalars().all()
    return {"user":{"id":user.id,"username":user.username,"email":user.email,"referral_code":user.referral_code,"referral_balance":str(user.referral_balance),"wallet_balance":str(user.wallet_balance or 0),"auto_renew_enabled":user.auto_renew_enabled},"subscription":None if not sub else {"id":sub.id,"name":sub.name,"plan_id":sub.plan_id,"expires_at":sub.expires_at,"subscription_url":sub.subscription_url,"status":sub.lifecycle_status,"auto_renew_enabled":user.auto_renew_enabled},"payments":[{"id":p.id,"amount":str(p.amount),"currency":p.currency,"status":p.status,"fulfillment_status":p.fulfillment_status,"created_at":p.created_at} for p in payments],"tickets":[{"id":t.id,"subject":t.subject,"status":t.status} for t in tickets]}


__all__ = ['create_support_ticket', 'customer_dashboard', 'my_support_tickets', 'my_withdrawals', 'request_withdrawal']
# Imported before main finished (``from app import customer_ops_api`` first)? Then main's star
# import saw a half-loaded module; hand the names over now that they exist.
shop.__dict__.update({_n: globals()[_n] for _n in __all__})
