"""Home-screen widget summary for the Corgi mobile apps.

The widget is visible without unlocking the app, so the payload is deliberately small:
subscription state, expiry, remaining traffic and the unread-notification count. It never
contains the subscription link, balances, email or payment data. Remnawave traffic is
cached per subscription so a periodic widget refresh cannot hammer the panel.
"""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .models import Notification, Plan, Subscription

logger = logging.getLogger("vpnshop.widget")
router = APIRouter()

TRAFFIC_CACHE_SECONDS = 600
REFRESH_AFTER_SECONDS = 1800
EXPIRING_DAYS = 3


def days_left(expires_at: datetime | None, now: datetime) -> int | None:
    if expires_at is None:
        return None
    return math.ceil((expires_at - now).total_seconds() / 86400)


def state_of(sub: Subscription | None, now: datetime) -> str:
    left = days_left(sub.expires_at if sub else None, now)
    if sub is None or left is None:
        return "none"
    if left <= 0:
        return "expired"
    if sub.lifecycle_status == "cancel_scheduled":
        return "cancel_scheduled"
    if left <= EXPIRING_DAYS:
        return "expiring"
    return "active"


async def _traffic(sub: Subscription) -> tuple[bool, int | None, int | None]:
    """Returns (available, used_bytes, limit_bytes) with a short shared cache."""
    from . import main

    fallback_limit = int(sub.traffic_limit_gb_snapshot) * 1024**3 if sub.traffic_limit_gb_snapshot else None
    if not sub.remnawave_uuid:
        return False, None, fallback_limit
    key = f"widget:traffic:{sub.id}"
    redis = main.redis_client
    if redis is not None:
        try:
            cached = await redis.get(key)
            if cached:
                data = json.loads(cached)
                return bool(data["available"]), data["used"], data["limit"]
        except Exception as exc:
            logger.warning("Widget traffic cache unavailable: %s", type(exc).__name__)
    try:
        remote = await main.RemnawaveClient().get_user(sub.remnawave_uuid)
        used = remote.get("trafficUsedBytes") or remote.get("usedTrafficBytes")
        remote_limit = remote.get("trafficLimitBytes")
        result = (True, int(used) if used is not None else 0, int(remote_limit) if remote_limit else fallback_limit)
    except Exception:
        # Do not cache a failure: the next refresh retries the panel.
        return False, None, fallback_limit
    if redis is not None:
        try:
            await redis.set(key, json.dumps({"available": result[0], "used": result[1], "limit": result[2]}), ex=TRAFFIC_CACHE_SECONDS)
        except Exception as exc:
            logger.warning("Widget traffic cache unavailable: %s", type(exc).__name__)
    return result


@router.get("/api/me/widget")
async def widget_summary(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    from .main import user_from_token

    response.headers["Cache-Control"] = "private, no-store"
    user = await user_from_token(request, db)
    now = datetime.utcnow()
    sub = await db.scalar(select(Subscription).where(Subscription.user_id == user.id, Subscription.is_primary.is_(True)))
    unread = await db.scalar(select(func.count(Notification.id)).where(Notification.user_id == user.id, Notification.read_at.is_(None))) or 0
    summary = None
    if sub is not None:
        plan = await db.get(Plan, sub.plan_id) if sub.plan_id else None
        available, used, limit = await _traffic(sub)
        summary = {
            "name": (sub.name or "")[:64] or None,
            "plan": (plan.name if plan else "")[:64] or None,
            "state": state_of(sub, now),
            "expires_at": sub.expires_at.isoformat() + "Z" if sub.expires_at else None,
            "days_left": days_left(sub.expires_at, now),
            "traffic_available": available,
            "traffic_used_bytes": used,
            "traffic_limit_bytes": limit,
            "traffic_left_bytes": max(0, limit - used) if (limit and used is not None) else None,
        }
    return {
        "subscription": summary,
        "unread_notifications": int(unread),
        "generated_at": now.isoformat() + "Z",
        "refresh_after_seconds": REFRESH_AFTER_SECONDS,
    }
