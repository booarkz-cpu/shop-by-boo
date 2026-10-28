"""Unit economics by acquisition source: what a customer costs and what they bring.

The source is the first touch and is never overwritten: the bot link ``t.me/<bot>?start=src_<name>`` (also combined
with a referral as ``ref_<code>``…) and the cabinet or Mini App link ``?utm_source=<name>``. Ad spend per source and
month is entered in «Аналитика → Юнит-экономика». For each source over the chosen months: new customers, paying
customers, conversion, revenue, spend, CAC (spend per paying customer), revenue per paying customer and ROMI.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import require_permission

router = APIRouter()
SPEND_KEY = "economics.spend"
SOURCE_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,47}$")
PAID = ("paid", "fulfilled")
ORGANIC = "без источника"


def clean_source(raw: str | None) -> str | None:
    value = (raw or "").strip().lower().replace(" ", "_")[:48]
    return value if SOURCE_RE.fullmatch(value) else None


def source_from_start(payload: str) -> str | None:
    """«src_vk_ads» or «ref_AB12__src_vk_ads» → «vk_ads»."""
    for part in (payload or "").split("__"):
        if part.lower().startswith("src_"):
            return clean_source(part[4:])
    return None


async def remember_source(db: AsyncSession, user, source: str | None) -> bool:
    """First touch only, and only for a fresh account (an old customer clicking an ad is not «acquired» by it)."""
    if not source or user.acquisition_source or (user.created_at and user.created_at < datetime.utcnow() - timedelta(days=1)):
        return False
    user.acquisition_source = source
    return True


class SpendIn(BaseModel):
    source: str
    month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    amount: Decimal = Field(ge=0, le=Decimal("100000000"))

    @field_validator("source")
    @classmethod
    def _source(cls, value: str) -> str:
        cleaned = clean_source(value)
        if not cleaned:
            raise ValueError("Источник: латиница, цифры, _ . - (до 48 символов)")
        return cleaned


async def _spend(db: AsyncSession) -> dict:
    from .main import setting_value
    try:
        value = json.loads(await setting_value(db, SPEND_KEY, "{}") or "{}")
    except ValueError:
        value = {}
    return value if isinstance(value, dict) else {}


def _months(now: datetime, count: int) -> list[str]:
    year, month, out = now.year, now.month, []
    for _ in range(count):
        out.append(f"{year:04d}-{month:02d}")
        year, month = (year - 1, 12) if month == 1 else (year, month - 1)
    return out


async def report(db: AsyncSession, months: int = 3, now: datetime | None = None) -> dict:
    from .models import Payment, User
    now = now or datetime.utcnow()
    window = _months(now, months)
    since = datetime(int(window[-1][:4]), int(window[-1][5:]), 1)
    source = func.coalesce(User.acquisition_source, ORGANIC)
    users = dict((await db.execute(select(source, func.count(User.id)).where(User.created_at >= since, User.deleted_at.is_(None))
                                   .group_by(source))).all())
    paying_rows = (await db.execute(select(source, func.count(func.distinct(Payment.user_id)), func.coalesce(func.sum(Payment.amount), 0))
                                    .join(User, User.id == Payment.user_id)
                                    .where(User.created_at >= since, Payment.status.in_(PAID), Payment.provider != "wallet")
                                    .group_by(source))).all()
    paying = {s: (int(n), Decimal(str(r))) for s, n, r in paying_rows}
    spend_all = await _spend(db)
    spend = {s: sum((Decimal(str(v)) for m, v in by_month.items() if m in window), Decimal("0")) for s, by_month in spend_all.items()}
    rows = []
    for name in sorted(set(users) | set(paying) | set(spend), key=lambda s: (s == ORGANIC, s)):
        new = int(users.get(name, 0))
        payers, revenue = paying.get(name, (0, Decimal("0")))
        cost = spend.get(name, Decimal("0"))
        rows.append({
            "source": name, "new_customers": new, "paying_customers": payers,
            "conversion": round(payers * 100 / new, 1) if new else 0.0,
            "revenue": str(revenue.quantize(Decimal("0.01"))), "spend": str(cost.quantize(Decimal("0.01"))),
            "cac": str((cost / payers).quantize(Decimal("0.01"))) if payers and cost else None,
            "revenue_per_payer": str((revenue / payers).quantize(Decimal("0.01"))) if payers else None,
            "romi": round(float((revenue - cost) / cost * 100), 1) if cost else None,
        })
    return {"months": window, "sources": rows, "spend": spend_all}


@router.get("/api/admin/analytics/economics")
async def economics(months: int = Query(3, ge=1, le=12), db: AsyncSession = Depends(get_db), admin=Depends(require_permission("analytics.read"))):
    return await report(db, months)


@router.put("/api/admin/analytics/economics/spend")
async def put_spend(payload: SpendIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("settings.runtime.write"))):
    from .main import audit, set_setting
    data = await _spend(db)
    month_values = data.setdefault(payload.source, {})
    if payload.amount == 0:
        month_values.pop(payload.month, None)
    else:
        month_values[payload.month] = str(payload.amount.quantize(Decimal("0.01")))
    if not month_values:
        data.pop(payload.source, None)
    await set_setting(db, SPEND_KEY, json.dumps(data, ensure_ascii=False))
    await audit(db, "economics.spend", admin.email if admin else "system", payload.source, {"month": payload.month, "amount": str(payload.amount)})
    await db.commit()
    return data


@router.post("/api/me/source")
async def my_source(payload: dict, request: Request, db: AsyncSession = Depends(get_db)):
    """The cabinet and the Mini App send ``utm_source`` once after sign-in; first touch wins."""
    from .main import user_from_token
    user = await user_from_token(request, db)
    changed = await remember_source(db, user, clean_source(str(payload.get("source") or "")))
    from .ad_postbacks import remember_click
    clicked = await remember_click(db, user.id, str(payload.get("click_id") or "") or None, str(payload.get("ym_uid") or "") or None)
    if changed or clicked:
        await db.commit()
    if clicked and user.created_at and (datetime.utcnow() - user.created_at).total_seconds() < 86400:
        from .ad_postbacks import fire
        fire(user.id, "registration")
    return {"source": user.acquisition_source}
