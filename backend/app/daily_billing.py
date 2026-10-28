"""Daily plans: a plan of 1 day renews itself every day from the wallet («суточная подписка»).

Turned on in «Тарифы → Суточные тарифы»; applies to enabled plans with ``duration_days = 1`` for customers with
auto-renewal on. Every 15 minutes subscriptions on such a plan that end within the next hour are bought again from the
wallet (the same wallet purchase as a manual one: checks, ledger, one charge per day — the idempotency key is the
subscription and the date). Not enough money → one message a day «пополните баланс», and the subscription ends as
usual (with grace access if that is on).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import require_permission

logger = logging.getLogger("vpnshop.daily")
router = APIRouter()
KEY = "daily_billing.enabled"
NOTICE_KEY = "daily_billing.notified"


async def enabled(db: AsyncSession) -> bool:
    from .backups_api import setting_value
    return await setting_value(db, KEY, "0") == "1"


async def tick(db: AsyncSession, now: datetime | None = None, notify=None) -> dict:
    from .customer_api import spend_from_wallet
    from .models import Plan, Subscription, User
    from .node_health import _load, _save
    if not await enabled(db):
        return {"renewed": [], "short": []}
    now = now or datetime.utcnow()
    if notify is None:
        from .main import notify_user_telegram as notify
    daily = {p.id: p for p in (await db.execute(select(Plan).where(Plan.duration_days == 1, Plan.enabled.is_(True)))).scalars()}
    if not daily:
        return {"renewed": [], "short": []}
    subs = (await db.execute(select(Subscription).where(
        Subscription.plan_id.in_(list(daily)), Subscription.lifecycle_status.in_(("active", "grace")),
        Subscription.scheduled_cancel_at.is_(None), Subscription.expires_at <= now + timedelta(hours=1),
        Subscription.expires_at > now - timedelta(hours=24)))).scalars().all()
    notified = await _load(db, NOTICE_KEY, {})
    renewed, short = [], []
    for sub in subs:
        user = await db.get(User, sub.user_id)
        if not user or not user.auto_renew_enabled or user.restricted_at or user.deleted_at:
            continue
        plan = daily[sub.plan_id]
        day = sub.expires_at.date().isoformat()
        if Decimal(str(user.wallet_balance or 0)) < Decimal(str(plan.price)):
            if notified.get(str(sub.id)) != day:
                notified[str(sub.id)] = day
                short.append(sub.id)
                await notify(user.telegram_id, f"Суточная подписка: на балансе меньше {plan.price} ₽ — пополните, чтобы VPN не прервался. "
                                               "Daily plan: top up your balance to stay connected.")
            continue
        try:
            await spend_from_wallet(db, user, {"plan_id": plan.id, "subscription_id": sub.id}, f"daily-{sub.id}-{day}")
            renewed.append(sub.id)
        except HTTPException as exc:
            logger.info("daily renewal of %s skipped: %s", sub.id, exc.detail)
    await _save(db, NOTICE_KEY, {k: v for k, v in notified.items() if v >= (now - timedelta(days=3)).date().isoformat()})
    await db.commit()
    return {"renewed": renewed, "short": short}


async def _loop():
    from .db import SessionLocal
    from .main import redis_client
    while True:
        await asyncio.sleep(900)
        try:
            if redis_client is not None and not await redis_client.set("lock:daily-billing", "1", nx=True, ex=850):
                continue
            async with SessionLocal() as db:
                await tick(db)
        except Exception as exc:  # noqa: BLE001
            logger.warning("daily billing pass failed: %s", exc)


def _start():
    from .main import _track_task
    _track_task(_loop())


router.add_event_handler("startup", _start)


@router.get("/api/admin/daily-billing")
async def get_daily(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("read"))):
    from .models import Plan
    plans = (await db.execute(select(Plan).where(Plan.duration_days == 1))).scalars().all()
    return {"enabled": await enabled(db), "plans": [{"id": p.id, "name": p.name, "price": str(p.price), "enabled": p.enabled} for p in plans]}


@router.put("/api/admin/daily-billing")
async def put_daily(payload: dict, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("manage_plans"))):
    from .backups_api import set_setting
    from .main import audit
    await set_setting(db, KEY, "1" if payload.get("enabled") else "0")
    await audit(db, "daily_billing", admin.email, None, {"enabled": bool(payload.get("enabled"))})
    await db.commit()
    return {"enabled": bool(payload.get("enabled"))}
