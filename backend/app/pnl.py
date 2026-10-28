"""P&L: what the shop earns after gateway fees, servers, domains, software and advertising — by month and per node.

* Revenue — paid payments by month (wallet purchases are not counted twice: the top-up is the revenue), minus refunds.
* Gateway fees — the percent the owner sets per gateway («ЮKassa 3.5 %…»).
* Costs — entries in «Аналитика → Расходы»: month, category (servers, domains, software, staff, other), vendor and,
  for a server, its node (to see the cost per node); advertising spend comes from unit economics.
* Result — gross profit, margin, profit per paying customer and the cost of each node per active customer.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import require_permission

router = APIRouter()
FEES_KEY = "pnl.fees"
CATEGORIES = ("servers", "domains", "software", "staff", "other")
EXTERNAL = ("yookassa", "platega", "rollypay", "cryptobot", "freekassa", "cloudpayments", "lava", "pal24", "mulenpay", "wata", "antilopay", "aurapay", "anore", "stars", "telegram_stars")


class CostIn(BaseModel):
    month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    category: str = Field(pattern="^(servers|domains|software|staff|other)$")
    vendor: str = Field("", max_length=80)
    node: str = Field("", max_length=120)
    amount: Decimal = Field(gt=0, le=100_000_000, max_digits=12, decimal_places=2)
    note: str = Field("", max_length=200)


def months_back(count: int, now: datetime) -> list[str]:
    out, year, month = [], now.year, now.month
    for _ in range(count):
        out.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return list(reversed(out))


async def report(db: AsyncSession, months: int = 6, now: datetime | None = None) -> dict:
    from .models import InfraCost, Payment, RefundRequest, Subscription
    from .node_health import _load
    now = now or datetime.utcnow()
    keys = months_back(months, now)
    fees = await _load(db, FEES_KEY, {})
    rows = (await db.execute(select(Payment.paid_at, Payment.amount, Payment.provider).where(
        Payment.paid_at.is_not(None), Payment.status.in_(("paid", "fulfilled", "refunded", "refunded_pending_revoke")),
        Payment.provider != "wallet"))).all()
    revenue, fee = defaultdict(Decimal), defaultdict(Decimal)
    for paid_at, amount, provider in rows:
        key = paid_at.strftime("%Y-%m")
        if key in keys:
            revenue[key] += Decimal(str(amount))
            fee[key] += Decimal(str(amount)) * Decimal(str(fees.get(provider, 0))) / 100
    refunds = defaultdict(Decimal)
    for created, amount in (await db.execute(select(RefundRequest.updated_at, RefundRequest.amount).where(
            RefundRequest.status.in_(("refunded", "refunded_pending_revoke"))))).all():
        key = created.strftime("%Y-%m")
        if key in keys:
            refunds[key] += Decimal(str(amount))
    costs, by_node = defaultdict(lambda: defaultdict(Decimal)), defaultdict(Decimal)
    for c in (await db.execute(select(InfraCost).where(InfraCost.month.in_(keys)))).scalars():
        costs[c.month][c.category] += Decimal(str(c.amount))
        if c.node and c.month == keys[-1]:
            by_node[c.node] += Decimal(str(c.amount))
    ads = await _ad_spend(db, keys)
    active = int(await db.scalar(select(func.count()).select_from(Subscription).where(
        Subscription.expires_at > now, Subscription.lifecycle_status.in_(("active", "cancel_scheduled", "grace")))) or 0)
    table = []
    for key in keys:
        cost = sum(costs[key].values(), Decimal("0"))
        net = revenue[key] - refunds[key] - fee[key] - cost - ads.get(key, Decimal("0"))
        income = revenue[key] - refunds[key]
        table.append({"month": key, "revenue": str(revenue[key].quantize(Decimal("0.01"))), "refunds": str(refunds[key]),
                      "fees": str(fee[key].quantize(Decimal("0.01"))), "costs": {k: str(v) for k, v in costs[key].items()},
                      "ads": str(ads.get(key, Decimal("0"))), "profit": str(net.quantize(Decimal("0.01"))),
                      "margin": round(float(net / income * 100), 1) if income else None})
    last = table[-1]
    return {"months": table, "fees": fees, "active_customers": active,
            "profit_per_customer": str((Decimal(last["profit"]) / active).quantize(Decimal("0.01"))) if active else None,
            "nodes": [{"node": n, "cost": str(v), "per_customer": str((v / active).quantize(Decimal("0.01"))) if active else None}
                      for n, v in sorted(by_node.items(), key=lambda x: -x[1])]}


async def _ad_spend(db: AsyncSession, keys: list[str]) -> dict[str, Decimal]:
    from .economics import _spend
    spend = await _spend(db)  # {source: {"YYYY-MM": amount}}
    out = defaultdict(Decimal)
    for _source, months in (spend or {}).items():
        if isinstance(months, dict):
            for month, amount in months.items():
                if month in keys:
                    out[month] += Decimal(str(amount))
    return out


@router.get("/api/admin/pnl")
async def pnl(months: int = 6, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("analytics.read"))):
    return await report(db, max(1, min(months, 24)))


@router.get("/api/admin/pnl/costs")
async def list_costs(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("analytics.read"))):
    from .models import InfraCost
    rows = (await db.execute(select(InfraCost).order_by(InfraCost.month.desc(), InfraCost.id.desc()).limit(500))).scalars().all()
    return {"costs": [{"id": c.id, "month": c.month, "category": c.category, "vendor": c.vendor, "node": c.node,
                       "amount": str(c.amount), "note": c.note} for c in rows], "categories": list(CATEGORIES)}


@router.post("/api/admin/pnl/costs")
async def add_cost(payload: CostIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("payments.reconcile"))):
    from .main import audit
    from .models import InfraCost
    row = InfraCost(**payload.model_dump(), created_at=datetime.utcnow())
    db.add(row)
    await db.flush()
    await audit(db, "pnl.cost.added", admin.email, str(row.id), {"month": row.month, "amount": str(row.amount)})
    await db.commit()
    return {"id": row.id}


@router.delete("/api/admin/pnl/costs/{cost_id}")
async def delete_cost(cost_id: int, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("payments.reconcile"))):
    from .models import InfraCost
    result = await db.execute(delete(InfraCost).where(InfraCost.id == cost_id))
    if not result.rowcount:
        raise HTTPException(404, "Запись не найдена")
    await db.commit()
    return {"ok": True}


@router.put("/api/admin/pnl/fees")
async def put_fees(payload: dict[str, float], db: AsyncSession = Depends(get_db), admin=Depends(require_permission("payments.reconcile"))):
    from .node_health import _save
    clean = {k: round(float(v), 2) for k, v in payload.items() if k in EXTERNAL and 0 <= float(v) <= 30}
    await _save(db, FEES_KEY, clean)
    await db.commit()
    return {"fees": clean}
