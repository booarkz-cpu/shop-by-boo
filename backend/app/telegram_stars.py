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
from datetime import datetime, timedelta
from decimal import ROUND_CEILING, Decimal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import get_db
from .models import Payment, Plan, StarsSubscription, User

logger = logging.getLogger(__name__)
router = APIRouter()
PROVIDER = "telegram_stars"
CURRENCY = "XTR"


class StarsError(RuntimeError):
    """Telegram rejected a Stars call or an update does not match its order."""


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
    if not order_id.startswith(("stars-", "starsub-")):
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


async def record_successful_payment(db: AsyncSession, *, order_id: str, currency: str, total: int, telegram_id: int, charge_id: str,
                                    is_recurring: bool = False, is_first_recurring: bool = False, period_end: datetime | None = None) -> dict:
    from . import main
    if order_id.startswith("starsub-"):
        return await record_subscription_payment(db, order_id=order_id, currency=currency, total=total, telegram_id=telegram_id,
                                                 charge_id=charge_id, period_end=period_end)
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


# ---------------------------------------------------------------- Stars subscriptions
#
# A 30-day plan can be bought as a Telegram Stars subscription (createInvoiceLink with
# subscription_period=2592000). Telegram charges the customer every 30 days and sends the
# bot a successful_payment with the same invoice payload: the first one activates the shop
# subscription, every next one is stored as its own Payment (order "<payload>:r<n>") and
# extends it through the common fulfillment. editUserStarSubscription cancels renewals.

PERIOD_SECONDS = 2592000
LAPSE_GRACE = timedelta(days=3)


class SubscriptionIn(BaseModel):
    plan_id: int = Field(gt=0)
    subscription_id: int | None = Field(default=None, gt=0)


async def _stars_settings(db: AsyncSession):
    from .app_config import load_overrides
    stars = (await load_overrides(db)).wallet.stars
    if not (stars.enabled and stars.subscriptions) or not settings.bot_token:
        raise HTTPException(503, "Подписка за Telegram Stars не включена")
    return stars


