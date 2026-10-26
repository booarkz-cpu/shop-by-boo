"""Marketing / promotions / broadcasts: admin and customer endpoints moved out of main.py (v28.28.0).

Names that belong to main are read through ``shop.<name>`` at call time, so tests and
operators that patch ``app.main`` keep affecting this code exactly as before."""
from .db import get_db
from .security import require_permission
from datetime import datetime
from decimal import Decimal
from fastapi import Depends
from pydantic import BaseModel
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from . import main as shop

# ---------- Marketing / promotions / broadcasts ----------
class PromotionIn(BaseModel):
    name:str=Field(min_length=1,max_length=255); kind:str="percent"; value:Decimal=Field(gt=0,le=1000000,decimal_places=2,max_digits=12); plan_ids:list[int]|None=None; starts_at:datetime|None=None; ends_at:datetime|None=None; enabled:bool=True; description:str=""; priority:int=Field(default=0,ge=-100000,le=100000); exclusive:bool=True
class PromoCodeIn(BaseModel):
    code:str=Field(min_length=2,max_length=64); kind:str="percent"; value:Decimal=Field(gt=0,le=1000000,decimal_places=2,max_digits=12); plan_ids:list[int]|None=None; starts_at:datetime|None=None; ends_at:datetime|None=None; usage_limit:int|None=Field(default=None,ge=1); enabled:bool=True; first_purchase_only:bool=False; max_uses_per_user:int|None=Field(default=None,ge=1); min_amount:Decimal|None=Field(default=None,ge=0,decimal_places=2,max_digits=12); referral_only:bool=False
class AdIn(BaseModel):
    title:str=Field(min_length=1,max_length=255); text:str=""; image_url:str|None=None; button_text:str|None=None; button_url:str|None=None; starts_at:datetime|None=None; ends_at:datetime|None=None; enabled:bool=True; sort_order:int=0
class BroadcastIn(BaseModel):
    text:str=Field(min_length=1,max_length=4000); image_url:str|None=None; button_text:str|None=Field(default=None,max_length=100); button_url:str|None=None; target:str="all"

@shop.app.get("/api/admin/marketing")
async def admin_marketing(db:AsyncSession=Depends(get_db),admin=Depends(require_permission("read"))):
    ps=(await db.execute(shop.select(shop.Promotion).order_by(shop.Promotion.id.desc()))).scalars().all(); cs=(await db.execute(shop.select(shop.PromoCode).order_by(shop.PromoCode.id.desc()))).scalars().all(); ads=(await db.execute(shop.select(shop.Advertisement).order_by(shop.Advertisement.sort_order,shop.Advertisement.id))).scalars().all(); bs=(await db.execute(shop.select(shop.Broadcast).order_by(shop.Broadcast.id.desc()).limit(100))).scalars().all()
    return {"promotions":[{"id":x.id,"name":x.name,"kind":x.kind,"value":float(x.value),"plan_ids":x.plan_ids,"starts_at":x.starts_at,"ends_at":x.ends_at,"enabled":x.enabled,"description":x.description,"priority":x.priority,"exclusive":x.exclusive} for x in ps],"promo_codes":[{"id":x.id,"code":x.code,"kind":x.kind,"value":float(x.value),"plan_ids":x.plan_ids,"starts_at":x.starts_at,"ends_at":x.ends_at,"usage_limit":x.usage_limit,"used_count":x.used_count,"enabled":x.enabled} for x in cs],"advertisements":[{"id":x.id,"title":x.title,"text":x.text,"image_url":x.image_url,"button_text":x.button_text,"button_url":x.button_url,"starts_at":x.starts_at,"ends_at":x.ends_at,"enabled":x.enabled,"sort_order":x.sort_order} for x in ads],"broadcasts":[{"id":x.id,"text":x.text,"status":x.status,"target":x.target,"sent_count":x.sent_count,"failed_count":x.failed_count,"created_at":x.created_at,"finished_at":x.finished_at} for x in bs]}

