"""Targeted promo audiences; the existing checkout owns price snapshots and quotas."""
from datetime import datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter,Depends,HTTPException,Query,Request,Response
from pydantic import BaseModel,ConfigDict,Field,model_validator
from sqlalchemy import select,delete,func
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .models import PromoReservation,PromoRedemption,AuditLog,PromoCode,PromoAudience,PromoGroup,PromoGroupMember,User,Subscription,Payment
from .security import require_permission


def private(response:Response):response.headers['Cache-Control']='private, no-store'
router=APIRouter(dependencies=[Depends(private)])


class GroupIn(BaseModel):
    model_config=ConfigDict(extra='forbid')
    name:str=Field(min_length=1,max_length=200)
    segment:Literal['manual','new','active','expired','referred']='manual'
    user_ids:list[int]=Field(default_factory=list,max_length=1000)
    enabled:bool=True
    version:int|None=Field(default=None,ge=1)

    @model_validator(mode='after')
    def validate_group(self):
        if not self.name.strip() or len(set(self.user_ids))!=len(self.user_ids) or any(x<=0 for x in self.user_ids):raise ValueError('Укажите название и разные положительные ID')
        if self.segment!='manual' and self.user_ids:raise ValueError('Динамическая группа не содержит ручных ID')
        return self


class AudienceIn(BaseModel):
    model_config=ConfigDict(extra='forbid')
    title:str=Field(min_length=1,max_length=200)
    description:str=Field(default='',max_length=2000)
    group_id:int|None=Field(default=None,gt=0)
    user_ids:list[int]=Field(default_factory=list,max_length=1000)
    version:int=Field(ge=0)
    enabled:bool=True

    @model_validator(mode='after')
    def scope(self):
        if bool(self.group_id)==bool(self.user_ids):raise ValueError('Выберите группу или персональные ID')
        if not self.title.strip() or len(set(self.user_ids))!=len(self.user_ids) or any(x<=0 for x in self.user_ids):raise ValueError('Проверьте название и ID')
        return self


class NewOfferIn(AudienceIn):
    code:str=Field(pattern=r'^[A-Z0-9_-]{2,64}$')
    kind:Literal['percent','fixed']='percent'
    value:Decimal=Field(gt=0,le=1000000,max_digits=12,decimal_places=2)
    max_uses_per_user:int=Field(default=1,ge=1,le=1000)

    @model_validator(mode='after')
    def discount(self):
        if self.version!=0:raise ValueError('Версия нового предложения равна 0')
        if self.kind=='percent' and self.value>100:raise ValueError('Скидка не больше 100%')
        return self


async def validate_users(db,ids):
    if not ids:return
    count=await db.scalar(select(func.count(User.id)).where(User.id.in_(ids),User.deleted_at.is_(None)))
    if count!=len(ids):raise HTTPException(409,'Один из клиентов удалён или не существует')


def group_json(group,members):return {'id':group.id,'name':group.name,'segment':group.segment,'enabled':group.enabled,'version':group.version,'user_ids':members}
def audience_json(row):return {'promo_id':row.promo_id,'title':row.title,'description':row.description,'group_id':row.group_id,'user_ids':row.user_ids,'version':row.version,'enabled':row.enabled}


@router.get('/api/admin/promo-groups')
async def groups(offset:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=100),db:AsyncSession=Depends(get_db),admin=Depends(require_permission('manage_marketing'))):
    rows=(await db.scalars(select(PromoGroup).order_by(PromoGroup.id.desc()).offset(offset).limit(limit))).all()
    members=(await db.execute(select(PromoGroupMember.group_id,PromoGroupMember.user_id).where(PromoGroupMember.group_id.in_([g.id for g in rows])).order_by(PromoGroupMember.user_id))).all()
    return [group_json(g,[uid for gid,uid in members if gid==g.id]) for g in rows]


async def save_group(db,body,admin,group=None):
    await validate_users(db,body.user_ids)
    if group:
        if group.version!=body.version:raise HTTPException(409,'Группа изменена; обновите список')
        group.version+=1;group.name=body.name;group.segment=body.segment;group.enabled=body.enabled
        await db.execute(delete(PromoGroupMember).where(PromoGroupMember.group_id==group.id))
    else:
        if body.version is not None:raise HTTPException(422,'При создании версия отсутствует')
        group=PromoGroup(name=body.name,segment=body.segment,enabled=body.enabled);db.add(group);await db.flush()
    db.add_all([PromoGroupMember(group_id=group.id,user_id=uid) for uid in sorted(body.user_ids)])
    db.add(AuditLog(actor=admin.email,action='marketing.group.saved',target=str(group.id),details=str(group.version)))
    await db.commit();return group_json(group,sorted(body.user_ids))


@router.post('/api/admin/promo-groups')
async def create_group(body:GroupIn,db:AsyncSession=Depends(get_db),admin=Depends(require_permission('manage_marketing'))):return await save_group(db,body,admin)


@router.put('/api/admin/promo-groups/{group_id}')
async def update_group(group_id:int,body:GroupIn,db:AsyncSession=Depends(get_db),admin=Depends(require_permission('manage_marketing'))):
    group=await db.scalar(select(PromoGroup).where(PromoGroup.id==group_id).execution_options(populate_existing=True).with_for_update())
    if not group:raise HTTPException(404,'Группа не найдена')
    return await save_group(db,body,admin,group)


@router.get('/api/admin/promo-audiences')
async def audiences(offset:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=100),db:AsyncSession=Depends(get_db),admin=Depends(require_permission('manage_marketing'))):
    return [audience_json(r) for r in (await db.scalars(select(PromoAudience).order_by(PromoAudience.promo_id.desc()).offset(offset).limit(limit))).all()]


