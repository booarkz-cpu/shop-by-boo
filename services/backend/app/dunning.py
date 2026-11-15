"""v28.50 «Повторные попытки автопродления» (dunning): what happens after a saved card is declined.

Without this module a declined renewal is retried after 2, 4 … 72 hours, the subscription gets 72 hours of grace
and the third decline switches auto-renew off — silently. With ``dunning.config`` enabled (off by default):

* retries follow the owner's schedule (``retry_hours``, default after 1, 3 and 5 days) up to ``max_failures``;
* the grace period lasts ``grace_hours`` so VPN keeps working while the retries run;
* every decline sends the customer a message (Telegram + in-app): which attempt it was, when the next one is,
  and how to pay by hand — the last one says auto-renew is now off;
* ``wallet_fallback``: if the wallet holds enough for the plan, the renewal is paid from the wallet instead of
  waiting for the next card attempt (the same purchase as «оплатить с баланса», idempotent per decline).

Admin: «Тарифы → Повторные попытки» and the mobile card.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import require_permission

logger = logging.getLogger("vpnshop.dunning")
router = APIRouter()
CONFIG_KEY = "dunning.config"
DEFAULT = {"enabled": False, "retry_hours": [24, 72, 120], "max_failures": 3, "grace_hours": 72, "notify": True, "wallet_fallback": True}


class DunningIn(BaseModel):
    enabled: bool = False
    retry_hours: list[int] = Field(default_factory=lambda: [24, 72, 120], min_length=1, max_length=8)
    max_failures: int = Field(3, ge=1, le=8)
    grace_hours: int = Field(72, ge=0, le=336)
    notify: bool = True
    wallet_fallback: bool = True


async def load(db: AsyncSession) -> dict:
    from .node_health import _load
    return {**DEFAULT, **(await _load(db, CONFIG_KEY, DEFAULT) or {})}


def next_attempt(failures: int, cfg: dict) -> timedelta:
    """Pause before the next charge after ``failures`` declines."""
    if not cfg.get("enabled"):
        return timedelta(hours=min(72, 2 ** min(failures, 6)))
    hours = [int(h) for h in cfg.get("retry_hours") or DEFAULT["retry_hours"]]
    return timedelta(hours=max(1, hours[min(max(failures, 1), len(hours)) - 1]))


def max_failures(cfg: dict) -> int:
    return int(cfg.get("max_failures") or 3) if cfg.get("enabled") else 3


def grace(cfg: dict) -> timedelta:
    return timedelta(hours=int(cfg.get("grace_hours", 72)) if cfg.get("enabled") else 72)


def notice(failures: int, cfg: dict, next_at: datetime | None, wallet: bool) -> str:
    total = max_failures(cfg)
    if failures >= total:
        return ("Не получилось списать оплату за продление подписки — автопродление выключено. "
                "Продлите подписку вручную в боте или кабинете, чтобы VPN не отключился.")
    when = f" Следующая попытка — {next_at:%d.%m %H:%M} UTC." if next_at else ""
    extra = " Если на балансе хватит денег, продлим с баланса." if wallet else " Можно пополнить баланс или оплатить вручную."
    return f"Не получилось списать оплату за продление (попытка {failures} из {total}).{when}{extra} VPN пока работает."


async def on_failure(db: AsyncSession, user, sub, method, cfg: dict, send=None) -> None:
    """A renewal was declined: tell the customer (once per attempt)."""
    if not cfg.get("enabled") or not cfg.get("notify"):
        return
    from .main import enqueue_notification
    failures = int(method.failure_count or 0)
    text = notice(failures, cfg, method.next_attempt_at if failures < max_failures(cfg) else None, bool(cfg.get("wallet_fallback")))
    key = f"dunning:{sub.id}:{(sub.expires_at or datetime.utcnow()):%Y%m%d}:{failures}"
    await enqueue_notification(db, user_id=user.id, channel="in_app", kind="renewal_failed", title="Не удалось продлить подписку",
                               body=text, dedupe_key=key)
    await db.commit()
    if send is None:
        from .schedulers import notify_user_telegram as send
    try:
        await send(user.telegram_id, text)
    except Exception as exc:  # noqa: BLE001
        logger.debug("dunning notice for %s skipped: %s", user.id, exc)


async def wallet_pass(db: AsyncSession, spend=None) -> list[int]:
    """Pay renewals that the card declined from the wallet, when the balance covers the plan."""
    from .models import AutoRenewMethod, Plan, Subscription, User
    cfg = await load(db)
    if not cfg["enabled"] or not cfg["wallet_fallback"]:
        return []
    if spend is None:
        from .customer_api import spend_from_wallet as spend
    rows = (await db.execute(select(Subscription, User, Plan).join(User, User.id == Subscription.user_id).join(Plan, Plan.id == Subscription.plan_id)
                             .where(Subscription.last_renewal_failure_at.is_not(None), Subscription.auto_renew_enabled.is_(True),
                                    Subscription.lifecycle_status == "grace", User.deleted_at.is_(None), User.restricted_at.is_(None),
                                    User.wallet_balance >= Plan.price).limit(50))).all()
    paid = []
    for sub, user, plan in rows:
        idem = f"dunning-wallet-{sub.id}-{sub.last_renewal_failure_at:%Y%m%d%H%M}"
        try:
            result = await spend(db, user, {"plan_id": plan.id, "subscription_id": sub.id}, idem)
        except HTTPException as exc:
            logger.info("wallet renewal of subscription %s refused: %s", sub.id, exc.detail)
            await db.rollback()
            continue
        except Exception as exc:  # noqa: BLE001 — the next pass retries with the same idempotency key
            logger.warning("wallet renewal of subscription %s failed: %s", sub.id, exc)
            await db.rollback()
            continue
        method = await db.scalar(select(AutoRenewMethod).where(AutoRenewMethod.user_id == user.id))
        if method:
            method.failure_count, method.status, method.last_error = 0, "active", None
        fresh = await db.get(Subscription, sub.id)
        if fresh:
            fresh.last_renewal_failure_at = None
        await db.commit()
        paid.append(sub.id)
        logger.info("subscription %s renewed from the wallet (payment %s)", sub.id, result.get("payment_id"))
    return paid


async def _loop():
    from .db import SessionLocal
    from .main import redis_client
    while True:
        await asyncio.sleep(900)
        try:
            if redis_client is not None and not await redis_client.set("lock:dunning", "1", nx=True, ex=880):
                continue
            async with SessionLocal() as db:
                await wallet_pass(db)
        except Exception as exc:  # noqa: BLE001
            logger.warning("dunning pass failed: %s", exc)


def _start():
    from .main import _track_task
    _track_task(_loop())


router.add_event_handler("startup", _start)


async def stats(db: AsyncSession) -> dict:
    from .models import AutoRenewMethod, Payment, Subscription
    since = datetime.utcnow() - timedelta(days=30)
    return {"past_due": int(await db.scalar(select(func.count()).select_from(AutoRenewMethod).where(AutoRenewMethod.status == "past_due")) or 0),
            "switched_off": int(await db.scalar(select(func.count()).select_from(AutoRenewMethod).where(AutoRenewMethod.status == "payment_failed")) or 0),
            "in_grace": int(await db.scalar(select(func.count()).select_from(Subscription).where(Subscription.lifecycle_status == "grace",
                                                                                                 Subscription.last_renewal_failure_at.is_not(None))) or 0),
            "wallet_30d": int(await db.scalar(select(func.count()).select_from(Payment).where(Payment.idempotency_key.like("dunning-wallet-%"),
                                                                                              Payment.created_at >= since,
                                                                                              Payment.status.in_(("paid", "fulfilled")))) or 0)}


@router.get("/api/admin/dunning")
async def get_dunning(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("read"))):
    return {"config": await load(db), **await stats(db)}


@router.put("/api/admin/dunning")
async def put_dunning(payload: DunningIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("manage_plans"))):
    from .main import audit
    from .node_health import _save
    if any(h < 1 or h > 720 for h in payload.retry_hours):
        raise HTTPException(400, "Интервал попытки — от 1 до 720 часов")
    await _save(db, CONFIG_KEY, payload.model_dump())
    await audit(db, "dunning.config", admin.email, None, payload.model_dump())
    await db.commit()
    return await load(db)
