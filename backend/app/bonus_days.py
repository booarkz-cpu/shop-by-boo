"""«Приведи друга — получи дни»: the referrer gets free days when an invited friend pays for the first time.

Fulfillment of the friend's payment queues one job (unique job key per payment, in the same transaction).
The worker adds the days to the referrer's subscription on the Remnawave panel with the idempotent
extension (the target expiry is stored before the panel call, so a lost answer is never granted twice).
A referrer without a subscription gets a gift code for the same days instead.
Settings: «Рефералы → Бонус днями» (/api/admin/referrals/bonus).
"""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .models import AppSetting, GiftCode, Job, Payment, Plan, Subscription, User
from .security import require_permission

CONFIG_KEY = "referrals.bonus_days"
DEFAULT = {"enabled": True, "days": 10, "first_payment_only": True}
router = APIRouter()


class BonusIn(BaseModel):
    enabled: bool = True
    days: int = Field(default=10, ge=1, le=365)
    first_payment_only: bool = True


async def config(db: AsyncSession) -> dict:
    row = await db.get(AppSetting, CONFIG_KEY)
    try:
        value = json.loads(row.value) if row and row.value else {}
    except ValueError:
        value = {}
    return {**DEFAULT, **value} if isinstance(value, dict) else dict(DEFAULT)


async def queue_referral_bonus(db: AsyncSession, payment: Payment) -> bool:
    """Called by fulfillment, inside its transaction. True when a bonus job was queued."""
    cfg = await config(db)
    referrer = payment.referrer_id_snapshot
    if not cfg["enabled"] or not referrer or payment.purpose != "subscription" or referrer == payment.user_id:
        return False
    if cfg["first_payment_only"]:
        earlier = await db.scalar(select(func.count(Payment.id)).where(
            Payment.user_id == payment.user_id, Payment.id != payment.id, Payment.purpose == "subscription",
            Payment.status.in_(("paid", "fulfilled")), Payment.fulfillment_status == "completed"))
        if earlier:
            return False
    key = f"bonus_days:referral:{payment.id}"
    if await db.scalar(select(Job.id).where(Job.job_key == key)):
        return False
    db.add(Job(job_key=key, kind="bonus_days", status="queued", payload={"user_id": int(referrer), "days": int(cfg["days"]),
                                                                        "reason": "referral", "friend_id": payment.user_id}))
    return True


async def _marker(db: AsyncSession, key: str) -> tuple[AppSetting, dict]:
    row = await db.get(AppSetting, key)
    if row is None:
        row = AppSetting(key=key, value="{}")
        db.add(row)
    try:
        return row, json.loads(row.value or "{}")
    except ValueError:
        return row, {}


async def apply_bonus_days(db: AsyncSession, job_key: str, user_id: int, days: int, reason: str = "referral") -> dict:
    """Run by the worker for a «bonus_days» job. Safe to repeat: the stored target expiry decides."""
    from . import main
    from .remnawave import RemnawaveClient
    row, state = await _marker(db, job_key)
    if state.get("status") == "completed":
        return state
    user_lock, user_token = await main._acquire_user_fulfillment_lock(user_id, ttl=600)
    try:
        user = await db.scalar(select(User).where(User.id == user_id).execution_options(populate_existing=True).with_for_update())
        if user is None or user.deleted_at is not None:
            state = {"status": "completed", "skipped": "account_unavailable"}
            row.value = json.dumps(state)
            await db.commit()
            return state
        sub = await db.scalar(select(Subscription).where(Subscription.user_id == user_id, Subscription.is_primary.is_(True))
                              .execution_options(populate_existing=True).with_for_update())
        now = datetime.utcnow()
        if sub is None or not sub.remnawave_uuid:
            plan = await db.scalar(select(Plan).where(Plan.enabled.is_(True)).order_by(Plan.price, Plan.id).limit(1))
            if plan is None:
                raise RuntimeError("No enabled plan for a bonus gift")
            code = "REF-" + secrets.token_hex(4).upper()
            db.add(GiftCode(code=code, plan_id=plan.id, duration_days=days, max_uses=1, enabled=True,
                            expires_at=now + timedelta(days=180)))
            state = {"status": "completed", "gift_code": code, "days": days}
            row.value = json.dumps(state)
            await main.enqueue_notification(db, user_id=user_id, channel="in_app", kind="referral_bonus",
                                            title=f"+{days} дней за друга",
                                            body=f"Друг оплатил подписку. Ваш подарок — код {code} на {days} дней: «Подарки → Активировать».",
                                            dedupe_key=job_key)
            await db.commit()
            return state
        rw = RemnawaveClient()
        if state.get("expected_after") is None:
            remote = await rw.get_expiry(sub.remnawave_uuid)
            before = max(sub.expires_at or now, remote or now, now)
            state = {"status": "processing", "expected_before": before.isoformat(), "expected_after": (before + timedelta(days=days)).isoformat()}
            row.value = json.dumps(state)
            await db.commit()  # the target is fixed before the panel is touched
        before, after = datetime.fromisoformat(state["expected_before"]), datetime.fromisoformat(state["expected_after"])
        remote_user = await rw.get_user(sub.remnawave_uuid)
        if str((remote_user or {}).get("status") or "").lower() in {"disabled", "blocked", "inactive", "expired"}:
            await rw.enable_user(sub.remnawave_uuid)
        extension = await rw.extend_idempotent(sub.remnawave_uuid, days, before, after)
        verified = extension.get("expires_at") if isinstance(extension, dict) else None
        sub.expires_at = max(after, verified or after)
        sub.lifecycle_status = "active"
        sub.grace_until = None
        state = {**state, "status": "completed", "expires_at": sub.expires_at.isoformat()}
        row.value = json.dumps(state)
        await main.audit(db, f"bonus_days.{reason}", "system", str(user_id), {"days": days, "job": job_key})
        await main.enqueue_notification(db, user_id=user_id, channel="in_app", kind="referral_bonus", title=f"+{days} дней за друга",
                                        body=f"Друг оплатил подписку: ваша подписка продлена на {days} дней.", dedupe_key=job_key)
        await db.commit()
        return state
    finally:
        await main._release_payment_side_effect_lock(user_lock, user_token)


@router.get("/api/admin/referrals/bonus")
async def get_bonus(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("referrals.read"))):
    granted = await db.scalar(select(func.count(Job.id)).where(Job.kind == "bonus_days", Job.status == "completed"))
    return {**await config(db), "granted": int(granted or 0)}


@router.put("/api/admin/referrals/bonus")
async def set_bonus(payload: BonusIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("referrals.reconcile"))):
    from .main import audit
    row = await db.get(AppSetting, CONFIG_KEY)
    value = json.dumps(payload.model_dump())
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=CONFIG_KEY, value=value))
    await audit(db, "referral.bonus_days.updated", admin.email, None, payload.model_dump())
    await db.commit()
    return payload.model_dump()