@shop.app.post("/api/admin/promotions")
async def create_promotion(payload:PromotionIn,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("manage_marketing"))):
    if payload.kind not in {"percent","fixed"}: raise shop.HTTPException(400,"kind must be percent or fixed")
    if payload.kind=="percent" and payload.value>100: raise shop.HTTPException(400,"Percent discount cannot exceed 100")
    if payload.kind=="fixed" and payload.value<=0: raise shop.HTTPException(400,"Invalid discount")
    x=shop.Promotion(**payload.model_dump()); db.add(x); await shop.audit(db,"marketing.promotion.created",admin.email); await db.commit(); return {"ok":True}
@shop.app.put("/api/admin/promotions/{item_id}")
async def update_promotion(item_id:int,payload:PromotionIn,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("manage_marketing"))):
    x=await db.get(shop.Promotion,item_id)
    if not x: raise shop.HTTPException(404,"Promotion not found")
    for k,v in payload.model_dump().items(): setattr(x,k,v)
    await db.commit(); return {"ok":True}
@shop.app.delete("/api/admin/promotions/{item_id}")
async def delete_promotion(item_id:int,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("manage_marketing"))):
    x=await db.get(shop.Promotion,item_id);
    if not x: raise shop.HTTPException(404,"Promotion not found")
    await db.delete(x); await db.commit(); return {"ok":True}

@shop.app.post("/api/admin/promo-codes")
async def create_promo_code(payload:PromoCodeIn,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("manage_marketing"))):
    if payload.kind not in {"percent","fixed"}: raise shop.HTTPException(400,"kind must be percent or fixed")
    if payload.kind=="percent" and payload.value>100: raise shop.HTTPException(400,"Percent discount cannot exceed 100")
    data=payload.model_dump(); data["code"]=payload.code.strip().upper(); x=shop.PromoCode(**data); db.add(x)
    try: await db.commit()
    except shop.IntegrityError: await db.rollback(); raise shop.HTTPException(409,"Promo code already exists")
    return {"ok":True}
@shop.app.put("/api/admin/promo-codes/{item_id}")
async def update_promo_code(item_id:int,payload:PromoCodeIn,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("manage_marketing"))):
    x=await db.get(shop.PromoCode,item_id);
    if not x: raise shop.HTTPException(404,"Promo code not found")
    data=payload.model_dump(); data["code"]=data["code"].strip().upper()
    for k,v in data.items(): setattr(x,k,v)
    await db.commit(); return {"ok":True}
@shop.app.delete("/api/admin/promo-codes/{item_id}")
async def delete_promo_code(item_id:int,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("manage_marketing"))):
    x=await db.get(shop.PromoCode,item_id);
    if not x: raise shop.HTTPException(404,"Promo code not found")
    from .models import PromoAudience
    if await db.get(PromoAudience,item_id):raise shop.HTTPException(409,"Отключите промокод и оффер вместо удаления истории аудитории")
    await db.delete(x); await db.commit(); return {"ok":True}

@shop.app.post("/api/admin/advertisements")
async def create_ad(payload:AdIn,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("manage_marketing"))):
    shop.validate_public_url(payload.button_url)
    shop.validate_public_url(payload.image_url)
    x=shop.Advertisement(**payload.model_dump()); db.add(x); await db.commit(); return {"ok":True}
@shop.app.put("/api/admin/advertisements/{item_id}")
async def update_ad(item_id:int,payload:AdIn,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("manage_marketing"))):
    x=await db.get(shop.Advertisement,item_id);
    if not x: raise shop.HTTPException(404,"Advertisement not found")
    shop.validate_public_url(payload.button_url); shop.validate_public_url(payload.image_url)
    for k,v in payload.model_dump().items(): setattr(x,k,v)
    await db.commit(); return {"ok":True}
@shop.app.delete("/api/admin/advertisements/{item_id}")
async def delete_ad(item_id:int,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("manage_marketing"))):
    x=await db.get(shop.Advertisement,item_id);
    if not x: raise shop.HTTPException(404,"Advertisement not found")
    await db.delete(x); await db.commit(); return {"ok":True}

