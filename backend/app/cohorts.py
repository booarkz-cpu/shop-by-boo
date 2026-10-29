"""v28.52 «Когорты»: how many customers of each month of the first payment stay after 1, 3 and 6 months, and the money
each cohort brought; optionally split by the acquisition source (``users.acquisition_source``).

A customer of a cohort is «still with us» at month N when a subscription of theirs runs at least N×30 days after the
first payment (paid renewals, gifts and bonus days all count). A month that has not passed yet is ``null``.
Admin: «Аналитика → Когорты» and the mobile card; ``GET /api/admin/cohorts``.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import require_permission

router = APIRouter()
POINTS = (1, 3, 6, 12)
PAID = ("paid", "fulfilled")


async def build(db: AsyncSession, months: int = 12, by_source: bool = False, now: datetime | None = None) -> dict:
    from .models import Payment, Subscription, User
    now = now or datetime.utcnow()
    first = dict((await db.execute(select(Payment.user_id, func.min(Payment.paid_at)).where(Payment.status.in_(PAID), Payment.purpose == "subscription",
                                                                                          Payment.paid_at.is_not(None)).group_by(Payment.user_id))).all())
    start = (now.replace(day=1) - timedelta(days=31 * (months - 1))).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    users = {uid: at for uid, at in first.items() if at >= start}
    if not users:
        return {"months": months, "points": list(POINTS), "cohorts": []}
    ids = list(users)
    until = dict((await db.execute(select(Subscription.user_id, func.max(Subscription.expires_at)).where(Subscription.user_id.in_(ids))
                                   .group_by(Subscription.user_id))).all())
    revenue = dict((await db.execute(select(Payment.user_id, func.coalesce(func.sum(Payment.amount), 0)).where(Payment.user_id.in_(ids), Payment.status.in_(PAID))
                                     .group_by(Payment.user_id))).all())
    sources = dict((await db.execute(select(User.id, User.acquisition_source).where(User.id.in_(ids)))).all()) if by_source else {}
    groups: dict[tuple[str, str], list[int]] = defaultdict(list)
    for uid, at in users.items():
        groups[(at.strftime("%Y-%m"), (sources.get(uid) or "—") if by_source else "")].append(uid)
    cohorts = []
    for (month, source), members in sorted(groups.items()):
        row = {"month": month, "source": source or None, "size": len(members),
               "revenue": str(sum((Decimal(str(revenue.get(u, 0))) for u in members), Decimal("0")).quantize(Decimal("0.01")))}
        for n in POINTS:
            due = [u for u in members if users[u] + timedelta(days=30 * n) <= now]
            if not due:
                row[f"m{n}"] = None
                continue
            kept = sum(1 for u in due if until.get(u) and until[u] >= users[u] + timedelta(days=30 * n))
            row[f"m{n}"] = round(kept * 100 / len(due))
        row["arpu"] = str((Decimal(row["revenue"]) / len(members)).quantize(Decimal("0.01")))
        cohorts.append(row)
    return {"months": months, "points": list(POINTS), "cohorts": cohorts}


@router.get("/api/admin/cohorts")
async def admin_cohorts(months: int = 12, by_source: bool = False, db: AsyncSession = Depends(get_db),
                        admin=Depends(require_permission("analytics.read"))):
    return await build(db, max(1, min(months, 24)), by_source)