@router.post('/api/admin/personal-offers')
async def create_offer(body:NewOfferIn,db:AsyncSession=Depends(get_db),admin=Depends(require_permission('manage_marketing'))):
    from sqlalchemy.exc import IntegrityError
    if body.group_id and not await db.get(PromoGroup,body.group_id):raise HTTPException(404,'Группа не найдена')
    await validate_users(db,body.user_ids)
    promo=PromoCode(code=body.code,kind=body.kind,value=body.value,enabled=True,max_uses_per_user=body.max_uses_per_user)
    db.add(promo)
    try:
        await db.flush()
        row=PromoAudience(promo_id=promo.id,title=body.title,description=body.description,group_id=body.group_id,
            user_ids=sorted(body.user_ids),version=1,enabled=body.enabled)
        db.add(row);db.add(AuditLog(actor=admin.email,action='marketing.offer.created',target=str(promo.id)))
        await db.commit()
    except IntegrityError:
        await db.rollback();raise HTTPException(409,'Промокод уже существует')
    return {**audience_json(row),'code':promo.code}


@router.put('/api/admin/promo-audiences/{promo_id}')
async def set_audience(promo_id:int,body:AudienceIn,db:AsyncSession=Depends(get_db),admin=Depends(require_permission('manage_marketing'))):
    promo=await db.scalar(select(PromoCode).where(PromoCode.id==promo_id).with_for_update())
    if not promo:raise HTTPException(404,'Промокод не найден')
    if body.group_id and not await db.get(PromoGroup,body.group_id):raise HTTPException(404,'Группа не найдена')
    await validate_users(db,body.user_ids)
    row=await db.scalar(select(PromoAudience).where(PromoAudience.promo_id==promo_id).execution_options(populate_existing=True))
    if (row.version if row else 0)!=body.version:raise HTTPException(409,'Оффер изменён; обновите список')
    if not row:row=PromoAudience(promo_id=promo_id,version=0);db.add(row)
    for key,value in body.model_dump(exclude={'version'}).items():setattr(row,key,value)
    row.version+=1;db.add(AuditLog(actor=admin.email,action='marketing.audience.saved',target=str(promo_id),details=str(row.version)))
    await db.commit();return audience_json(row)


async def audience_allowed(db,promo_id,user_id,lock=False):
    audience=await db.scalar(select(PromoAudience).where(PromoAudience.promo_id==promo_id).execution_options(populate_existing=True))
    if not audience:return True
    if not user_id or not audience.enabled:return False
    user=await db.get(User,user_id)
    if not user or user.deleted_at or user.restricted_at:return False
    if audience.group_id is None:return user_id in audience.user_ids
    query=select(PromoGroup).where(PromoGroup.id==audience.group_id).execution_options(populate_existing=True)
    if lock:query=query.with_for_update()
    group=await db.scalar(query)
    if not group or not group.enabled:return False
    if group.segment=='manual':return bool(await db.scalar(select(PromoGroupMember.user_id).where(PromoGroupMember.group_id==group.id,PromoGroupMember.user_id==user_id)))
    if group.segment=='referred':return user.referred_by_id is not None
    if group.segment=='new':return not bool(await db.scalar(select(Payment.id).where(Payment.user_id==user_id,Payment.status.in_(['paid','fulfilled','refunded'])).limit(1)))
    active=bool(await db.scalar(select(Subscription.id).where(Subscription.user_id==user_id,Subscription.lifecycle_status=='active',Subscription.expires_at>datetime.utcnow()).limit(1)))
    if group.segment=='active':return active
    return not active and bool(await db.scalar(select(Subscription.id).where(Subscription.user_id==user_id,Subscription.expires_at<=datetime.utcnow()).limit(1)))


@router.get('/api/me/offers')
async def offers(request:Request,offset:int=Query(0,ge=0),limit:int=Query(30,ge=1,le=100),db:AsyncSession=Depends(get_db)):
    from .main import user_from_token
    user=await user_from_token(request,db);now=datetime.utcnow()
    # A bounded scan has an explicit cursor even when an entire page is ineligible.
    candidates=(await db.execute(select(PromoCode,PromoAudience).join(PromoAudience,PromoAudience.promo_id==PromoCode.id)
        .where(PromoCode.enabled==True,PromoAudience.enabled==True).order_by(PromoCode.id.desc()).offset(offset).limit(limit))).all()
    result=[]
    for promo,audience in candidates:
        if promo.starts_at and promo.starts_at>now or promo.ends_at and promo.ends_at<=now:continue
        if promo.usage_limit is not None and promo.used_count+promo.reserved_count>=promo.usage_limit:continue
        if promo.first_purchase_only and await db.scalar(select(Payment.id).where(Payment.user_id==user.id,Payment.status.in_(['paid','fulfilled','refunded'])).limit(1)):continue
        if promo.max_uses_per_user is not None:
            used=int(await db.scalar(select(func.count(PromoRedemption.id)).where(PromoRedemption.promo_code_id==promo.id,PromoRedemption.user_id==user.id)) or 0)
            reserved=int(await db.scalar(select(func.count(PromoReservation.id)).where(PromoReservation.promo_code_id==promo.id,PromoReservation.user_id==user.id,PromoReservation.status=='reserved')) or 0)
            if used+reserved>=promo.max_uses_per_user:continue
        if await audience_allowed(db,promo.id,user.id):result.append({'code':promo.code,'title':audience.title,'description':audience.description,'kind':promo.kind,'value':str(promo.value),'plan_ids':promo.plan_ids,'ends_at':promo.ends_at})
    return {'items':result,'next_offset':offset+len(candidates) if len(candidates)==limit else None}