@router.post("/api/me/stars-subscriptions")
async def create_stars_subscription(payload: SubscriptionIn, request: Request, db: AsyncSession = Depends(get_db)):
    from . import main
    from .app_config import require_consent
    from .platform_api import reject_restricted
    from .referral_program import snapshot as referral_snapshot
    from .subscriptions import reserve_target
    if await main.maintenance_enabled(db):
        raise HTTPException(503, "Service is in maintenance mode")
    if not await main.feature_enabled(db, "payments", True) or not await main.production_payments_allowed(db):
        raise HTTPException(503, "Приём платежей временно остановлен администратором")
    stars_cfg = await _stars_settings(db)
    user = await main.user_from_token(request, db)
    reject_restricted(user)
    await require_consent(db, user)
    if not user.telegram_id:
        raise HTTPException(409, "Подписка за Stars доступна в Telegram: откройте магазин из бота")
    plan = await db.get(Plan, payload.plan_id)
    if not plan or not plan.enabled:
        raise HTTPException(404, "Тариф не найден")
    if plan.duration_days != 30:
        raise HTTPException(409, "Подписка за Stars продлевается каждые 30 дней: выберите тариф на 30 дней")
    amount = main._money(plan.price)
    stars = stars_for(amount, stars_cfg.rate)
    if stars < 1 or stars > 10000:
        raise HTTPException(400, "Цена подписки в Stars должна быть от 1 до 10000")
    await main.ensure_required_channel(user)
    target = await reserve_target(db, user, plan.id, payload.model_dump(exclude={"plan_id"}))
    order_id = f"starsub-{user.id}-{hashlib.sha256((str(user.id) + str(datetime.utcnow().timestamp()) + str(target.id)).encode()).hexdigest()[:20]}"
    # Partner attribution follows the subscription: the latest partner order of this profile.
    from .partners import latest_partner_order
    previous = await latest_partner_order(db, target.id)
    reseller = {"reseller_id": previous.reseller_id, "reseller_slug_snapshot": previous.reseller_slug_snapshot,
                "reseller_percent_snapshot": previous.reseller_percent_snapshot} if previous else {}
    sub_row = StarsSubscription(order_id=order_id, user_id=user.id, plan_id=plan.id, subscription_id=target.id, stars_amount=stars,
                                amount=amount, reseller_id=reseller.get("reseller_id"), reseller_percent_snapshot=reseller.get("reseller_percent_snapshot"))
    db.add(sub_row)
    db.add(Payment(user_id=user.id, subscription_id=target.id, plan_id=plan.id, provider=PROVIDER, order_id=order_id, amount=amount,
                   original_amount=amount, discount_amount=Decimal("0.00"), duration_days_snapshot=plan.duration_days,
                   traffic_limit_gb_snapshot=plan.traffic_limit_gb, device_limit_snapshot=plan.device_limit,
                   remnawave_profile_id_snapshot=plan.remnawave_profile_id, referrer_id_snapshot=user.referred_by_id,
                   referral_terms_snapshot=await referral_snapshot(db, user), currency=settings.default_currency, status="creating",
                   fulfillment_status="pending", purpose="subscription", bonus_days=0, stars_amount=stars, **reseller))
    await db.commit()
    try:
        data = await bot_api("createInvoiceLink", {
            "title": f"Подписка {plan.name}"[:32], "description": f"VPN {plan.name}: продление каждые 30 дней"[:255],
            "payload": order_id, "currency": CURRENCY, "prices": [{"label": plan.name[:32], "amount": stars}],
            "subscription_period": PERIOD_SECONDS,
        })
    except Exception as exc:
        payment = await _order(db, order_id)
        payment.status, payment.fulfillment_terminal, payment.fulfillment_error = "failed", True, str(exc)[:1000]
        sub_row.status = "failed"
        await db.commit()
        raise HTTPException(502, "Telegram не создал подписку в Stars: " + str(exc)[:200])
    payment = await _order(db, order_id)
    payment.checkout_url, payment.status = str(data["result"]), "pending"
    await db.commit()
    return {"url": payment.checkout_url, "stars": stars, "amount": str(amount), "order_id": order_id, "period_days": 30}


