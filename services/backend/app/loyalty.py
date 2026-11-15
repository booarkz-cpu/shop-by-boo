"""v28.51 «Уровни лояльности»: Бронза → Серебро → Золото по стажу и сумме оплат.

A level is reached when the customer has been paying for ``months`` months (since the first paid order) **or** has
paid ``spent`` in total (refunded orders do not count). Every level may give:

* ``cashback_percent`` — part of each paid subscription order back to the wallet (``loyalty-cashback:<payment>`` in
  the financial ledger, credited after ``hold_days`` so a quick refund does not keep it; a later refund takes the
  cashback back, as far as the balance allows);
* ``discount_percent`` — a discount on purchases and auto-renewals (not added to a promo code: the larger one wins);
* ``bonus_days`` — free days once, when the level is reached (the «bonus_days» machinery, one job per level).

Off by default (``loyalty.config``). Customers: cabinet, bot (/level), apps (in «Моя статистика»). Admin:
«Маркетинг → Уровни лояльности» and the mobile card. Reached levels live in ``loyalty_members``.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import require_permission

logger = logging.getLogger("vpnshop.loyalty")
router = APIRouter()
CONFIG_KEY = "loyalty.config"
LEVELS = [
    {"key": "bronze", "title": "Бронза", "months": 0, "spent": 0, "cashback_percent": 0, "discount_percent": 0, "bonus_days": 0},
    {"key": "silver", "title": "Серебро", "months": 3, "spent": 1500, "cashback_percent": 3, "discount_percent": 0, "bonus_days": 3},
    {"key": "gold", "title": "Золото", "months": 12, "spent": 5000, "cashback_percent": 5, "discount_percent": 5, "bonus_days": 7},
]
DEFAULT = {"enabled": False, "hold_days": 7, "since": None, "levels": LEVELS}
PAID = ("paid", "fulfilled")
CENT = Decimal("0.01")


class LevelIn(BaseModel):
    key: str = Field(..., pattern=r"^[a-z0-9_-]{1,24}$")
    title: str = Field(..., min_length=1, max_length=40)
    months: int = Field(0, ge=0, le=240)
    spent: float = Field(0, ge=0, le=10_000_000)
    cashback_percent: float = Field(0, ge=0, le=50)
    discount_percent: float = Field(0, ge=0, le=50)
    bonus_days: int = Field(0, ge=0, le=90)


class LoyaltyIn(BaseModel):
    enabled: bool = False
    hold_days: int = Field(7, ge=0, le=60)
    levels: list[LevelIn] = Field(..., min_length=1, max_length=8)


async def load(db: AsyncSession) -> dict:
    from .node_health import _load
    cfg = {**DEFAULT, **(await _load(db, CONFIG_KEY, DEFAULT) or {})}
    cfg["levels"] = sorted(cfg.get("levels") or LEVELS, key=lambda x: (float(x.get("spent", 0)), int(x.get("months", 0))))
    return cfg


async def progress(db: AsyncSession, user_id: int, now: datetime | None = None) -> dict:
    """Months since the first paid order and the total paid (refunds excluded)."""
    from .models import Payment
    now = now or datetime.utcnow()
    first = await db.scalar(select(func.min(Payment.paid_at)).where(Payment.user_id == user_id, Payment.status.in_(PAID), Payment.purpose == "subscription"))
    spent = await db.scalar(select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.user_id == user_id, Payment.status.in_(PAID),
                                                                                       Payment.purpose == "subscription"))
    months = int((now - first).days // 30) if first else 0
    return {"months": months, "spent": Decimal(str(spent or 0)).quantize(CENT)}


def level_for(levels: list[dict], months: int, spent: Decimal) -> tuple[int, dict]:
    """The highest level whose months **or** spent threshold is met (the first level is everyone's)."""
    index = 0
    for i, lv in enumerate(levels):
        if i == 0 or months >= int(lv.get("months") or 0) > 0 or spent >= Decimal(str(lv.get("spent") or 0)) > 0:
            index = i
    return index, levels[index]


async def current(db: AsyncSession, user_id: int, cfg: dict | None = None) -> dict | None:
    cfg = cfg or await load(db)
    if not cfg["enabled"]:
        return None
    p = await progress(db, user_id)
    index, lv = level_for(cfg["levels"], p["months"], p["spent"])
    nxt = cfg["levels"][index + 1] if index + 1 < len(cfg["levels"]) else None
    need = None
    if nxt:
        parts = []
        if int(nxt.get("months") or 0) > p["months"]:
            parts.append(f"{int(nxt['months']) - p['months']} мес. с нами")
        if Decimal(str(nxt.get("spent") or 0)) > p["spent"]:
            parts.append(f"оплат на {(Decimal(str(nxt['spent'])) - p['spent']).quantize(CENT)} ₽")
        need = " или ".join(parts) or None
    return {"key": lv["key"], "title": lv["title"], "index": index, "cashback_percent": lv.get("cashback_percent", 0),
            "discount_percent": lv.get("discount_percent", 0), "months": p["months"], "spent": str(p["spent"]),
            "next": {"title": nxt["title"], "need": need, "cashback_percent": nxt.get("cashback_percent", 0),
                     "discount_percent": nxt.get("discount_percent", 0), "bonus_days": nxt.get("bonus_days", 0)} if nxt else None,
            "levels": [{"title": x["title"], "months": x.get("months", 0), "spent": x.get("spent", 0), "cashback_percent": x.get("cashback_percent", 0),
                        "discount_percent": x.get("discount_percent", 0), "bonus_days": x.get("bonus_days", 0)} for x in cfg["levels"]]}


async def renewal_discount(db: AsyncSession, user, amount) -> Decimal:
    """The level's discount on this purchase or renewal (zero while the levels are off)."""
    try:
        lv = await current(db, user.id)
    except Exception as exc:  # noqa: BLE001 — a pricing helper never breaks a checkout
        logger.warning("loyalty discount for %s skipped: %s", getattr(user, "id", None), exc)
        return Decimal("0.00")
    if not lv or not lv["discount_percent"]:
        return Decimal("0.00")
    return (Decimal(str(amount)) * Decimal(str(lv["discount_percent"])) / 100).quantize(CENT, rounding=ROUND_HALF_UP)


async def _ledger(db, key):
    from .models import FinancialLedger
    return await db.scalar(select(FinancialLedger.id).where(FinancialLedger.operation_key == key))


async def cashback_pass(db: AsyncSession, now: datetime | None = None) -> dict:
    """Credit cashback for paid orders older than ``hold_days``; take it back from refunded ones."""
    from .main import record_financial_event
    from .models import Payment, User
    cfg = await load(db)
    out = {"credited": 0, "reversed": 0}
    if not cfg["enabled"] or not cfg.get("since"):
        return out
    now = now or datetime.utcnow()
    since = datetime.fromisoformat(cfg["since"])
    rows = (await db.execute(select(Payment).where(Payment.status.in_(PAID), Payment.purpose == "subscription", Payment.paid_at.is_not(None),
                                                   Payment.paid_at >= since, Payment.paid_at <= now - timedelta(days=int(cfg["hold_days"])))
                             .order_by(Payment.id).limit(500))).scalars().all()
    for p in rows:
        key = f"loyalty-cashback:{p.id}"
        if await _ledger(db, key):
            continue
        lv = await current(db, p.user_id, cfg)
        percent = Decimal(str(lv["cashback_percent"])) if lv else Decimal(0)
        amount = (Decimal(str(p.amount)) * percent / 100).quantize(CENT, rounding=ROUND_HALF_UP)
        user = await db.scalar(select(User).where(User.id == p.user_id).with_for_update())
        if amount <= 0 or not user or user.deleted_at:
            continue
        await record_financial_event(db, operation_key=key, user_id=user.id, payment_id=p.id, kind="loyalty_cashback", direction="credit",
                                     amount=amount, currency=p.currency, metadata={"level": lv["key"], "percent": str(percent)})
        user.wallet_balance = (Decimal(str(user.wallet_balance or 0)) + amount).quantize(CENT)
        await db.commit()
        out["credited"] += 1
    refunded = (await db.execute(select(Payment).where(Payment.status.in_(("refunded", "refunded_pending_revoke")), Payment.purpose == "subscription",
                                                       Payment.paid_at >= since).order_by(Payment.id).limit(500))).scalars().all()
    from .models import FinancialLedger
    for p in refunded:
        credit = await db.scalar(select(FinancialLedger).where(FinancialLedger.operation_key == f"loyalty-cashback:{p.id}"))
        key = f"loyalty-cashback-reversal:{p.id}"
        if not credit or await _ledger(db, key):
            continue
        user = await db.scalar(select(User).where(User.id == p.user_id).with_for_update())
        if not user:
            continue
        take = min(Decimal(str(credit.amount)), Decimal(str(user.wallet_balance or 0))).quantize(CENT)
        if take > 0:
            await record_financial_event(db, operation_key=key, user_id=user.id, payment_id=p.id, kind="loyalty_cashback_reversal",
                                         direction="debit", amount=take, currency=credit.currency, metadata={"refund": True})
            user.wallet_balance = (Decimal(str(user.wallet_balance or 0)) - take).quantize(CENT)
            await db.commit()
            out["reversed"] += 1
    return out


async def levels_pass(db: AsyncSession, apply=None, notify=None) -> list[tuple[int, str]]:
    """Store reached levels; a new level gives its bonus days once and a message."""
    from .models import LoyaltyMember, Payment, Subscription, User
    cfg = await load(db)
    if not cfg["enabled"]:
        return []
    if apply is None:
        from .bonus_days import apply_bonus_days as apply
    users = (await db.execute(select(Payment.user_id).where(Payment.status.in_(PAID), Payment.purpose == "subscription").distinct().limit(5000))).scalars().all()
    changed = []
    for uid in users:
        p = await progress(db, uid)
        index, lv = level_for(cfg["levels"], p["months"], p["spent"])
        member = await db.get(LoyaltyMember, uid)
        if member and member.level == lv["key"]:
            continue
        old_rank = next((i for i, x in enumerate(cfg["levels"]) if member and x["key"] == member.level), -1)
        if member:
            member.level, member.reached_at = lv["key"], datetime.utcnow()
        else:
            db.add(LoyaltyMember(user_id=uid, level=lv["key"], reached_at=datetime.utcnow()))
        await db.commit()
        if index <= old_rank or index == 0:
            continue  # a lower level (refunds, edited thresholds) or the starting one: nothing to celebrate
        changed.append((uid, lv["key"]))
        days = int(lv.get("bonus_days") or 0)
        live = await db.scalar(select(Subscription.id).where(Subscription.user_id == uid, Subscription.is_primary.is_(True),
                                                              Subscription.lifecycle_status.in_(("active", "grace", "cancel_scheduled"))))
        if days and live:
            try:
                await apply(db, f"loyalty:{uid}:{lv['key']}", uid, days, "loyalty", title=f"Уровень «{lv['title']}»: +{days} дн.",
                            body=f"Вы достигли уровня «{lv['title']}» — дарим {days} дней подписки.")
            except Exception as exc:  # noqa: BLE001 — the job key keeps it once; the next pass does not repeat a stored level
                logger.warning("loyalty bonus for %s failed: %s", uid, exc)
        user = await db.get(User, uid)
        if user and user.telegram_id:
            if notify is None:
                from .schedulers import notify_user_telegram as notify
            perks = [f"кешбэк {lv['cashback_percent']}%" if lv.get("cashback_percent") else "",
                     f"скидка {lv['discount_percent']}% на продление" if lv.get("discount_percent") else "",
                     f"+{days} дн. в подарок" if days and live else ""]
            text = f"🎉 Новый уровень — «{lv['title']}»!" + (" Теперь у вас: " + ", ".join(x for x in perks if x) + "." if any(perks) else "")
            try:
                await notify(user.telegram_id, text)
            except Exception as exc:  # noqa: BLE001
                logger.debug("loyalty notice for %s skipped: %s", uid, exc)
    return changed


async def _loop():
    from .db import SessionLocal
    from .main import redis_client
    while True:
        await asyncio.sleep(1800)
        try:
            if redis_client is not None and not await redis_client.set("lock:loyalty", "1", nx=True, ex=1700):
                continue
            async with SessionLocal() as db:
                await levels_pass(db)
                await cashback_pass(db)
        except Exception as exc:  # noqa: BLE001
            logger.warning("loyalty pass failed: %s", exc)


def _start():
    from .main import _track_task
    _track_task(_loop())


router.add_event_handler("startup", _start)


@router.get("/api/me/loyalty")
async def my_loyalty(request: Request, db: AsyncSession = Depends(get_db)):
    from .main import user_from_token
    user = await user_from_token(request, db)
    lv = await current(db, user.id)
    if not lv:
        return {"enabled": False}
    from .models import FinancialLedger
    earned = await db.scalar(select(func.coalesce(func.sum(FinancialLedger.amount), 0)).where(FinancialLedger.user_id == user.id,
                                                                                               FinancialLedger.kind == "loyalty_cashback"))
    return {"enabled": True, **lv, "cashback_earned": str(Decimal(str(earned or 0)).quantize(CENT))}


@router.get("/api/admin/loyalty")
async def admin_loyalty(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("read"))):
    from .models import FinancialLedger, LoyaltyMember
    cfg = await load(db)
    counts = dict((await db.execute(select(LoyaltyMember.level, func.count()).group_by(LoyaltyMember.level))).all())
    since = datetime.utcnow() - timedelta(days=30)
    paid = await db.scalar(select(func.coalesce(func.sum(FinancialLedger.amount), 0)).where(FinancialLedger.kind == "loyalty_cashback",
                                                                                             FinancialLedger.created_at >= since))
    return {"config": cfg, "members": {lv["key"]: int(counts.get(lv["key"], 0)) for lv in cfg["levels"]},
            "cashback_30d": str(Decimal(str(paid or 0)).quantize(CENT))}


@router.put("/api/admin/loyalty")
async def admin_loyalty_config(payload: LoyaltyIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("manage_plans"))):
    from .main import audit
    from .node_health import _save
    keys = [lv.key for lv in payload.levels]
    if len(set(keys)) != len(keys):
        raise HTTPException(400, "У уровней должны быть разные ключи")
    old = await load(db)
    value = payload.model_dump()
    # Cashback counts orders paid after the levels were first switched on: no payout for the whole history at once.
    value["since"] = old.get("since") or (datetime.utcnow().isoformat() if payload.enabled else None)
    await _save(db, CONFIG_KEY, value)
    await audit(db, "loyalty.config", admin.email, None, value)
    await db.commit()
    return await load(db)
