"""Owner selection and immutable order binding for multiple subscriptions."""
from datetime import datetime
from fastapi import APIRouter,Depends,HTTPException,Request
from pydantic import BaseModel,Field
from sqlalchemy import select,func,update
from sqlalchemy.ext.asyncio import AsyncSession
from .sub_proxy import client_url
from .db import get_db
from .models import User,Subscription,Payment,Plan,UserDevice,GiftRedemption,EntitlementOperation
router=APIRouter()


def selection(payload):
    raw=payload.get('subscription_id')
    try:sub_id=int(raw) if raw not in (None,'') else None
    except (TypeError,ValueError):raise HTTPException(400,'Некорректная подписка')
    if isinstance(raw,bool) or (sub_id is not None and sub_id<=0):raise HTTPException(400,'Некорректная подписка')
    new=payload.get('new_subscription',False)
    if not isinstance(new,bool) or (new and sub_id is not None):raise HTTPException(400,'Выберите новую или существующую подписку')
    return sub_id,new


async def owned(db,user_id,subscription_id=None,lock=False):
    q=select(Subscription).where(Subscription.user_id==user_id)
    q=q.where(Subscription.id==subscription_id) if subscription_id is not None else q.where(Subscription.is_primary.is_(True))
    if lock:q=q.execution_options(populate_existing=True).with_for_update()
    return await db.scalar(q)


FAMILY_TARGET='Это семейная подписка: её продлевает владелец семьи. Купите для себя отдельную подписку.'


async def is_family_subscription(db,subscription_id):
    """A family member's subscription follows the owner's: it is never bought, renewed or changed directly."""
    from .models import FamilyMember
    return bool(subscription_id and await db.scalar(select(FamilyMember.id).where(FamilyMember.subscription_id==subscription_id).limit(1)))


async def reserve_target(db,user,plan_id,payload):
    sub_id,new=selection(payload)
    # This row lock serializes profile creation with wallet reservations and primary selection.
    user=await db.scalar(select(User).where(User.id==user.id).execution_options(populate_existing=True).with_for_update())
    if not user or user.deleted_at:raise HTTPException(409,'Аккаунт недоступен')
    primary=await owned(db,user.id,lock=True)
    sub=await owned(db,user.id,sub_id,lock=True) if sub_id is not None else primary
    if sub_id is not None and not sub:raise HTTPException(404,'Подписка не найдена')
    if sub is not None and not new and await is_family_subscription(db,sub.id):
        # Paid days on a family subscription would be overwritten by the owner's expiry on the next sync.
        if sub_id is not None:raise HTTPException(409,FAMILY_TARGET)
        new=True
    if new or sub is None:
        count=await db.scalar(select(func.count()).select_from(Subscription).where(Subscription.user_id==user.id))
        if count>=20:raise HTTPException(409,'Достигнут лимит 20 подписок')
        sub=Subscription(user_id=user.id,plan_id=plan_id,is_primary=primary is None,lifecycle_status='pending',name='Подписка',expires_at=None)
        db.add(sub);await db.flush()
        if primary is None:
            await db.execute(update(UserDevice).where(UserDevice.user_id==user.id,UserDevice.subscription_id.is_(None)).values(subscription_id=sub.id))
    await ensure_no_pending_purchase(db,sub.id)
    return sub


async def ensure_no_pending_gift(db,subscription_id):
    pending=await db.scalar(select(GiftRedemption.id).where(GiftRedemption.subscription_id==subscription_id,GiftRedemption.status!='completed').limit(1))
    if pending:raise HTTPException(409,'Завершите активацию ранее принятого подарка')


async def ensure_no_pending_purchase(db,subscription_id):
    """Call under the owner row lock before accepting a new entitlement purchase.

    A paid grant or uncertain absolute remote update must settle before another
    purchase can freeze terms for the same profile. Other profiles stay available.
    Existing idempotent retries are resolved before this check by each caller.
    """
    if await is_family_subscription(db,subscription_id):raise HTTPException(409,FAMILY_TARGET)
    await ensure_no_pending_gift(db,subscription_id)
    operation=await db.scalar(select(EntitlementOperation.id).where(
        EntitlementOperation.subscription_id==subscription_id,
        EntitlementOperation.status.in_(('queued','applying','refund_pending'))).limit(1))
    payment=await db.scalar(select(Payment.id).where(
        Payment.subscription_id==subscription_id,
        Payment.status.in_(('paid','fulfilled')),
        Payment.fulfillment_status!='completed').limit(1))
    if operation or payment:raise HTTPException(409,'Предыдущая покупка ещё обрабатывается')


async def pending_absolute_write(db,subscription_id):
    """Owner row must be locked. Late invoice grants wait for frozen writes."""
    gift=await db.scalar(select(GiftRedemption.id).where(GiftRedemption.subscription_id==subscription_id,
        GiftRedemption.status!='completed').limit(1))
    operation=await db.scalar(select(EntitlementOperation.id).where(EntitlementOperation.subscription_id==subscription_id,
        EntitlementOperation.status.in_(('queued','applying','refund_pending'))).limit(1))
    return bool(gift or operation)


