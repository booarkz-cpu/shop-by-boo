"""Reseller orders API: a partner sells subscriptions in its own bot or site and gets them from the shop by API.

``POST /api/reseller/orders`` (the reseller key, the same as for ``/api/reseller/catalog``) with a plan and the
partner's own customer reference creates — or renews — that customer's subscription and answers with the
subscription link. The wholesale price (plan price minus the reseller's commission percent) is taken from the
reseller balance (its commissions plus deposits the owner books in «Партнёры → Пополнить баланс»). The same
reference always means the same customer, so a renewal extends the existing subscription. ``Idempotency-Key`` is
required: a repeated request returns the same order and never charges twice.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import require_permission

logger = logging.getLogger("vpnshop.reseller")
router = APIRouter()


class OrderIn(BaseModel):
    plan_id: int = Field(gt=0)
    customer_ref: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:-]+$")


class DepositIn(BaseModel):
    amount: Decimal = Field(gt=0, le=10_000_000, max_digits=14, decimal_places=2)
    note: str = Field("", max_length=200)


def wholesale(price: Decimal, commission_percent: Decimal) -> Decimal:
    return (Decimal(str(price)) * (Decimal("100") - Decimal(str(commission_percent))) / Decimal("100")).quantize(Decimal("0.01"))


def _order_view(payment, sub) -> dict:
    return {"order_id": payment.order_id, "status": payment.fulfillment_status, "amount": str(payment.amount),
            "subscription_url": getattr(sub, "subscription_url", None),
            "expires_at": sub.expires_at.isoformat() if sub and sub.expires_at else None}


@router.post("/api/reseller/orders")
async def create_order(payload: OrderIn, request: Request, db: AsyncSession = Depends(get_db)):
    from .main import _acquire_user_fulfillment_lock, _release_payment_side_effect_lock, fulfill, record_financial_event
    from .marketplace_api import _reseller_from_request
    from .models import Payment, Plan, Reseller, Subscription, User
    reseller = await _reseller_from_request(request, db)
    idem = request.headers.get("Idempotency-Key") or ""
    if not idem or len(idem) > 100:
        raise HTTPException(400, "Idempotency-Key is required")
    order_id = f"reseller-{reseller.id}-{hashlib.sha256(idem.encode()).hexdigest()[:24]}"
    existing = await db.scalar(select(Payment).where(Payment.order_id == order_id))
    if existing:
        sub = await db.get(Subscription, existing.subscription_id) if existing.subscription_id else None
        return _order_view(existing, sub)
    plan = await db.get(Plan, payload.plan_id)
    if not plan or not plan.enabled or (reseller.plan_ids and plan.id not in reseller.plan_ids):
        raise HTTPException(404, "Тариф недоступен этому партнёру")
    username = f"r{reseller.id}:{payload.customer_ref}"[:255]
    customer = await db.scalar(select(User).where(User.username == username, User.email.is_(None), User.telegram_id.is_(None)))
    if not customer:
        import secrets
        customer = User(username=username, referral_code=secrets.token_urlsafe(8).upper(), acquisition_source=f"reseller_{reseller.slug}"[:48])
        db.add(customer)
        await db.flush()
    price = wholesale(plan.price, reseller.commission_percent)
    reseller = await db.scalar(select(Reseller).where(Reseller.id == reseller.id).with_for_update().execution_options(populate_existing=True))
    if Decimal(str(reseller.balance or 0)) < price:
        raise HTTPException(402, f"Недостаточно средств на балансе партнёра: нужно {price}")
    target = await db.scalar(select(Subscription).where(Subscription.user_id == customer.id, Subscription.is_primary.is_(True)))
    reseller.balance = (Decimal(str(reseller.balance)) - price).quantize(Decimal("0.01"))
    payment = Payment(user_id=customer.id, subscription_id=target.id if target else None, plan_id=plan.id, provider="reseller",
                      order_id=order_id, amount=price, original_amount=Decimal(str(plan.price)), discount_amount=Decimal(str(plan.price)) - price,
                      duration_days_snapshot=plan.duration_days, traffic_limit_gb_snapshot=plan.traffic_limit_gb,
                      device_limit_snapshot=plan.device_limit, remnawave_profile_id_snapshot=plan.remnawave_profile_id,
                      currency="RUB", status="paid", fulfillment_status="pending", idempotency_key=f"reseller:{idem}"[:128],
                      purpose="subscription", paid_at=datetime.utcnow())
    db.add(payment)
    await db.flush()
    await record_financial_event(db, operation_key=f"reseller-order:{payment.id}", user_id=customer.id, payment_id=payment.id,
                                 kind="reseller_order", direction="debit", amount=price, currency="RUB",
                                 metadata={"reseller_id": reseller.id, "customer_ref": payload.customer_ref})
    await db.commit()
    lock, token = await _acquire_user_fulfillment_lock(customer.id, ttl=600)
    try:
        await fulfill(payment.id, db, existing_user_lock_token=token)
    except Exception as exc:  # noqa: BLE001 — the retry queue finishes it; the partner polls GET /api/reseller/orders/{id}
        logger.info("reseller order %s queued for retry: %s", payment.order_id, exc)
    finally:
        await _release_payment_side_effect_lock(lock, token)
    payment = await db.scalar(select(Payment).where(Payment.id == payment.id).execution_options(populate_existing=True))
    sub = await db.get(Subscription, payment.subscription_id) if payment.subscription_id else None
    return _order_view(payment, sub)


@router.get("/api/reseller/orders/{order_id}")
async def get_order(order_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    from .marketplace_api import _reseller_from_request
    from .models import Payment, Subscription
    reseller = await _reseller_from_request(request, db)
    payment = await db.scalar(select(Payment).where(Payment.order_id == order_id))
    if not payment or not order_id.startswith(f"reseller-{reseller.id}-"):
        raise HTTPException(404, "Заказ не найден")
    sub = await db.get(Subscription, payment.subscription_id) if payment.subscription_id else None
    return _order_view(payment, sub)


@router.post("/api/admin/marketplace/resellers/{reseller_id}/deposit")
async def deposit(reseller_id: int, payload: DepositIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("referrals.reconcile"))):
    from .main import audit
    from .models import Reseller
    row = await db.scalar(select(Reseller).where(Reseller.id == reseller_id).with_for_update())
    if not row:
        raise HTTPException(404, "Партнёр не найден")
    row.balance = (Decimal(str(row.balance or 0)) + payload.amount).quantize(Decimal("0.01"))
    await audit(db, "marketplace.reseller.deposit", admin.email, str(row.id), {"amount": str(payload.amount), "note": payload.note})
    await db.commit()
    return {"balance": str(row.balance)}
