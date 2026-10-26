"""Уведомления, статус и управление развёртываниями: admin and customer endpoints moved out of main.py (v28.28.0).

Names that belong to main are read through ``shop.<name>`` at call time, so tests and
operators that patch ``app.main`` keep affecting this code exactly as before."""
from .db import get_db
from .security import require_permission
from fastapi import Depends
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from . import main as shop

# ---------- Уведомления, статус и управление развёртываниями ----------
@shop.app.get("/api/me/notifications")
async def my_notifications(request:Request, unread_only:bool=False, db:AsyncSession=Depends(get_db)):
    user=await shop.user_from_token(request,db)
    q=shop.select(shop.Notification).where(shop.Notification.user_id==user.id)
    if unread_only: q=q.where(shop.Notification.read_at.is_(None))
    rows=(await db.execute(q.order_by(shop.Notification.id.desc()).limit(100))).scalars().all()
    return [{"id":n.id,"channel":n.channel,"kind":n.kind,"title":n.title,"body":n.body,"read":n.read_at is not None,"created_at":n.created_at} for n in rows]

@shop.app.post("/api/me/notifications/{notification_id}/read")
async def read_notification(notification_id:int,request:Request,db:AsyncSession=Depends(get_db)):
    user=await shop.user_from_token(request,db)
    row=(await db.execute(shop.select(shop.Notification).where(shop.Notification.id==notification_id,shop.Notification.user_id==user.id).with_for_update())).scalar_one_or_none()
    if not row: raise shop.HTTPException(404,"Уведомление не найдено")
    row.read_at=shop.datetime.utcnow(); await db.commit(); return {"ok":True}

@shop.app.get("/api/public/status")
async def public_status(db:AsyncSession=Depends(get_db)):
    rows=(await db.execute(shop.select(shop.StatusComponent).where(shop.StatusComponent.enabled==True).order_by(shop.StatusComponent.sort_order,shop.StatusComponent.id))).scalars().all()
    return {"version":shop.APP_VERSION,"overall":("unknown" if not rows else "operational" if all(x.status=="operational" for x in rows) else "degraded"),"components":[{"slug":x.slug,"name":x.name,"status":x.status,"message":x.message,"updated_at":x.updated_at} for x in rows]}

@shop.app.get("/api/admin/notifications")
async def admin_notifications(db:AsyncSession=Depends(get_db),admin=Depends(require_permission("read"))):
    rows=(await db.execute(shop.select(shop.Notification).order_by(shop.Notification.id.desc()).limit(200))).scalars().all()
    return [{"id":n.id,"user_id":n.user_id,"channel":n.channel,"kind":n.kind,"title":n.title,"status":n.status,"attempts":n.attempts,"created_at":n.created_at,"sent_at":n.sent_at} for n in rows]

@shop.app.post("/api/admin/notifications")
async def admin_notification_create(payload:shop.NotificationIn,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("manage_content"))):
    if not await db.get(shop.User,payload.user_id): raise shop.HTTPException(404,"Пользователь не найден")
    row=await shop.enqueue_notification(db,**payload.model_dump()); await shop.audit(db,"notification.created",admin.email,str(row.id),payload.model_dump()); await db.commit()
    return {"id":row.id,"status":row.status}

@shop.app.get("/api/admin/status/components")
async def admin_status_components(db:AsyncSession=Depends(get_db),admin=Depends(require_permission("ops.diagnostics"))):
    rows=(await db.execute(shop.select(shop.StatusComponent).order_by(shop.StatusComponent.sort_order,shop.StatusComponent.id))).scalars().all()
    return [{"id":x.id,"slug":x.slug,"name":x.name,"status":x.status,"message":x.message,"enabled":x.enabled,"sort_order":x.sort_order} for x in rows]

@shop.app.post("/api/admin/status/components")
async def admin_status_component_create(payload:shop.StatusComponentIn,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("ops.diagnostics"))):
    if await db.scalar(shop.select(shop.StatusComponent).where(shop.StatusComponent.slug==payload.slug)): raise shop.HTTPException(409,"Компонент уже существует")
    row=shop.StatusComponent(**payload.model_dump()); db.add(row); await shop.audit(db,"status.component.created",admin.email,payload.slug); await db.commit(); await db.refresh(row); return {"id":row.id,"status":row.status}

