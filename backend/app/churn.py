"""Churn forecast: which paying customers are likely to leave, why, and a personal offer before they do.

A rule-based score 0–100 for every customer with a live paid subscription (no black box — every point has a reason):

* the subscription ends within 7 days and auto-renewal is off (+30), within 3 days (+15 more);
* no sign of use: no activity, connection report or sign-in for 14 days (+20);
* a failed auto-renewal or an abandoned checkout in 14 days (+15);
* a support ticket in 14 days (+10) — and +10 more if it is still open;
* only one payment ever (a first-time buyer leaves more often) (+10).

«Аналитика → Риск оттока» lists customers above the threshold with reasons; «Отправить предложение» gives each a
personal one-time promo code (percent off, valid 7 days) in Telegram and in-app. With «автоматически» it runs once a
day for new risky customers (one offer per customer per 30 days). Mobile admin card too.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import require_permission

logger = logging.getLogger("vpnshop.churn")
router = APIRouter()
KEY = "churn.config"
OFFERS_KEY = "churn.offers"
DEFAULT = {"threshold": 50, "percent": 15, "auto": False}


class ChurnIn(BaseModel):
    threshold: int = Field(50, ge=10, le=100)
    percent: int = Field(15, ge=1, le=90)
    auto: bool = False


async def _load(db, key, default):
    from .node_health import _load as load
    return await load(db, key, default)


async def score_all(db: AsyncSession, now: datetime | None = None) -> list[dict]:
    from .models import ConnectionReport, Payment, Subscription, SupportTicket, User, UserActivity, UserSession
    now = now or datetime.utcnow()
    since = now - timedelta(days=14)
    subs = (await db.execute(select(Subscription).where(Subscription.lifecycle_status.in_(("active", "cancel_scheduled", "grace")),
                                                        Subscription.expires_at > now))).scalars().all()
    out = []
    for sub in subs:
        user = await db.get(User, sub.user_id)
        if not user or user.deleted_at or user.restricted_at:
            continue
        paid = int(await db.scalar(select(func.count()).select_from(Payment).where(
            Payment.user_id == user.id, Payment.status.in_(("paid", "fulfilled")), Payment.provider != "reseller")) or 0)
        if not paid:
            continue  # trials and gifts are not «paying customers»
        score, reasons = 0, []
        left = (sub.expires_at - now).days
        if left <= 7 and (not user.auto_renew_enabled or sub.scheduled_cancel_at):
            score += 30
            reasons.append(f"подписка кончается через {left} дн., автопродление выключено")
            if left <= 3:
                score += 15
        seen = await db.scalar(select(func.max(UserActivity.created_at)).where(UserActivity.user_id == user.id))
        used = await db.scalar(select(func.max(ConnectionReport.created_at)).where(ConnectionReport.user_id == user.id))
        signed = await db.scalar(select(func.max(UserSession.created_at)).where(UserSession.user_id == user.id))
        last = max([x for x in (seen, used, signed) if x] or [datetime.min])
        if last < since:
            score += 20
            reasons.append("не заходил и не подключался 14 дней")
        failed = await db.scalar(select(func.count()).select_from(Payment).where(
            Payment.user_id == user.id, Payment.created_at >= since, Payment.status.in_(("failed", "canceled", "cancelled", "creation_unknown", "pending"))))
        if failed:
            score += 15
            reasons.append("неудачная или брошенная оплата")
        tickets = (await db.execute(select(SupportTicket.status).where(SupportTicket.user_id == user.id, SupportTicket.created_at >= since))).scalars().all()
        if tickets:
            score += 10
            reasons.append("обращался в поддержку")
            if any(t not in ("resolved", "closed") for t in tickets):
                score += 10
                reasons.append("обращение ещё открыто")
        if paid == 1:
            score += 10
            reasons.append("одна оплата за всё время")
        out.append({"user_id": user.id, "name": user.username or user.email or f"№{user.id}", "score": min(score, 100),
                    "reasons": reasons, "expires_at": sub.expires_at.isoformat(), "auto_renew": bool(user.auto_renew_enabled)})
    return sorted(out, key=lambda r: -r["score"])


async def send_offer(db: AsyncSession, user_id: int, percent: int, now: datetime | None = None) -> str | None:
    """A personal one-time promo code (7 days) to one customer; at most one per 30 days."""
    from .main import notify_user_telegram
    from .models import Notification, PromoCode, User
    from .node_health import _save
    from .promo_generator import make_code
    now = now or datetime.utcnow()
    offers = await _load(db, OFFERS_KEY, {})
    last = offers.get(str(user_id))
    if last and now - datetime.fromisoformat(last) < timedelta(days=30):
        return None
    user = await db.get(User, user_id)
    if not user:
        return None
    code = make_code("STAY", 8)
    db.add(PromoCode(code=code, kind="percent", value=Decimal(percent), usage_limit=1, max_uses_per_user=1,
                     ends_at=now + timedelta(days=7), enabled=True))
    text = f"Мы ценим, что вы с нами! Персональная скидка {percent}% на продление — промокод {code}, действует 7 дней."
    db.add(Notification(user_id=user_id, channel="in_app", kind="promo.personal", title="Персональная скидка", body=text,
                        status="sent", sent_at=now, dedupe_key=f"churn:{user_id}:{now.date()}"))
    offers[str(user_id)] = now.isoformat()
    await _save(db, OFFERS_KEY, offers)
    from .activity_log import record
    record(db, user_id, "system", "churn.offer", {"code": code, "percent": percent})
    await db.commit()
    await notify_user_telegram(user.telegram_id, text)
    return code


async def auto_pass(db: AsyncSession, now: datetime | None = None) -> int:
    config = await _load(db, KEY, DEFAULT)
    if not config["auto"]:
        return 0
    sent = 0
    for row in await score_all(db, now):
        if row["score"] < config["threshold"]:
            break
        if await send_offer(db, row["user_id"], int(config["percent"]), now):
            sent += 1
    return sent


async def _loop():
    from .db import SessionLocal
    from .main import redis_client
    while True:
        await asyncio.sleep(3600)
        try:
            if datetime.utcnow().hour != 9:  # once a day, 12:00 Moscow
                continue
            if redis_client is not None and not await redis_client.set("lock:churn", "1", nx=True, ex=3500):
                continue
            async with SessionLocal() as db:
                await auto_pass(db)
        except Exception as exc:  # noqa: BLE001
            logger.warning("churn pass failed: %s", exc)


def _start():
    from .main import _track_task
    _track_task(_loop())


router.add_event_handler("startup", _start)


@router.get("/api/admin/churn")
async def churn(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("analytics.read"))):
    config = await _load(db, KEY, DEFAULT)
    rows = await score_all(db)
    return {"config": config, "at_risk": [r for r in rows if r["score"] >= config["threshold"]][:200], "scored": len(rows)}


@router.put("/api/admin/churn")
async def put_churn(payload: ChurnIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("manage_marketing"))):
    from .main import audit
    from .node_health import _save
    await _save(db, KEY, payload.model_dump())
    await audit(db, "churn.config", admin.email, None, payload.model_dump())
    await db.commit()
    return {"ok": True}


@router.post("/api/admin/churn/{user_id}/offer")
async def offer(user_id: int, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("manage_marketing"))):
    from fastapi import HTTPException
    config = await _load(db, KEY, DEFAULT)
    code = await send_offer(db, user_id, int(config["percent"]))
    if not code:
        raise HTTPException(409, "Клиенту уже отправляли предложение за последние 30 дней")
    return {"code": code}
