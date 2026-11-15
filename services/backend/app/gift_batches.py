"""Gift code batches: N one-time gift codes for a plan (giveaways, partners, offline sales), downloadable as CSV with
ready links. A code is activated like any gift: bot ``/start GIFT_…`` (one tap), cabinet and Mini App «Подарки».
«Маркетинг → Пачки подарочных кодов» (web) and the mobile admin card.
"""
from __future__ import annotations

import csv
import io
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import require_permission

router = APIRouter()
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


class BatchIn(BaseModel):
    plan_id: int = Field(gt=0)
    count: int = Field(ge=1, le=5000)
    days: int | None = Field(None, ge=1, le=3650)  # None → the plan's own duration
    tag: str = Field(min_length=2, max_length=12, pattern=r"^[A-Z0-9]+$")
    valid_days: int = Field(90, ge=1, le=3650)


def links(code: str) -> tuple[str, str]:
    from .config import settings
    bot = f"https://t.me/{settings.bot_username}?start={code}" if settings.bot_username else ""
    cabinet = f"{(settings.cabinet_url or settings.mini_app_url or '').rstrip('/')}/?gift={code}"
    return bot, cabinet


@router.post("/api/admin/gift-batches")
async def create_batch(payload: BatchIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("manage_marketing"))):
    from .main import audit
    from .models import GiftCode, Plan
    plan = await db.get(Plan, payload.plan_id)
    if not plan:
        raise HTTPException(404, "Тариф не найден")
    prefix = f"GIFT_{payload.tag}_"
    existing = set((await db.execute(select(GiftCode.code).where(GiftCode.code.like(prefix + "%")))).scalars())
    expires = datetime.utcnow() + timedelta(days=payload.valid_days)
    codes = []
    while len(codes) < payload.count:
        code = prefix + "".join(secrets.choice(ALPHABET) for _ in range(10))
        if code not in existing:
            existing.add(code)
            codes.append(code)
            db.add(GiftCode(code=code, plan_id=plan.id, duration_days=payload.days or plan.duration_days, max_uses=1,
                            expires_at=expires, enabled=True))
    await audit(db, "marketing.gift_batch", admin.email, payload.tag, {"count": payload.count, "plan_id": plan.id})
    await db.commit()
    return {"tag": payload.tag, "count": len(codes), "codes": codes[:20]}


@router.get("/api/admin/gift-batches")
async def list_batches(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("marketing.read"))):
    from .models import GiftCode
    rows = (await db.execute(select(GiftCode.code, GiftCode.used_count, GiftCode.plan_id, GiftCode.expires_at, GiftCode.created_at)
                             .where(GiftCode.code.like("GIFT\\_%\\_%", escape="\\"), GiftCode.purchaser_user_id.is_(None)))).all()
    batches: dict[str, dict] = {}
    for code, used, plan_id, expires, created in rows:
        parts = code.split("_")
        if len(parts) < 3:
            continue
        b = batches.setdefault(parts[1], {"tag": parts[1], "plan_id": plan_id, "count": 0, "used": 0,
                                         "expires_at": expires.isoformat() if expires else None, "created_at": created.isoformat()})
        b["count"] += 1
        b["used"] += 1 if used else 0
    return {"batches": sorted(batches.values(), key=lambda b: b["created_at"], reverse=True)}


@router.get("/api/admin/gift-batches/{tag}.csv")
async def export_batch(tag: str, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("marketing.read"))):
    from .models import GiftCode
    if not tag.isalnum():
        raise HTTPException(400, "Bad tag")
    rows = (await db.execute(select(GiftCode).where(GiftCode.code.like(f"GIFT\\_{tag}\\_%", escape="\\")).order_by(GiftCode.id))).scalars().all()
    if not rows:
        raise HTTPException(404, "Пачка не найдена")
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["code", "days", "used", "expires_at", "bot_link", "cabinet_link"])
    for g in rows:
        bot, cabinet = links(g.code)
        writer.writerow([g.code, g.duration_days or "", g.used_count, g.expires_at.isoformat() if g.expires_at else "", bot, cabinet])
    return Response(out.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="gifts-{tag}.csv"', "Cache-Control": "private, no-store"})


@router.delete("/api/admin/gift-batches/{tag}")
async def disable_batch(tag: str, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("manage_marketing"))):
    """Switch off the unused codes of a batch (used ones stay in history)."""
    from sqlalchemy import update

    from .main import audit
    from .models import GiftCode
    result = await db.execute(update(GiftCode).where(GiftCode.code.like(f"GIFT\\_{tag}\\_%", escape="\\"), GiftCode.used_count == 0)
                              .values(enabled=False))
    await audit(db, "marketing.gift_batch.disabled", admin.email, tag, {"codes": result.rowcount})
    await db.commit()
    return {"disabled": result.rowcount}


async def stats(db: AsyncSession) -> dict:
    from .models import GiftCode
    total = await db.scalar(select(func.count()).select_from(GiftCode).where(GiftCode.code.like("GIFT\\_%\\_%", escape="\\")))
    return {"codes": int(total or 0)}
