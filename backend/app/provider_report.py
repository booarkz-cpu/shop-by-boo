"""«Платёжные агенты → Кассы за период»: how each gateway actually sells.

For every gateway over the chosen days: orders opened, paid, conversion, revenue and the median time from the
payment page to the money. The best-converting gateway is marked so the operator can move it up the queue."""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from statistics import median

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import require_permission

router = APIRouter()
PAID = ("paid", "fulfilled", "refunded", "refunded_pending_revoke")
MIN_FOR_BEST = 10  # a conversion of 2 orders out of 2 is not «the best gateway»


async def build_report(db: AsyncSession, days: int, now: datetime | None = None) -> dict:
    from .models import Payment
    from .payment_policy import PAYMENT_AGENTS
    now = now or datetime.utcnow()
    since = now - timedelta(days=days)
    rows = (await db.execute(select(Payment.provider, Payment.status, Payment.amount, Payment.created_at, Payment.paid_at)
                             .where(Payment.created_at >= since, Payment.provider.in_(PAYMENT_AGENTS)))).all()
    stats: dict[str, dict] = {}
    for provider, status, amount, created_at, paid_at in rows:
        item = stats.setdefault(provider, {"provider": provider, "orders": 0, "paid": 0, "revenue": Decimal("0"), "_minutes": []})
        item["orders"] += 1
        if status in PAID:
            item["paid"] += 1
            item["revenue"] += Decimal(str(amount or 0))
            if paid_at and created_at:
                item["_minutes"].append(max(0.0, (paid_at - created_at).total_seconds() / 60))
    out = []
    for item in stats.values():
        minutes = item.pop("_minutes")
        out.append({**item, "revenue": str(item["revenue"].quantize(Decimal("0.01"))),
                    "conversion": round(item["paid"] * 100 / item["orders"], 1) if item["orders"] else 0.0,
                    "median_minutes_to_pay": round(median(minutes), 1) if minutes else None})
    out.sort(key=lambda x: (-x["conversion"], -x["orders"]))
    best = next((x["provider"] for x in out if x["orders"] >= MIN_FOR_BEST), None)
    return {"days": days, "since": since.isoformat(), "providers": out, "best": best}


@router.get("/api/admin/payments/providers-report")
async def providers_report(days: int = Query(30, ge=1, le=365), db: AsyncSession = Depends(get_db),
                           admin=Depends(require_permission("payments.read"))):
    return await build_report(db, days)
