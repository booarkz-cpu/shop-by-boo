"""«Срок — с первого подключения»: the subscription term starts when the customer first connects, not at payment.

For plans marked in «Тарифы → Срок с первого подключения», a new subscription is created active at once with
expiry = payment + wait + term, where wait = min(term, ``max_wait_days``, 30 by default). When the panel reports
``user.first_connected`` (Remnawave webhook) the unused part of the wait is taken off: expiry = expiry − (deadline −
now), in the panel (``expireAt``) and in the shop. Renewals during the wait are kept (they were added on top). If
the customer never connects, the term starts by itself at the deadline — the preset expiry already says so.
Only for brand-new subscriptions (a renewal of a used subscription never waits). Off by default.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import require_permission

logger = logging.getLogger("vpnshop.first_connect")
router = APIRouter()
CONFIG_KEY = "first_connect.config"
DEFAULT = {"enabled": False, "plans": [], "max_wait_days": 30}


async def _config(db: AsyncSession) -> dict:
    from .node_health import _load
    return await _load(db, CONFIG_KEY, DEFAULT)


async def wait_days(db: AsyncSession, plan_id: int, duration_days: int) -> int:
    cfg = await _config(db)
    if not cfg.get("enabled") or int(plan_id) not in {int(x) for x in cfg.get("plans") or []}:
        return 0
    return max(0, min(int(duration_days), int(cfg.get("max_wait_days") or 30), 30))


async def start_waiting(db: AsyncSession, sub, days: int, deadline: datetime) -> None:
    from .models import FirstConnectWait
    row = (await db.execute(select(FirstConnectWait).where(FirstConnectWait.subscription_id == sub.id))).scalar_one_or_none()
    if row is None:
        db.add(FirstConnectWait(subscription_id=sub.id, days=days, deadline=deadline))


async def on_first_connect(db: AsyncSession, sub, now: datetime | None = None) -> bool:
    """Take the unused wait off the expiry; True when the term started now."""
    from .models import FirstConnectWait
    from .grace_access import panel_expiry_patch
    from .remnawave import RemnawaveClient
    now = now or datetime.utcnow()
    row = (await db.execute(select(FirstConnectWait).where(FirstConnectWait.subscription_id == sub.id))).scalar_one_or_none()
    if row is None or row.started_at is not None or now >= row.deadline or not sub.expires_at:
        return False
    new_expiry = sub.expires_at - (row.deadline - now)
    if sub.remnawave_uuid:
        await RemnawaveClient().patch_user(sub.remnawave_uuid, panel_expiry_patch(new_expiry.replace(microsecond=0)))
    sub.expires_at = new_expiry
    row.started_at = now
    await db.commit()
    logger.info("Subscription %s: term started at the first connection", sub.id)
    return True


class FirstConnectIn(BaseModel):
    enabled: bool = False
    plans: list[int] = Field(default_factory=list, max_length=200)
    max_wait_days: int = Field(30, ge=1, le=30)


@router.get("/api/admin/first-connect")
async def get_cfg(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("manage_plans"))):
    from .models import FirstConnectWait
    waiting = (await db.execute(select(FirstConnectWait).where(FirstConnectWait.started_at.is_(None),
                                                                FirstConnectWait.deadline > datetime.utcnow())
                                .order_by(FirstConnectWait.deadline).limit(200))).scalars().all()
    started = (await db.execute(select(FirstConnectWait).where(FirstConnectWait.started_at.is_not(None),
                                                                FirstConnectWait.started_at > datetime.utcnow() - timedelta(days=30)))).scalars().all()
    return {"config": await _config(db), "waiting": [{"subscription_id": w.subscription_id, "days": w.days,
                                                       "deadline": w.deadline.isoformat(timespec="minutes")} for w in waiting],
            "started_30d": len(started)}


@router.put("/api/admin/first-connect")
async def put_cfg(payload: FirstConnectIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("manage_plans"))):
    from .node_health import _save
    await _save(db, CONFIG_KEY, payload.model_dump())
    await db.commit()
    return {"ok": True}
