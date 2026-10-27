"""Anti-sharing: a subscription used on more devices than its plan allows.

Every 15 minutes one worker reads the devices (HWID) Remnawave has seen for each live subscription and compares
them with the device limit the customer bought (``device_limit_snapshot``). Over the limit:
* ``reset``  — the panel forgets all devices; the customer reconnects only their own (and is told so);
* ``block``  — the config is switched off: the customer is restricted (platform_api.suspend_access) until the
  operator lifts it in «Платформа → Нарушения»; a violation with the device list is opened there.
The panel also enforces ``hwidDeviceLimit`` on new connections when its HWID limit is on; this pass catches
devices added before the limit or while it was off. «Защита → Анти-шеринг» (/api/admin/anti-sharing).
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .models import AbuseViolation, AppSetting, Plan, Subscription, User
from .security import require_permission

logger = logging.getLogger("vpnshop.anti_sharing")
CONFIG_KEY = "anti_sharing"
DEFAULT = {"enabled": False, "action": "reset", "tolerance": 0}
router = APIRouter()


class AntiSharingIn(BaseModel):
    enabled: bool = False
    action: str = Field(default="reset", pattern="^(reset|block)$")
    tolerance: int = Field(default=0, ge=0, le=5)


async def config(db: AsyncSession) -> dict:
    row = await db.get(AppSetting, CONFIG_KEY)
    try:
        value = json.loads(row.value) if row and row.value else {}
    except ValueError:
        value = {}
    return {**DEFAULT, **value} if isinstance(value, dict) else dict(DEFAULT)


async def _limit(db: AsyncSession, sub: Subscription) -> int | None:
    if sub.device_limit_snapshot:
        return int(sub.device_limit_snapshot)
    plan = await db.get(Plan, sub.plan_id) if sub.plan_id else None
    return int(plan.device_limit) if plan and plan.device_limit else None


async def check_pass(db: AsyncSession, *, panel=None, notify=None, limit: int = 300) -> dict:
    from .main import RemnawaveClient, audit, enqueue_notification
    from .platform_api import suspend_access
    cfg = await config(db)
    done = {"checked": 0, "over": [], "action": cfg["action"]}
    if not cfg["enabled"]:
        return done
    panel = panel or RemnawaveClient()
    now = datetime.utcnow()
    subs = (await db.execute(select(Subscription).where(Subscription.remnawave_uuid.is_not(None), Subscription.expires_at > now,
                                                        Subscription.lifecycle_status.in_(("active", "grace", "cancel_scheduled")))
                             .order_by(Subscription.id).limit(limit))).scalars().all()
    for sub in subs:
        allowed = await _limit(db, sub)
        if not allowed:
            continue
        try:
            devices = await panel.hwid_devices(sub.remnawave_uuid)
        except Exception as exc:  # noqa: BLE001 — a panel without HWID support is not a violation
            logger.debug("HWID list unavailable for %s: %s", sub.id, exc)
            continue
        done["checked"] += 1
        if len(devices) <= allowed + int(cfg["tolerance"]):
            continue
        user = await db.get(User, sub.user_id)
        if user is None or user.deleted_at is not None or user.restricted_at is not None:
            continue
        names = [str(d.get("deviceModel") or d.get("platform") or d.get("hwid") or "?")[:60] for d in devices][:20]
        summary = f"Подписка №{sub.id}: {len(devices)} устройств при лимите {allowed}"
        db.add(AbuseViolation(user_id=user.id, score=90 if cfg["action"] == "block" else 50,
                              recommendation="block" if cfg["action"] == "block" else "warn",
                              analyzers={"hits": [{"name": "devices", "detail": summary}], "devices": names}, summary=summary, status="open"))
        if cfg["action"] == "block":
            await suspend_access(db, user)
            text = (f"Подписка отключена: она используется на {len(devices)} устройствах, а тариф разрешает {allowed}. "
                    "Напишите в поддержку, чтобы восстановить доступ.")
        else:
            await panel.reset_hwid_devices(sub.remnawave_uuid)
            text = (f"Подписка использовалась на {len(devices)} устройствах при лимите {allowed}. Список устройств сброшен: "
                    "подключите заново только свои устройства.")
        await enqueue_notification(db, user_id=user.id, channel="in_app", kind="device_limit", title="Превышен лимит устройств",
                                   body=text, dedupe_key=f"anti_sharing:{sub.id}:{now:%Y%m%d%H}")
        await audit(db, f"anti_sharing.{cfg['action']}", "system", str(sub.id), {"devices": len(devices), "limit": allowed})
        await db.commit()
        if notify:
            await notify(user, text)
        done["over"].append(sub.id)
    return done


async def anti_sharing_scheduler():
    from . import main
    from .db import SessionLocal
    while True:
        try:
            lock = await main.redis_client.set("lock:anti-sharing", "1", nx=True, ex=840) if main.redis_client else True
            if lock:
                async with SessionLocal() as db:
                    await check_pass(db, notify=lambda user, text: main.notify_user_telegram(user.telegram_id, text))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Anti-sharing pass failed: %s", exc)
        await asyncio.sleep(900)


@router.get("/api/admin/anti-sharing")
async def get_anti_sharing(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("security.manage"))):
    recent = (await db.execute(select(AbuseViolation).where(AbuseViolation.summary.like("Подписка №%"))
                               .order_by(AbuseViolation.id.desc()).limit(30))).scalars().all()
    return {**await config(db), "recent": [{"id": v.id, "user_id": v.user_id, "summary": v.summary, "status": v.status,
                                            "created_at": v.created_at} for v in recent]}


@router.put("/api/admin/anti-sharing")
async def put_anti_sharing(payload: AntiSharingIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("security.manage"))):
    from .main import audit
    row = await db.get(AppSetting, CONFIG_KEY)
    value = json.dumps(payload.model_dump())
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=CONFIG_KEY, value=value))
    await audit(db, "anti_sharing.config", admin.email, None, payload.model_dump())
    await db.commit()
    return payload.model_dump()
