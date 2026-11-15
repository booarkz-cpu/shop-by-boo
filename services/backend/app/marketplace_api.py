from __future__ import annotations
import hashlib, hmac, secrets
from datetime import datetime
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import get_db
from .models import Reseller, Plan, Promotion, User, Subscription, ReferralLedger, Payment
from .security import require_permission

router = APIRouter(prefix="/api", tags=["corgi-marketplace"])


def _key_hash(key: str) -> str:
    return hmac.new(settings.app_secret.encode(), key.encode(), hashlib.sha256).hexdigest()


class ResellerCreate(BaseModel):
    owner_user_id: int | None = Field(default=None, gt=0)
    name: str = Field(min_length=2, max_length=255)
    slug: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9-]+$")
    commission_percent: Decimal = Field(default=Decimal("20"), ge=0, le=100, max_digits=5, decimal_places=2)
    plan_ids: list[int] = Field(default_factory=list)
    branding: dict = Field(default_factory=dict)


class ResellerUpdate(BaseModel):
    owner_user_id: int | None = Field(default=None, gt=0)
    name: str | None = Field(default=None, min_length=2, max_length=255)
    commission_percent: Decimal | None = Field(default=None, ge=0, le=100, max_digits=5, decimal_places=2)
    plan_ids: list[int] | None = None
    branding: dict | None = None
    enabled: bool | None = None


async def _reseller_from_request(request: Request, db: AsyncSession) -> Reseller:
    raw = request.headers.get("Authorization", "")
    if not raw.startswith("Bearer "):
        raise HTTPException(401, "Reseller API key required")
    digest = _key_hash(raw[7:].strip())
    row = (await db.execute(select(Reseller).where(Reseller.api_key_hash == digest, Reseller.enabled.is_(True)))).scalar_one_or_none()
    if not row:
        raise HTTPException(401, "Invalid reseller API key")
    row.last_used_at = datetime.utcnow()
    await db.commit()
    return row


@router.get("/admin/marketplace/resellers")
async def list_resellers(admin=Depends(require_permission("referrals.read")), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Reseller).order_by(Reseller.id.desc()))).scalars().all()
    return [{"id": r.id, "owner_user_id": r.owner_user_id, "balance": str(r.balance), "name": r.name, "slug": r.slug, "commission_percent": str(r.commission_percent),
             "plan_ids": r.plan_ids or [], "branding": r.branding or {}, "enabled": r.enabled,
             "created_at": r.created_at.isoformat(), "last_used_at": r.last_used_at.isoformat() if r.last_used_at else None} for r in rows]


@router.post("/admin/marketplace/resellers")
async def create_reseller(payload: ResellerCreate, admin=Depends(require_permission("referrals.reconcile")), db: AsyncSession = Depends(get_db)):
    if payload.owner_user_id:
        user=await db.get(User,payload.owner_user_id)
        if not user or user.deleted_at or user.restricted_at:raise HTTPException(404,"Partner account unavailable")
        if await db.scalar(select(Reseller.id).where(Reseller.owner_user_id==user.id)):raise HTTPException(409,"Account already owns a partner portal")
    existing = await db.scalar(select(Reseller).where(Reseller.slug == payload.slug))
    if existing:
        raise HTTPException(409, "Reseller slug already exists")
    raw_key = "corgi_rsk_" + secrets.token_urlsafe(32)
    row = Reseller(owner_user_id=payload.owner_user_id, name=payload.name, slug=payload.slug, commission_percent=payload.commission_percent,
                   plan_ids=payload.plan_ids, branding=payload.branding, api_key_hash=_key_hash(raw_key), enabled=True)
    from .main import audit
    db.add(row)
    try:
        await db.flush()
        await audit(db,"partner.created",admin.email,str(row.id),{"owner_user_id":row.owner_user_id,"slug":row.slug,"percent":str(row.commission_percent)})
        await db.commit()
    except IntegrityError:
        await db.rollback();raise HTTPException(409,"Partner slug/account already exists")
    await db.refresh(row)
    return {"id": row.id, "name": row.name, "slug": row.slug, "api_key": raw_key,
            "commission_percent": str(row.commission_percent), "plan_ids": row.plan_ids or [], "branding": row.branding or {}}