@shop.app.post("/api/admin/broadcasts")
async def create_broadcast(payload:BroadcastIn,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("manage_broadcasts"))):
    if not shop.settings.bot_token: raise shop.HTTPException(503,"BOT_TOKEN is not configured")
    if payload.target not in {"all","active","inactive"}: raise shop.HTTPException(400,"Unsupported target")
    data=payload.model_dump()
    for key in ("image_url","button_text","button_url"):
        if data.get(key)=="": data[key]=None
    if bool(data.get("button_text")) != bool(data.get("button_url")): raise shop.HTTPException(400,"Button text and URL are set together")
    if data.get("image_url") and len(payload.text)>1024: raise shop.HTTPException(400,"Caption is longer than 1024 characters")
    shop.validate_public_url(data.get("button_url")); shop.validate_public_url(data.get("image_url"))
    x=shop.Broadcast(**data); db.add(x); await shop.audit(db,"marketing.broadcast.queued",admin.email,str(payload.target)); await db.commit(); await db.refresh(x); return {"id":x.id,"status":"queued"}

@shop.app.post("/api/admin/broadcasts/{broadcast_id}/retry")
async def retry_broadcast(broadcast_id:int,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("manage_broadcasts"))):
    if not shop.settings.bot_token: raise shop.HTTPException(503,"BOT_TOKEN is not configured")
    x=await db.get(shop.Broadcast,broadcast_id)
    if not x: raise shop.HTTPException(404,"Broadcast not found")
    if x.status not in {"sending","failed"}: raise shop.HTTPException(409,"Broadcast is not waiting for a retry")
    x.status="queued"; x.finished_at=None
    await shop.audit(db,"marketing.broadcast.retried",admin.email,str(x.id),{"sent_count":x.sent_count,"failed_count":x.failed_count})
    await db.commit(); return {"id":x.id,"status":"queued","sent_count":x.sent_count,"failed_count":x.failed_count}

async def monitor_checks_scheduler():
    while True:
        try:
            async with shop.AsyncSession(shop.engine, expire_on_commit=False) as db:
                now=shop.datetime.utcnow(); rows=(await db.execute(shop.select(shop.MonitoringCheck).where(shop.MonitoringCheck.enabled.is_(True)))).scalars().all()
                for x in rows:
                    if x.last_checked_at and (now-x.last_checked_at).total_seconds() < x.interval_seconds: continue
                    started=shop.asyncio.get_running_loop().time()
                    try:
                        shop.validate_public_url(x.url, allow_empty=False)
                        async with shop._pinned_public_http_client(x.timeout_seconds) as c:
                            r=await c.request(x.method,x.url)
                        x.last_status="ok" if 200<=r.status_code<400 else "degraded"; x.last_error=None if x.last_status=="ok" else f"HTTP {r.status_code}"
                        x.last_latency_ms=round((shop.asyncio.get_running_loop().time()-started)*1000); x.failure_streak=0 if x.last_status=="ok" else x.failure_streak+1
                    except Exception as exc:
                        x.last_status="down"; x.last_error=str(exc)[:500]; x.last_latency_ms=round((shop.asyncio.get_running_loop().time()-started)*1000); x.failure_streak+=1
                    x.last_checked_at=shop.datetime.utcnow()
                    if x.failure_streak in {1,3,5}: await shop.audit(db,"monitoring.alert","system",str(x.id),{"name":x.name,"status":x.last_status,"error":x.last_error})
                await db.commit()
        except Exception: shop.logger.exception("monitoring scheduler failure")
        await shop.asyncio.sleep(15)


__all__ = ['AdIn', 'BroadcastIn', 'PromoCodeIn', 'PromotionIn', 'admin_marketing', 'create_ad', 'create_broadcast', 'create_promo_code', 'create_promotion', 'delete_ad', 'delete_promo_code', 'delete_promotion', 'monitor_checks_scheduler', 'retry_broadcast', 'update_ad', 'update_promo_code', 'update_promotion']
