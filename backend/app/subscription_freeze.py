"""v28.50 «Заморозка подписки»: the customer pauses a paid subscription (holiday, a break) instead of cancelling it.

While frozen the panel user is switched off and the paid days are kept: the end date moves forward by the
frozen period at once (``expires_at`` += days, the panel's ``expireAt`` the same), so every expiry, renewal and
reminder job simply sees a later end. An early thaw takes back the unused frozen days. A purchase, a gift or bonus
days onto a frozen subscription thaw it first (``thaw``), so frozen days are never stacked with paid access.

Rules (``freeze.config``, off by default): days per freeze, total days and number of freezes in 365 days, only
paid subscriptions, at least N days left. Customers: cabinet, bot (/freeze), mobile API. Admin: «Тарифы →
Заморозка» and the mobile card; the operator can thaw any subscription.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import require_permission

logger = logging.getLogger("vpnshop.freeze")
router = APIRouter()
CONFIG_KEY = "freeze.config"
DEFAULT = {"enabled": False, "min_days": 3, "max_days": 30, "year_days": 30, "year_times": 2, "min_left_days": 1, "paid_only": True}


class FreezeConfigIn(BaseModel):
    enabled: bool = False
    min_days: int = Field(3, ge=1, le=90)
    max_days: int = Field(30, ge=1, le=180)
    year_days: int = Field(30, ge=1, le=365)
    year_times: int = Field(2, ge=1, le=24)
    min_left_days: int = Field(1, ge=0, le=30)
    paid_only: bool = True


class FreezeIn(BaseModel):
    days: int = Field(..., ge=1, le=180)
    subscription_id: int | None = None


class ThawIn(BaseModel):
    subscription_id: int | None = None


async def load(db: AsyncSession) -> dict:
    from .node_health import _load
    return {**DEFAULT, **(await _load(db, CONFIG_KEY, DEFAULT) or {})}


def _panel():
    from .remnawave import RemnawaveClient
    return RemnawaveClient()


def expiry_patch(until: datetime) -> dict:
    from .grace_access import panel_expiry_patch
    return panel_expiry_patch(until)


async def _current(db: AsyncSession, subscription_id: int):
    from .models import SubscriptionFreeze
    return await db.scalar(select(SubscriptionFreeze).where(SubscriptionFreeze.subscription_id == subscription_id,
                                                           SubscriptionFreeze.ended_at.is_(None)).order_by(SubscriptionFreeze.id.desc()).limit(1))


async def usage(db: AsyncSession, user_id: int, now: datetime | None = None) -> dict:
    """Days and freezes used in the last 365 days (an early thaw counts only the days really frozen)."""
    from .models import SubscriptionFreeze
    now = now or datetime.utcnow()
    rows = (await db.execute(select(SubscriptionFreeze).where(SubscriptionFreeze.user_id == user_id,
                                                              SubscriptionFreeze.started_at >= now - timedelta(days=365)))).scalars().all()
    days = 0
    for r in rows:
        end = r.ended_at or r.until
        days += max(1, -(-int((end - r.started_at).total_seconds()) // 86400))
    return {"times": len(rows), "days": days}


async def check(db: AsyncSession, user, sub, days: int, cfg: dict | None = None, now: datetime | None = None) -> str:
    """Why this subscription cannot be frozen for ``days`` (an empty string when it can)."""
    from .models import Payment
    from .subscriptions import is_family_subscription
    cfg = cfg or await load(db)
    now = now or datetime.utcnow()
    if not cfg["enabled"]:
        return "Заморозка подписки сейчас недоступна"
    if not sub:
        return "Подписка не найдена"
    if sub.lifecycle_status == "frozen":
        return "Подписка уже заморожена"
    if sub.lifecycle_status != "active" or sub.scheduled_cancel_at or not sub.expires_at:
        return "Заморозить можно только действующую подписку"
    if user.restricted_at:
        return "Аккаунт ограничен"
    if sub.expires_at - now < timedelta(days=int(cfg["min_left_days"])):
        return f"До конца подписки меньше {cfg['min_left_days']} дн. — заморозка не нужна"
    if await is_family_subscription(db, sub.id):
        return "Семейную подписку замораживает владелец семьи"
    if cfg["paid_only"] and not await db.scalar(select(Payment.id).where(Payment.subscription_id == sub.id, Payment.status.in_(("paid", "fulfilled"))).limit(1)):
        return "Заморозить можно только оплаченную подписку"
    if days < int(cfg["min_days"]) or days > int(cfg["max_days"]):
        return f"Срок заморозки — от {cfg['min_days']} до {cfg['max_days']} дней"
    used = await usage(db, user.id, now)
    if used["times"] >= int(cfg["year_times"]):
        return f"За год можно заморозить подписку не больше {cfg['year_times']} раз"
    if used["days"] + days > int(cfg["year_days"]):
        return f"Осталось дней заморозки в этом году: {max(0, int(cfg['year_days']) - used['days'])}"
    return ""


async def freeze(db: AsyncSession, user, sub, days: int, panel=None, actor: str = "customer") -> dict:
    from .activity_log import record
    from .models import SubscriptionFreeze
    reason = await check(db, user, sub, days)
    if reason:
        raise HTTPException(409, reason)
    now = datetime.utcnow()
    until = now + timedelta(days=days)
    new_expiry = sub.expires_at + timedelta(days=days)
    if sub.remnawave_uuid:
        panel = panel or _panel()
        # The end date first: should the switch-off fail, the customer keeps working with a later end (no loss).
        await panel.patch_user(sub.remnawave_uuid, expiry_patch(new_expiry))
        await panel.disable_user(sub.remnawave_uuid)
    db.add(SubscriptionFreeze(subscription_id=sub.id, user_id=user.id, started_at=now, until=until, days=days,
                              expires_before=sub.expires_at))
    sub.expires_at = new_expiry
    sub.lifecycle_status = "frozen"
    if sub.next_renewal_at:
        sub.next_renewal_at = sub.next_renewal_at + timedelta(days=days)
    record(db, user.id, actor, "subscription.frozen", {"subscription_id": sub.id, "days": days, "until": until.isoformat()})
    await db.commit()
    return {"ok": True, "until": until.isoformat(), "expires_at": new_expiry.isoformat()}


async def thaw(db: AsyncSession, sub, panel=None, actor: str = "customer", commit: bool = False) -> bool:
    """End the freeze now; unused frozen days are taken back from the end date. A no-op for a live subscription."""
    if not sub or sub.lifecycle_status != "frozen":
        return False
    from .activity_log import record
    now = datetime.utcnow()
    row = await _current(db, sub.id)
    unused = (row.until - now) if row and row.until > now else timedelta(0)
    new_expiry = (sub.expires_at or now) - unused
    if sub.remnawave_uuid:
        panel = panel or _panel()
        await panel.patch_user(sub.remnawave_uuid, expiry_patch(new_expiry))
        await panel.enable_user(sub.remnawave_uuid)
    sub.expires_at = new_expiry
    if sub.next_renewal_at and unused:
        sub.next_renewal_at = sub.next_renewal_at - unused
    sub.lifecycle_status = "active"
    if row:
        row.ended_at = now
    record(db, sub.user_id, actor, "subscription.thawed", {"subscription_id": sub.id, "unused_hours": int(unused.total_seconds() // 3600)})
    if commit:
        await db.commit()
    return True


async def thaw_due(db: AsyncSession, panel=None, notify=None) -> list[int]:
    """Planned ends of freezes: the subscription works again and the customer gets a message."""
    from .models import Subscription, SubscriptionFreeze, User
    now = datetime.utcnow()
    rows = (await db.execute(select(SubscriptionFreeze).where(SubscriptionFreeze.ended_at.is_(None), SubscriptionFreeze.until <= now).limit(100))).scalars().all()
    done = []
    for row in rows:
        sub = await db.get(Subscription, row.subscription_id)
        if not sub or sub.lifecycle_status != "frozen":
            row.ended_at = now
            continue
        try:
            await thaw(db, sub, panel, actor="system")
        except Exception as exc:  # noqa: BLE001 — the next pass retries
            logger.warning("thaw of subscription %s failed: %s", sub.id, exc)
            await db.rollback()
            continue
        await db.commit()
        done.append(sub.id)
        user = await db.get(User, sub.user_id)
        if user and user.telegram_id:
            if notify is None:
                from .main import notify_user_telegram as notify
            try:
                await notify(user.telegram_id, f"Заморозка закончилась — VPN снова работает. Подписка действует до {sub.expires_at:%d.%m.%Y}.")
            except Exception as exc:  # noqa: BLE001
                logger.debug("thaw notice for %s skipped: %s", user.id, exc)
    await db.commit()
    return done


async def status_for(db: AsyncSession, user, sub) -> dict:
    cfg = await load(db)
    used = await usage(db, user.id)
    row = await _current(db, sub.id) if sub else None
    return {"enabled": bool(cfg["enabled"]), "min_days": cfg["min_days"], "max_days": cfg["max_days"],
            "days_left": max(0, int(cfg["year_days"]) - used["days"]), "times_left": max(0, int(cfg["year_times"]) - used["times"]),
            "subscription_id": sub.id if sub else None,
            "frozen": {"since": row.started_at.isoformat(), "until": row.until.isoformat()} if row and sub.lifecycle_status == "frozen" else None,
            "reason": "" if not sub or sub.lifecycle_status == "frozen" else await check(db, user, sub, int(cfg["min_days"]), cfg)}


async def _target(db, user, subscription_id):
    from .subscriptions import owned
    return await owned(db, user.id, subscription_id, lock=True)


async def _loop():
    from .db import SessionLocal
    from .main import redis_client
    while True:
        await asyncio.sleep(300)
        try:
            if redis_client is not None and not await redis_client.set("lock:freeze", "1", nx=True, ex=280):
                continue
            async with SessionLocal() as db:
                await thaw_due(db)
        except Exception as exc:  # noqa: BLE001
            logger.warning("freeze pass failed: %s", exc)


def _start():
    from .main import _track_task
    _track_task(_loop())


router.add_event_handler("startup", _start)


@router.get("/api/me/freeze")
async def my_freeze(request: Request, subscription_id: int | None = None, db: AsyncSession = Depends(get_db)):
    from .main import user_from_token
    user = await user_from_token(request, db)
    return await status_for(db, user, await _target(db, user, subscription_id))


@router.post("/api/me/freeze")
async def freeze_mine(payload: FreezeIn, request: Request, db: AsyncSession = Depends(get_db)):
    from .main import user_from_token
    user = await user_from_token(request, db)
    return await freeze(db, user, await _target(db, user, payload.subscription_id), payload.days)


@router.post("/api/me/freeze/thaw")
async def thaw_mine(payload: ThawIn, request: Request, db: AsyncSession = Depends(get_db)):
    from .main import user_from_token
    user = await user_from_token(request, db)
    sub = await _target(db, user, payload.subscription_id)
    if not await thaw(db, sub, commit=True):
        raise HTTPException(409, "Подписка не заморожена")
    return {"ok": True, "expires_at": sub.expires_at.isoformat()}


@router.get("/api/admin/freeze")
async def admin_freeze(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("read"))):
    from .models import SubscriptionFreeze
    now = datetime.utcnow()
    current = (await db.execute(select(SubscriptionFreeze).where(SubscriptionFreeze.ended_at.is_(None)).order_by(SubscriptionFreeze.until).limit(100))).scalars().all()
    month = await db.scalar(select(func.count()).select_from(SubscriptionFreeze).where(SubscriptionFreeze.started_at >= now - timedelta(days=30)))
    return {"config": await load(db), "frozen_now": len(current), "started_30d": int(month or 0),
            "items": [{"subscription_id": r.subscription_id, "user_id": r.user_id, "since": r.started_at.isoformat(),
                       "until": r.until.isoformat(), "days": r.days} for r in current]}


@router.put("/api/admin/freeze")
async def admin_freeze_config(payload: FreezeConfigIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("manage_plans"))):
    from .main import audit
    from .node_health import _save
    if payload.min_days > payload.max_days:
        raise HTTPException(400, "Минимальный срок больше максимального")
    await _save(db, CONFIG_KEY, payload.model_dump())
    await audit(db, "freeze.config", admin.email, None, payload.model_dump())
    await db.commit()
    return await load(db)


@router.post("/api/admin/freeze/{subscription_id}/thaw")
async def admin_thaw(subscription_id: int, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("users.write"))):
    from .main import audit
    from .models import Subscription
    sub = await db.get(Subscription, subscription_id)
    if not await thaw(db, sub, actor=f"admin:{admin.email}"):
        raise HTTPException(404, "Подписка не заморожена")
    await audit(db, "freeze.thaw", admin.email, str(subscription_id))
    await db.commit()
    return {"ok": True}
