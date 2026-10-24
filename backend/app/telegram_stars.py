"""Wallet top-up with Telegram Stars (currency XTR) for the Mini App.

Flow (Bot API "Payments in Telegram Stars"):
1. ``POST /api/me/wallet/stars-invoice {amount}`` — the shop amount is converted to Stars
   with the administrator's rate (``app_config.wallet.stars.rate`` = shop currency per Star,
   rounded up), a ``Payment`` row is stored (provider ``telegram_stars``, purpose ``topup``,
   exact ``stars_amount``) and ``createInvoiceLink`` returns a link for
   ``Telegram.WebApp.openInvoice``.
2. The bot answers ``pre_checkout_query`` only for a pending order with the same Stars
   amount and currency XTR (:func:`check_pre_checkout`).
3. ``successful_payment`` (:func:`record_successful_payment`) checks the order again, stores
   ``<telegram user id>:<telegram_payment_charge_id>`` as the provider payment id and runs
   the common confirm-and-fulfill path, which credits the wallet once.
Refunds use ``refundStarPayment``; a repeated refund of the same charge counts as done.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from decimal import ROUND_CEILING, Decimal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import get_db
from .models import Payment

logger = logging.getLogger(__name__)
router = APIRouter()
PROVIDER = "telegram_stars"
CURRENCY = "XTR"


class StarsError(RuntimeError):
    pass


async def bot_api(method: str, payload: dict) -> dict:
    if not settings.bot_token:
        raise StarsError("BOT_TOKEN is not configured")
    async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
        r = await client.post(f"https://api.telegram.org/bot{settings.bot_token}/{method}", json=payload)
    data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if not data.get("ok"):
        raise StarsError(str(data.get("description") or f"HTTP {r.status_code}"))
    return data


def stars_for(amount: Decimal, rate: Decimal) -> int:
    return int((amount / rate).to_integral_value(rounding=ROUND_CEILING))


class InvoiceIn(BaseModel):
    amount: Decimal = Field(gt=0, le=100000)


@router.post("/api/me/wallet/stars-invoice")
async def stars_invoice(payload: InvoiceIn, request: Request, db: AsyncSession = Depends(get_db)):
    from . import main
    from .app_config import load_overrides, require_consent
    if await main.maintenance_enabled(db):
        raise HTTPException(503, "Service is in maintenance mode")
    if not await main.feature_enabled(db, "payments", True) or not await main.production_payments_allowed(db):
        raise HTTPException(503, "Приём платежей временно остановлен администратором")
    stars_cfg = (await load_overrides(db)).wallet.stars
    if not stars_cfg.enabled or not settings.bot_token:
        raise HTTPException(503, "Оплата Telegram Stars не включена")
    user = await main.user_from_token(request, db)
    from .platform_api import reject_restricted
    reject_restricted(user)
    await require_consent(db, user)
    if not user.telegram_id:
        raise HTTPException(409, "Оплата Stars доступна в Telegram: откройте магазин из бота")
    idem = request.headers.get("Idempotency-Key")
    if not idem or len(idem) > 128:
        raise HTTPException(400, "Idempotency-Key is required")
    amount = main._money(payload.amount)
    if amount < Decimal("50"):
        raise HTTPException(400, "Amount is outside the allowed top-up range")
    stars = stars_for(amount, stars_cfg.rate)
    if stars < stars_cfg.min_stars or stars > 100000:
        raise HTTPException(400, f"Сумма в Stars должна быть от {stars_cfg.min_stars} до 100000")
    existing = (await db.execute(select(Payment).where(Payment.user_id == user.id, Payment.idempotency_key == idem))).scalar_one_or_none()
    if existing:
        if existing.provider != PROVIDER:
            raise HTTPException(409, "Idempotency-Key уже использован для другого платежа")
        return {"url": existing.checkout_url, "stars": existing.stars_amount, "amount": str(existing.amount), "order_id": existing.order_id}
    await main.ensure_required_channel(user)
    order_id = f"stars-{user.id}-{hashlib.sha256(idem.encode()).hexdigest()[:24]}"
    row = Payment(user_id=user.id, plan_id=0, provider=PROVIDER, order_id=order_id, amount=amount, original_amount=amount,
                  discount_amount=Decimal("0.00"), currency=settings.default_currency, status="creating", fulfillment_status="pending",
                  idempotency_key=idem, purpose="topup", bonus_days=0, stars_amount=stars)
    db.add(row)
    await db.commit()
    try:
        data = await bot_api("createInvoiceLink", {
            "title": "Пополнение баланса"[:32], "description": f"Пополнение баланса на {amount} {settings.default_currency}"[:255],
            "payload": order_id, "currency": CURRENCY, "prices": [{"label": "Пополнение", "amount": stars}],
        })
    except Exception as exc:
        row.status = "failed"
        row.fulfillment_terminal = True
        row.fulfillment_error = str(exc)[:1000]
        await db.commit()
        raise HTTPException(502, "Telegram не создал счёт в Stars: " + str(exc)[:200])
    row.checkout_url = str(data["result"])
    row.status = "pending"
    await db.commit()
    return {"url": row.checkout_url, "stars": stars, "amount": str(amount), "order_id": order_id}


async def _order(db: AsyncSession, order_id: str) -> Payment | None:
    if not order_id.startswith("stars-"):
        return None
    return (await db.execute(select(Payment).where(Payment.order_id == order_id, Payment.provider == PROVIDER))).scalar_one_or_none()


async def check_pre_checkout(db: AsyncSession, *, order_id: str, currency: str, total: int, telegram_id: int) -> str | None:
    """Return None to accept the pre-checkout query, or a customer-facing error."""
    from .models import User
    payment = await _order(db, order_id)
    if not payment or payment.status != "pending":
        return "Счёт устарел. Создайте новый в приложении."
    user = await db.get(User, payment.user_id)
    if currency != CURRENCY or total != payment.stars_amount or not user or int(user.telegram_id or 0) != int(telegram_id):
        return "Счёт не совпадает с заказом. Создайте новый в приложении."
    return None


async def record_successful_payment(db: AsyncSession, *, order_id: str, currency: str, total: int, telegram_id: int, charge_id: str) -> dict:
    from . import main
    payment = await _order(db, order_id)
    if not payment:
        raise StarsError(f"unknown Stars order {order_id}")
    if currency != CURRENCY or total != payment.stars_amount:
        await main.audit(db, "payment.stars.mismatch", "telegram", str(payment.id), {"currency": currency, "total": total})
        await db.commit()
        raise StarsError("Stars amount or currency mismatch")
    provider_id = f"{int(telegram_id)}:{charge_id}"[:255]
    if payment.provider_payment_id and payment.provider_payment_id != provider_id:
        raise StarsError("Stars order already bound to another charge")
    if not payment.provider_payment_id:
        payment.provider_payment_id = provider_id
        await main.audit(db, "payment.stars.paid", f"user:{payment.user_id}", str(payment.id), {"stars": total})
        await db.commit()
    return await main._confirm_and_fulfill_payment(payment.id, db)


class TelegramStarsProvider:
    """Refund adapter used by the common refund flow (provider_payment_id = 'user:charge')."""

    async def refund(self, payment_id: str, amount=None, currency: str = "", reason: str = ""):
        user_id, _, charge = str(payment_id).partition(":")
        if not user_id.isdigit() or not charge:
            raise StarsError("Malformed Telegram Stars payment id")
        try:
            await bot_api("refundStarPayment", {"user_id": int(user_id), "telegram_payment_charge_id": charge})
        except StarsError as exc:
            if "CHARGE_ALREADY_REFUNDED" not in str(exc).upper():
                raise
        return {"id": f"stars-refund-{charge}", "status": "succeeded"}

    async def get_refund_status(self, refund_id: str) -> str:
        # refundStarPayment is synchronous: a stored refund id means Telegram accepted it.
        return "succeeded"
