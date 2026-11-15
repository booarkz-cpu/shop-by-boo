"""Smart cart: «не хватило на балансе → пополнил → покупка сама».

When a purchase from the wallet lacks money, the cabinet, Mini App, bot and apps offer «Пополнить и купить»: the
purchase is put in the cart (``POST /api/me/cart`` — the same body as ``/api/me/wallet/spend``) and the customer tops
up the difference. When the top-up lands, the cart is bought from the wallet by itself (same checks, ledger and
idempotency as a manual purchase) and the customer gets a message. A cart lives 24 hours; one per customer.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db

logger = logging.getLogger("vpnshop.cart")
router = APIRouter()
LIFETIME = timedelta(hours=24)


async def price_of(db: AsyncSession, payload: dict) -> Decimal:
    from .models import Plan
    if payload.get("constructor_id") not in (None, "", 0, "0"):
        from .tariff_api import quote_constructor
        return Decimal(str((await quote_constructor(db, payload))["amount"]))
    plan = await db.get(Plan, int(payload.get("plan_id") or 0))
    if not plan or not plan.enabled:
        raise HTTPException(404, "Тариф не найден")
    return Decimal(str(plan.price))


async def buy_cart(db: AsyncSession, user_id: int, now: datetime | None = None) -> dict | None:
    """Buy the cart from the wallet if it covers it now; returns the purchase result or None."""
    from .customer_api import spend_from_wallet
    from .models import ShopCart, User
    now = now or datetime.utcnow()
    cart = await db.get(ShopCart, user_id)
    if not cart:
        return None
    if cart.expires_at < now:
        await db.delete(cart)
        await db.commit()
        return None
    user = await db.get(User, user_id)
    if not user or Decimal(str(user.wallet_balance or 0)) < Decimal(str(cart.amount)):
        return None
    key = f"cart-{user_id}-{int(cart.created_at.timestamp())}"
    payload = dict(cart.payload)
    try:
        result = await spend_from_wallet(db, user, payload, key)
    except HTTPException as exc:
        logger.info("cart of %s not bought: %s", user_id, exc.detail)
        return None
    cart = await db.get(ShopCart, user_id)
    if cart:
        await db.delete(cart)
    from .activity_log import record
    record(db, user_id, "system", "cart.bought", {"payment": result.get("payment_id")})
    await db.commit()
    from .main import notify_user_telegram
    await notify_user_telegram(user.telegram_id, "Баланс пополнен — покупка из корзины оплачена, подписка обновлена. "
                                                 "Top-up received — your cart was paid and the subscription is updated.")
    return result


async def after_topup(user_id: int) -> None:
    """Called after a wallet top-up is credited (in a task: the top-up still holds the customer's lock)."""
    from .db import SessionLocal
    for attempt in range(3):
        await asyncio.sleep(2 + attempt * 3)
        try:
            async with SessionLocal() as db:
                await buy_cart(db, user_id)
                return
        except Exception as exc:  # noqa: BLE001 — lock still held or a transient error: try again
            logger.info("cart purchase attempt %s for %s: %s", attempt + 1, user_id, exc)


@router.post("/api/me/cart")
async def put_cart(payload: dict, request: Request, db: AsyncSession = Depends(get_db)):
    """Remember the purchase; answers how much to top up (0 → the wallet covers it already: buy it right away)."""
    from .main import user_from_token
    from .models import ShopCart
    user = await user_from_token(request, db)
    body = {k: payload[k] for k in ("plan_id", "constructor_id", "device_option_id", "traffic_option_id", "days_option_id",
                                     "subscription_id", "new_subscription", "promo_code") if k in payload}
    amount = await price_of(db, body)
    now = datetime.utcnow()
    cart = await db.get(ShopCart, user.id)
    if cart:
        cart.payload, cart.amount, cart.created_at, cart.expires_at = body, amount, now, now + LIFETIME
    else:
        db.add(ShopCart(user_id=user.id, payload=body, amount=amount, created_at=now, expires_at=now + LIFETIME))
    from .activity_log import record
    record(db, user.id, "system", "cart.saved", {"amount": amount})
    await db.commit()
    missing = max(Decimal("0"), amount - Decimal(str(user.wallet_balance or 0)))
    if missing == 0:
        result = await buy_cart(db, user.id)
        return {"bought": bool(result), "topup": "0.00", "amount": str(amount)}
    # Payment gateways have minimum amounts; the wallet top-up minimum is 50.
    return {"bought": False, "topup": str(max(missing, Decimal("50.00")).quantize(Decimal("0.01"))), "amount": str(amount)}


@router.get("/api/me/cart")
async def get_cart(request: Request, db: AsyncSession = Depends(get_db)):
    from .main import user_from_token
    from .models import ShopCart
    user = await user_from_token(request, db)
    cart = await db.get(ShopCart, user.id)
    if not cart or cart.expires_at < datetime.utcnow():
        return {"cart": None}
    return {"cart": {"payload": cart.payload, "amount": str(cart.amount), "expires_at": cart.expires_at.isoformat()}}


@router.delete("/api/me/cart")
async def delete_cart(request: Request, db: AsyncSession = Depends(get_db)):
    from .main import user_from_token
    from .models import ShopCart
    user = await user_from_token(request, db)
    cart = await db.get(ShopCart, user.id)
    if cart:
        await db.delete(cart)
        await db.commit()
    return {"ok": True}
