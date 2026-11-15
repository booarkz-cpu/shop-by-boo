"""Tribute (v28.44): wallet top-up by a donation in Telegram.

Tribute is not an order gateway: the customer pays through the shop's donation link inside Telegram, and Tribute tells
the shop who paid (``telegram_user_id``) and how much. So Tribute is not in the gateway queue; it only tops up the
wallet of the customer with that Telegram account, and the balance is then spent on plans as usual.

The notification (``POST /api/webhooks/tribute``) is signed in ``trbt-signature`` — HMAC-SHA256 hex of the raw body with
the API key. Tribute has no API to read a donation back, so the signature is the proof; each donation is credited once
(the event key is the donation link, the payer, the amount and the time of the event). Only ``new_donation`` and
``recurrent_donation`` in the shop's currency are credited; anything else is acknowledged and logged.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import get_db

logger = logging.getLogger("vpnshop.tribute")
router = APIRouter()
EVENTS = {"new_donation", "recurrent_donation"}


def configured() -> bool:
    return bool(settings.tribute_api_key and settings.tribute_donate_link)


def signature(body: bytes) -> str:
    return hmac.new(settings.tribute_api_key.encode(), body, hashlib.sha256).hexdigest()


def parse(body: bytes) -> dict:
    """The donation from a notification: payer, amount in the shop's currency, the event key; or reason it is skipped."""
    data = json.loads(body)
    if not isinstance(data, dict):
        raise ValueError("not an object")
    name = str(data.get("name") or "")
    p = data.get("payload") if isinstance(data.get("payload"), dict) else {}
    if name not in EVENTS:
        return {"skip": f"event {name or '—'}"}
    try:
        tg = int(p.get("telegram_user_id") or 0)
        minor = int(p.get("amount") or 0)
    except (TypeError, ValueError):
        return {"skip": "bad payer or amount"}
    currency = str(p.get("currency") or settings.default_currency).upper()
    if tg <= 0 or minor <= 0:
        return {"skip": "no payer or amount"}
    if currency != settings.default_currency.upper():
        return {"skip": f"currency {currency}"}
    key = f"{p.get('donation_request_id')}:{tg}:{minor}:{data.get('created_at') or p.get('created_at') or ''}"
    return {"telegram_id": tg, "amount": (Decimal(minor) / 100).quantize(Decimal("0.01")), "currency": currency, "event": key[:240]}


@router.get("/api/me/wallet/tribute")
async def my_tribute_link(request: Request, db: AsyncSession = Depends(get_db)):
    """The donation link for the wallet; the money comes to the Telegram account the customer pays from."""
    from . import main as shop
    user = await shop.user_from_token(request, db)
    if not configured():
        return {"enabled": False}
    return {"enabled": True, "url": settings.tribute_donate_link, "telegram_linked": bool(user.telegram_id),
            "currency": settings.default_currency}


@router.post("/api/webhooks/tribute")
async def tribute_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    from . import main as shop
    raw = await request.body()
    if len(raw) > 64 * 1024:
        raise HTTPException(413, "Payload too large")
    got = str(request.headers.get("trbt-signature") or "").strip().lower()
    if not configured() or not got or not hmac.compare_digest(signature(raw), got):
        raise HTTPException(403, "Invalid signature")
    try:
        d = parse(raw)
    except ValueError:
        raise HTTPException(400, "Invalid body")
    if "skip" in d:
        logger.info("Tribute: not credited (%s)", d["skip"])
        return {"status": "ignored", "reason": d["skip"]}
    user = (await db.execute(select(shop.User).where(shop.User.telegram_id == d["telegram_id"]))).scalar_one_or_none()
    if not user:
        logger.warning("Tribute: a donation from Telegram %s, no customer with this account — credit it by hand", d["telegram_id"])
        return {"status": "ignored", "reason": "unknown customer"}
    if not await shop.register_provider_event(db, "tribute", d["event"], None):
        await db.rollback()
        return {"status": "duplicate"}
    order_id = "tribute-" + hashlib.sha256(d["event"].encode()).hexdigest()[:32]
    row = shop.Payment(user_id=user.id, plan_id=0, provider="tribute", provider_payment_id=order_id, order_id=order_id, amount=d["amount"],
                       original_amount=d["amount"], discount_amount=Decimal("0.00"), currency=d["currency"], status="paid", paid_at=datetime.utcnow(),
                       fulfillment_status="pending", idempotency_key=order_id, purpose="topup", bonus_days=0)
    db.add(row)
    await db.commit()
    try:
        await shop.fulfill(row.id, db)
        async with AsyncSession(shop.engine, expire_on_commit=False) as edb:
            await shop.finish_provider_event(edb, "tribute", d["event"], ok=True)
            await edb.commit()
    except Exception as exc:
        async with AsyncSession(shop.engine, expire_on_commit=False) as edb:
            await shop.finish_provider_event(edb, "tribute", d["event"], ok=False, error=str(exc))
            await edb.commit()
        raise
    return {"status": "ok"}