@shop.app.put("/api/admin/status/components/{component_id}")
async def admin_status_component_update(component_id:int,payload:shop.StatusComponentIn,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("ops.diagnostics"))):
    row=await db.get(shop.StatusComponent,component_id)
    if not row: raise shop.HTTPException(404,"Компонент не найден")
    duplicate=await db.scalar(shop.select(shop.StatusComponent).where(shop.StatusComponent.slug==payload.slug,shop.StatusComponent.id!=component_id))
    if duplicate: raise shop.HTTPException(409,"Slug уже занят")
    for k,v in payload.model_dump().items(): setattr(row,k,v)
    row.updated_at=shop.datetime.utcnow(); await shop.audit(db,"status.component.updated",admin.email,str(row.id),payload.model_dump()); await db.commit(); return {"ok":True}

@shop.app.post("/api/admin/deployments")
async def deployment_create(payload:shop.DeploymentIn,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("ops.releases"))):
    active=await db.scalar(shop.select(shop.Deployment).where(shop.Deployment.status.in_({"planned","canary","promoted"})).order_by(shop.Deployment.id.desc()))
    if active: raise shop.HTTPException(409,"Уже существует активное развёртывание")
    row=shop.Deployment(version=payload.version,previous_version=payload.previous_version,strategy=payload.strategy,traffic_percent=payload.traffic_percent,status="canary" if payload.traffic_percent else "planned")
    db.add(row); await shop.audit(db,"deployment.created",admin.email,str(row.version),payload.model_dump()); await db.commit(); await db.refresh(row); return {"id":row.id,"status":row.status,"traffic_percent":row.traffic_percent}

@shop.app.post("/api/admin/deployments/{deployment_id}/promote")
async def deployment_promote(deployment_id:int,payload:shop.DeploymentPromoteIn,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("ops.releases"))):
    row=(await db.execute(shop.select(shop.Deployment).where(shop.Deployment.id==deployment_id).with_for_update())).scalar_one_or_none()
    if not row: raise shop.HTTPException(404,"Развёртывание не найдено")
    if row.status in {"rolled_back","completed"}: raise shop.HTTPException(409,"Развёртывание уже завершено")
    if payload.error_rate_percent >= shop.Decimal("5") and payload.traffic_percent > row.traffic_percent: raise shop.HTTPException(409,"Нельзя повышать трафик при error rate >= 5%")
    row.traffic_percent=payload.traffic_percent; row.error_rate_percent=payload.error_rate_percent; row.status="completed" if payload.traffic_percent==100 else "promoted" if payload.traffic_percent>0 else "planned"; row.updated_at=shop.datetime.utcnow()
    if row.status=="completed": row.completed_at=shop.datetime.utcnow()
    await shop.audit(db,"deployment.promoted",admin.email,str(row.id),payload.model_dump()); await db.commit(); return {"ok":True,"status":row.status,"traffic_percent":row.traffic_percent}

@shop.app.post("/api/admin/deployments/{deployment_id}/rollback")
async def deployment_rollback(deployment_id:int,payload:dict|None=None,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("ops.releases"))):
    row=(await db.execute(shop.select(shop.Deployment).where(shop.Deployment.id==deployment_id).with_for_update())).scalar_one_or_none()
    if not row: raise shop.HTTPException(404,"Развёртывание не найдено")
    if row.status=="completed": raise shop.HTTPException(409,"Завершённый релиз требует отдельного обратного релиза")
    row.status="rolled_back"; row.traffic_percent=0; row.rollback_reason=str((payload or {}).get("reason") or "Ручной откат")[:2000]; row.updated_at=shop.datetime.utcnow(); await shop.audit(db,"deployment.rollback",admin.email,str(row.id),{"reason":row.rollback_reason}); await db.commit(); return {"ok":True,"status":row.status}

@shop.app.get("/api/admin/deployments")
async def deployment_list(db:AsyncSession=Depends(get_db),admin=Depends(require_permission("ops.releases"))):
    rows=(await db.execute(shop.select(shop.Deployment).order_by(shop.Deployment.id.desc()).limit(100))).scalars().all()
    return [{"id":x.id,"version":x.version,"previous_version":x.previous_version,"strategy":x.strategy,"traffic_percent":x.traffic_percent,"status":x.status,"error_rate_percent":str(x.error_rate_percent),"rollback_reason":x.rollback_reason,"created_at":x.created_at,"completed_at":x.completed_at} for x in rows]


__all__ = ['admin_notification_create', 'admin_notifications', 'admin_status_component_create', 'admin_status_component_update', 'admin_status_components', 'deployment_create', 'deployment_list', 'deployment_promote', 'deployment_rollback', 'my_notifications', 'public_status', 'read_notification']