async def renewal_terms(db,sub,plan):
    """Keep constructor choices; never guess a legacy changed constructor's price."""
    if sub.renewal_terms:
        return dict(sub.renewal_terms)
    from .tariff_api import linked_constructor_id
    if not await linked_constructor_id(db,plan.id):
        from .config import settings
        return {'amount':str(plan.price),'days':plan.duration_days,'traffic_gb':plan.traffic_limit_gb,
                'devices':plan.device_limit,'profile_id':plan.remnawave_profile_id,'currency':settings.default_currency}
    grant=await db.scalar(select(Payment).where(Payment.subscription_id==sub.id,Payment.plan_id==sub.plan_id,
        Payment.purpose=='subscription',Payment.fulfillment_status=='completed',Payment.status.in_(('paid','fulfilled')),
        Payment.duration_days_snapshot.is_not(None)).order_by(Payment.id.desc()).limit(1))
    if not grant:return None
    from decimal import Decimal
    total_days=int(grant.duration_days_snapshot)+int(grant.bonus_days or 0)
    if total_days<=0 or sub.unit_price_per_day is None or abs(Decimal(sub.unit_price_per_day)-Decimal(grant.amount)/total_days)>Decimal('0.00000002'):
        return None
    return {'amount':str(grant.original_amount if grant.original_amount is not None else grant.amount),
            'days':grant.duration_days_snapshot,'traffic_gb':grant.traffic_limit_gb_snapshot,
            'devices':grant.device_limit_snapshot,'profile_id':grant.remnawave_profile_id_snapshot,'currency':grant.currency}


def check_retry(payment,payload):
    sub_id,new=selection(payload)
    if bool(payment.new_subscription)!=new or (sub_id is not None and payment.subscription_id!=sub_id):
        raise HTTPException(409,'Ключ уже использован для другой подписки')


async def payment_target(db,payment,lock=False):
    sub=await owned(db,payment.user_id,payment.subscription_id,lock=lock)
    if payment.subscription_id is not None and not sub:raise RuntimeError('Payment subscription is missing or belongs to another owner')
    # Legacy orders created before the migration keep the pre-existing primary target.
    if sub and payment.subscription_id is None:payment.subscription_id=sub.id
    return sub


def remote_username(user_id,sub):
    # Pending independent profiles must never recover another profile's remote account.
    return f'user_{user_id}_sub_{sub.id}' if sub and sub.lifecycle_status=='pending' else f'user_{user_id}'


def output(sub,plan=None):
    return {'id':sub.id,'name':sub.name,'is_primary':sub.is_primary,'plan_id':sub.plan_id,
            'plan':plan.name if plan else None,'status':sub.lifecycle_status,'expires_at':sub.expires_at,
            'traffic_gb':sub.traffic_limit_gb_snapshot,'devices':sub.device_limit_snapshot,
            'subscription_url':client_url(sub.subscription_url),'auto_renew_enabled':sub.auto_renew_enabled}


async def user(request,db):
    from .main import user_from_token
    from .platform_api import reject_restricted
    owner=await user_from_token(request,db);reject_restricted(owner);return owner


@router.get('/api/me/subscriptions')
async def list_subscriptions(request:Request,db:AsyncSession=Depends(get_db)):
    owner=await user(request,db)
    rows=(await db.execute(select(Subscription,Plan).outerjoin(Plan,Subscription.plan_id==Plan.id)
        .where(Subscription.user_id==owner.id).order_by(Subscription.is_primary.desc(),Subscription.id))).all()
    return [output(sub,plan) for sub,plan in rows]


@router.post('/api/me/subscriptions/{subscription_id}/select')
async def select_subscription(subscription_id:int,request:Request,db:AsyncSession=Depends(get_db)):
    from .main import audit
    owner=await user(request,db)
    current=await db.scalar(select(User).where(User.id==owner.id).execution_options(populate_existing=True).with_for_update())
    if not current or current.deleted_at:raise HTTPException(409,'Аккаунт недоступен')
    sub=await owned(db,owner.id,subscription_id,lock=True)
    if not sub:raise HTTPException(404,'Подписка не найдена')
    # Clear first, then flush the new primary to respect the partial unique index.
    await db.execute(update(Subscription).where(Subscription.user_id==owner.id,Subscription.is_primary.is_(True)).values(is_primary=False))
    sub.is_primary=True
    await audit(db,'subscription.selected',f'user:{owner.id}',str(sub.id));await db.commit()
    return output(sub)


class RenameIn(BaseModel):
    name:str=Field(min_length=1,max_length=80)


@router.put('/api/me/subscriptions/{subscription_id}')
async def rename_subscription(subscription_id:int,payload:RenameIn,request:Request,db:AsyncSession=Depends(get_db)):
    from .main import audit
    owner=await user(request,db)
    current=await db.scalar(select(User).where(User.id==owner.id).execution_options(populate_existing=True).with_for_update())
    if not current or current.deleted_at:raise HTTPException(409,'Аккаунт недоступен')
    sub=await owned(db,owner.id,subscription_id,lock=True)
    if not sub:raise HTTPException(404,'Подписка не найдена')
    if not payload.name.strip():raise HTTPException(400,'Укажите название')
    sub.name=payload.name.strip();await audit(db,'subscription.renamed',f'user:{owner.id}',str(sub.id));await db.commit()
    return output(sub)