async def record_subscription_payment(db: AsyncSession, *, order_id: str, currency: str, total: int, telegram_id: int, charge_id: str,
                                      period_end: datetime | None) -> dict:
    """First charge activates the subscription; each renewal is a new Payment fulfilled once."""
    from . import main
    sub_row = await db.scalar(select(StarsSubscription).where(StarsSubscription.order_id == order_id).with_for_update())
    if not sub_row:
        raise StarsError(f"unknown Stars subscription {order_id}")
    user = await db.get(User, sub_row.user_id)
    if currency != CURRENCY or total != sub_row.stars_amount or not user or int(user.telegram_id or 0) != int(telegram_id):
        await main.audit(db, "payment.stars.mismatch", "telegram", order_id, {"currency": currency, "total": total})
        await db.commit()
        raise StarsError("Stars subscription amount, currency or customer mismatch")
    provider_id = f"{int(telegram_id)}:{charge_id}"[:255]
    duplicate = await db.scalar(select(Payment).where(Payment.provider == PROVIDER, Payment.provider_payment_id == provider_id))
    if duplicate:
        return await main._confirm_and_fulfill_payment(duplicate.id, db)
    first = await _order(db, order_id)
    if first and not first.provider_payment_id and first.status == "pending":
        payment = first
        sub_row.first_charge_id = charge_id
        sub_row.status = "active"
    else:
        if sub_row.status == "canceled":
            await main.audit(db, "payment.stars.renewal_after_cancel", "telegram", order_id, {"charge": charge_id})
        sub_row.renewals += 1
        source = first
        target_sub = source.subscription_id if source else sub_row.subscription_id
        payment = Payment(user_id=sub_row.user_id, subscription_id=target_sub, plan_id=sub_row.plan_id, provider=PROVIDER,
                          order_id=f"{order_id}:r{sub_row.renewals}", amount=sub_row.amount, original_amount=sub_row.amount,
                          discount_amount=Decimal("0.00"), duration_days_snapshot=30,
                          traffic_limit_gb_snapshot=source.traffic_limit_gb_snapshot if source else None,
                          device_limit_snapshot=source.device_limit_snapshot if source else None,
                          remnawave_profile_id_snapshot=source.remnawave_profile_id_snapshot if source else None,
                          referrer_id_snapshot=source.referrer_id_snapshot if source else None,
                          referral_terms_snapshot=source.referral_terms_snapshot if source else None,
                          currency=settings.default_currency, status="pending", fulfillment_status="pending", purpose="subscription",
                          bonus_days=0, stars_amount=sub_row.stars_amount, reseller_id=sub_row.reseller_id,
                          reseller_percent_snapshot=sub_row.reseller_percent_snapshot,
                          reseller_slug_snapshot=source.reseller_slug_snapshot if source else None)
        db.add(payment)
        await db.flush()
    payment.provider_payment_id = provider_id
    sub_row.current_period_end = period_end or sub_row.current_period_end
    await main.audit(db, "payment.stars.subscription_paid", f"user:{sub_row.user_id}", str(payment.id),
                     {"order": order_id, "renewal": sub_row.renewals, "stars": total})
    await db.commit()
    return await main._confirm_and_fulfill_payment(payment.id, db)


@router.get("/api/me/stars-subscriptions")
async def my_stars_subscriptions(request: Request, db: AsyncSession = Depends(get_db)):
    from . import main
    user = await main.user_from_token(request, db)
    rows = (await db.execute(select(StarsSubscription).where(StarsSubscription.user_id == user.id, StarsSubscription.status.in_(("active", "canceled")))
                             .order_by(StarsSubscription.id.desc()))).scalars().all()
    plans = {p.id: p.name for p in (await db.execute(select(Plan).where(Plan.id.in_([r.plan_id for r in rows] or [0])))).scalars()}
    lapse = datetime.utcnow() - LAPSE_GRACE
    # A customer can cancel in Telegram settings without the bot being told: once a period ends
    # with no renewal for LAPSE_GRACE the subscription is shown as ended instead of active.
    status = lambda r: "ended" if r.status == "active" and r.current_period_end and r.current_period_end < lapse else r.status  # noqa: E731
    return [{"id": r.id, "plan": plans.get(r.plan_id, ""), "stars": r.stars_amount, "amount": str(r.amount), "status": status(r),
             "renewals": r.renewals, "current_period_end": r.current_period_end, "subscription_id": r.subscription_id} for r in rows]


@router.post("/api/me/stars-subscriptions/{row_id}/cancel")
async def cancel_stars_subscription(row_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    from . import main
    user = await main.user_from_token(request, db)
    row = await db.scalar(select(StarsSubscription).where(StarsSubscription.id == row_id, StarsSubscription.user_id == user.id).with_for_update())
    if not row or row.status not in {"active", "canceled"}:
        raise HTTPException(404, "Подписка за Stars не найдена")
    if row.status == "active":
        try:
            await bot_api("editUserStarSubscription", {"user_id": int(user.telegram_id), "telegram_payment_charge_id": row.first_charge_id,
                                                       "is_canceled": True})
        except StarsError as exc:
            raise HTTPException(502, "Telegram не отменил подписку: " + str(exc)[:200])
        row.status, row.canceled_at = "canceled", datetime.utcnow()
        await main.audit(db, "payment.stars.subscription_canceled", f"user:{user.id}", str(row.id))
        await db.commit()
    return {"ok": True, "status": row.status, "active_until": row.current_period_end}
