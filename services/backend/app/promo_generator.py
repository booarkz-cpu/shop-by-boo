"""Promo code generator: a batch of random one-off (or limited) codes with the same terms, downloadable as CSV.
«Маркетинг → Генератор промокодов»."""
from __future__ import annotations

import csv
import io
import secrets
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .models import PromoCode
from .security import require_permission

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I: codes are typed by hand
router = APIRouter()


class GenerateIn(BaseModel):
    count: int = Field(ge=1, le=1000)
    prefix: str = Field(default="", max_length=16, pattern=r"^[A-Za-z0-9_-]*$")
    length: int = Field(default=8, ge=6, le=24)
    kind: str = Field(default="percent", pattern="^(percent|fixed)$")
    value: Decimal = Field(gt=0, le=1000000, decimal_places=2, max_digits=12)
    usage_limit: int = Field(default=1, ge=1, le=100000)
    max_uses_per_user: int | None = Field(default=1, ge=1)
    ends_at: datetime | None = None
    plan_ids: list[int] | None = None
    first_purchase_only: bool = False


def make_code(prefix: str, length: int) -> str:
    body = "".join(secrets.choice(ALPHABET) for _ in range(length))
    return f"{prefix.upper()}-{body}" if prefix else body


@router.post("/api/admin/promo-codes/generate")
async def generate_promo_codes(payload: GenerateIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("manage_marketing"))):
    from .main import audit
    if payload.kind == "percent" and payload.value > 100:
        raise HTTPException(400, "Скидка в процентах не больше 100")
    existing = set((await db.execute(select(PromoCode.code).where(PromoCode.code.like(f"{payload.prefix.upper()}%")))).scalars())
    codes: list[str] = []
    while len(codes) < payload.count:
        code = make_code(payload.prefix, payload.length)
        if code not in existing:
            existing.add(code)
            codes.append(code)
    for code in codes:
        db.add(PromoCode(code=code, kind=payload.kind, value=payload.value, usage_limit=payload.usage_limit,
                         max_uses_per_user=payload.max_uses_per_user, ends_at=payload.ends_at, plan_ids=payload.plan_ids,
                         first_purchase_only=payload.first_purchase_only, enabled=True))
    await audit(db, "marketing.promo_codes.generated", admin.email, payload.prefix or None,
                {"count": payload.count, "kind": payload.kind, "value": str(payload.value)})
    await db.commit()
    return {"count": len(codes), "codes": codes}


@router.get("/api/admin/promo-codes/export.csv")
async def export_promo_codes(prefix: str = "", db: AsyncSession = Depends(get_db), admin=Depends(require_permission("marketing.read"))):
    query = select(PromoCode).order_by(PromoCode.id)
    if prefix:
        query = query.where(PromoCode.code.like(f"{prefix.upper()}-%"))
    rows = (await db.execute(query)).scalars().all()
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["code", "kind", "value", "used", "limit", "ends_at", "enabled"])
    for x in rows:
        writer.writerow([x.code, x.kind, str(x.value), x.used_count, x.usage_limit or "", x.ends_at.isoformat() if x.ends_at else "", int(x.enabled)])
    return Response(out.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="promo-codes.csv"', "Cache-Control": "private, no-store"})
