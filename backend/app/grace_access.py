"""Grace access: when a subscription ends, VPN keeps working a few more hours so the customer can renew calmly.

Every 5 minutes subscriptions that end within 15 minutes get ``grace_until`` = end + ``hours`` (lifecycle «grace»),
the panel user's ``expireAt`` is moved to the same moment and the customer gets a message with a renewal link. The
lifecycle scheduler switches the user off only after the grace ends; a renewal clears it. A customer gets grace at
most once per ``cooldown_days`` (no endless free hours). Off by default; «Тарифы → Льготный доступ» and the mobile card. The same card holds «Сбрасывать трафик при оплате»
(a renewal starts the traffic limit from zero; off by default).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import require_permission

logger = logging.getLogger("vpnshop.grace")
router = APIRouter()
CONFIG_KEY = "grace.config"
HISTORY_KEY = "grace.history"
DEFAULT = {"enabled": False, "hours": 24, "cooldown_days": 30}


RESET_KEY = "fulfillment.reset_traffic"


async def reset_traffic_on_payment(db: AsyncSession) -> bool:
    """«Сбрасывать израсходованный трафик при оплате» (off by default: a renewal keeps the traffic used so far)."""
    from .backups_api import setting_value
    return await setting_value(db, RESET_KEY, "0") == "1"


class GraceIn(BaseModel):
    enabled: bool
    reset_traffic_on_payment: bool = False
    hours: int = Field(24, ge=1, le=168)
    cooldown_days: int = Field(30, ge=0, le=365)


async def _load(db, key, default):
    from .node_health import _load as load
    return await load(db, key, default)


async def _save(db, key, value):
    from .node_health import _save as save
    await save(db, key, value)


def panel_expiry_patch(until: datetime) -> dict:
    """Body for ``RemnawaveClient.patch_user`` (which adds the user id): checked against a live panel in CI."""
    return {"expireAt": until.isoformat(timespec="seconds") + ".000Z"}


async def tick(db: AsyncSession, now: datetime | None = None, panel=None, notify=None) -> list[int]:
    from .models import Subscription, User
    config = await _load(db, CONFIG_KEY, DEFAULT)
    if not config["enabled"]:
        return []
    now = now or datetime.utcnow()
    history = await _load(db, HISTORY_KEY, {})
    rows = (await db.execute(select(Subscription).where(
        Subscription.lifecycle_status == "active", Subscription.grace_until.is_(None), Subscription.scheduled_cancel_at.is_(None),
        Subscription.expires_at > now - timedelta(minutes=15), Subscription.expires_at <= now + timedelta(minutes=15)).limit(200))).scalars().all()
    if panel is None:
        from .remnawave import RemnawaveClient
        panel = RemnawaveClient()
    if notify is None:
        from .main import notify_user_telegram as notify
    granted = []
    for sub in rows:
        user = await db.get(User, sub.user_id)
        if not user or user.restricted_at or user.deleted_at:
            continue
        last = history.get(str(user.id))
        if last and now - datetime.fromisoformat(last) < timedelta(days=int(config["cooldown_days"])):
            continue
        until = sub.expires_at + timedelta(hours=int(config["hours"]))
        if sub.remnawave_uuid:
            try:
                await panel.patch_user(sub.remnawave_uuid, panel_expiry_patch(until))
            except Exception as exc:  # noqa: BLE001 — no grace this time; the subscription simply ends
                logger.warning("grace for subscription %s failed: %s", sub.id, exc)
                continue
        sub.grace_until = until
        sub.lifecycle_status = "grace"
        history[str(user.id)] = now.isoformat()
        from .activity_log import record
        record(db, user.id, "system", "subscription.grace", {"until": until.isoformat()})
        granted.append(sub.id)
        await notify(user.telegram_id, f"Подписка закончилась, но VPN поработает ещё {config['hours']} ч — продлите в боте или кабинете, "
                                       "чтобы не прерываться. Your subscription ended; VPN keeps working a little longer — renew to stay connected.")
    if granted:
        await _save(db, HISTORY_KEY, {k: v for k, v in history.items() if now - datetime.fromisoformat(v) < timedelta(days=366)})
    await db.commit()
    return granted


async def _loop():
    from .db import SessionLocal
    from .main import redis_client
    while True:
        await asyncio.sleep(300)
        try:
            if redis_client is not None and not await redis_client.set("lock:grace", "1", nx=True, ex=280):
                continue
            async with SessionLocal() as db:
                await tick(db)
        except Exception as exc:  # noqa: BLE001
            logger.warning("grace pass failed: %s", exc)


def _start():
    from .main import _track_task
    _track_task(_loop())


router.add_event_handler("startup", _start)


@router.get("/api/admin/grace")
async def get_grace(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("read"))):
    from sqlalchemy import func

    from .models import Subscription
    active = await db.scalar(select(func.count()).select_from(Subscription).where(Subscription.lifecycle_status == "grace"))
    return {"config": {**await _load(db, CONFIG_KEY, DEFAULT), "reset_traffic_on_payment": await reset_traffic_on_payment(db)},
            "in_grace": int(active or 0)}


@router.put("/api/admin/grace")
async def put_grace(payload: GraceIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("manage_plans"))):
    from .main import audit
    from .backups_api import set_setting
    await _save(db, CONFIG_KEY, payload.model_dump(exclude={"reset_traffic_on_payment"}))
    await set_setting(db, RESET_KEY, "1" if payload.reset_traffic_on_payment else "0")
    await audit(db, "grace.config", admin.email, None, payload.model_dump())
    await db.commit()
    return {"ok": True}