@router.patch("/admin/marketplace/resellers/{reseller_id}")
async def update_reseller(reseller_id: int, payload: ResellerUpdate, admin=Depends(require_permission("referrals.reconcile")), db: AsyncSession = Depends(get_db)):
    row = await db.scalar(select(Reseller).where(Reseller.id==reseller_id).with_for_update().execution_options(populate_existing=True))
    if not row: raise HTTPException(404, "Reseller not found")
    changes=payload.model_dump(exclude_unset=True)
    if any(changes.get(key) is None for key in ("name","commission_percent","enabled") if key in changes):raise HTTPException(422,"Required fields cannot be null")
    if "owner_user_id" in changes and changes["owner_user_id"] != row.owner_user_id:
        from .models import PartnerCommission, PartnerWithdrawal
        if row.owner_user_id is not None or await db.scalar(select(PartnerCommission.id).where(PartnerCommission.reseller_id==row.id).limit(1)) or await db.scalar(select(PartnerWithdrawal.id).where(PartnerWithdrawal.reseller_id==row.id).limit(1)):
            raise HTTPException(409,"Existing owner or financial history cannot be reassigned")
        user=await db.get(User,changes["owner_user_id"]) if changes["owner_user_id"] else None
        if not user or user.deleted_at or user.restricted_at:raise HTTPException(404,"Partner account unavailable")
        if await db.scalar(select(Reseller.id).where(Reseller.owner_user_id==user.id)):raise HTTPException(409,"Account already owns a portal")
    for key, value in changes.items():setattr(row,key,value)
    from .main import audit
    await audit(db,"partner.updated",admin.email,str(row.id),{"fields":sorted(changes)})
    try:await db.commit()
    except IntegrityError:
        await db.rollback();raise HTTPException(409,"Partner account already assigned")
    return {"ok": True, "id": row.id}


@router.post("/admin/marketplace/resellers/{reseller_id}/rotate-key")
async def rotate_reseller_key(reseller_id: int, admin=Depends(require_permission("referrals.reconcile")), db: AsyncSession = Depends(get_db)):
    row = await db.scalar(select(Reseller).where(Reseller.id==reseller_id).with_for_update().execution_options(populate_existing=True))
    if not row: raise HTTPException(404, "Reseller not found")
    raw_key = "corgi_rsk_" + secrets.token_urlsafe(32)
    from .main import audit
    row.api_key_hash = _key_hash(raw_key)
    await audit(db,"partner.key_rotated",admin.email,str(row.id));await db.commit()
    return {"ok": True, "api_key": raw_key}


@router.get("/reseller/catalog")
async def reseller_catalog(request: Request, db: AsyncSession = Depends(get_db)):
    reseller = await _reseller_from_request(request, db)
    query = select(Plan).where(Plan.enabled.is_(True))
    if reseller.plan_ids:
        query = query.where(Plan.id.in_(reseller.plan_ids))
    plans = (await db.execute(query.order_by(Plan.id))).scalars().all()
    return {"reseller": {"slug": reseller.slug, "name": reseller.name, "branding": reseller.branding or {}},
            "plans": [{"id": p.id, "name": p.name, "price": str(p.price), "duration_days": p.duration_days,
                       "traffic_limit_gb": p.traffic_limit_gb, "device_limit": p.device_limit} for p in plans]}


@router.get("/reseller/stats")
async def reseller_stats(request: Request, db: AsyncSession = Depends(get_db)):
    reseller = await _reseller_from_request(request, db)
    from .models import PartnerCommission
    credited = await db.scalar(select(func.coalesce(func.sum(PartnerCommission.amount), 0)).where(PartnerCommission.reseller_id == reseller.id, PartnerCommission.status == "credited"))
    gross = await db.scalar(select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.reseller_id == reseller.id, Payment.status == "paid"))
    return {"reseller": reseller.slug, "gross_paid": str(gross or 0), "commission_credited": str(credited or 0), "available_balance": str(reseller.balance), "commission_percent": str(reseller.commission_percent)}


@router.get("/reseller/branding")
async def reseller_branding(request: Request, db: AsyncSession = Depends(get_db)):
    reseller = await _reseller_from_request(request, db)
    return {"name": reseller.name, "slug": reseller.slug, "branding": reseller.branding or {}}
