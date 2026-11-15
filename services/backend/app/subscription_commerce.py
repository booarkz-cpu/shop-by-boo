"""Quoted tariff changes and traffic purchases on the existing wallet/ledger."""
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_CEILING
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import get_db
from .models import (User, Plan, Payment, Subscription, TrafficPackage, EntitlementQuote,
                     EntitlementOperation, Job, Notification, UserDevice)
from .security import require_permission
from .remnawave import RemnawaveClient

router=APIRouter()
KINDS=("subscription_change","traffic_addon")
CENT=Decimal("0.01")


def entitlement_state(sub):
    return {"plan_id":sub.plan_id,"traffic_gb":sub.traffic_limit_gb_snapshot,
            "devices":sub.device_limit_snapshot,"profile":sub.remnawave_profile_id_snapshot,
            "expires_at":sub.expires_at.isoformat() if sub.expires_at else None,
            "unit_price":str(Decimal(sub.unit_price_per_day).quantize(Decimal("0.00000001"))) if sub.unit_price_per_day is not None else None,
            "renewal_terms":sub.renewal_terms}


def public_state(state):
    return {k:v for k,v in state.items() if k not in {"profile","renewal_terms"}}


def prorated_amount(old_rate,new_rate,remaining_seconds):
    if remaining_seconds<=0:raise HTTPException(409,"Подписка уже истекла")
    days=Decimal(str(remaining_seconds))/Decimal(86400)
    # A downgrade never turns previously purchased access into withdrawable cash.
    return max(Decimal(0),(new_rate-old_rate)*days).quantize(CENT,rounding=ROUND_CEILING)


async def _owner(request,db):
    from .main import user_from_token
    from .platform_api import reject_restricted
    user=await user_from_token(request,db);reject_restricted(user)
    return user


async def _subscription(db,user_id,subscription_id=None,lock=False):
    query=select(Subscription).where(Subscription.user_id==user_id)
    query=query.where(Subscription.id==subscription_id) if subscription_id is not None else query.where(Subscription.is_primary.is_(True))
    if lock:query=query.execution_options(populate_existing=True).with_for_update()
    sub=await db.scalar(query)
    if not sub:raise HTTPException(404,"Подписка не найдена")
    if not sub.expires_at or sub.expires_at<=datetime.utcnow() or sub.lifecycle_status not in {"active","cancel_scheduled"}:
        raise HTTPException(409,"Нужна действующая подписка с конечным сроком")
    return sub


async def _effective_rate(db,sub):
    if sub.unit_price_per_day is not None:return Decimal(sub.unit_price_per_day)
    paid=await db.scalar(select(Payment).where(Payment.user_id==sub.user_id,Payment.subscription_id==sub.id,Payment.plan_id==sub.plan_id,
        Payment.purpose=="subscription",Payment.status.in_(("paid","fulfilled")),
        Payment.fulfillment_status=="completed",Payment.currency==settings.default_currency).order_by(Payment.id.desc()).limit(1))
    if not paid:return Decimal(0) # Trials and free gifts cannot create paid upgrade credit.
    days=int(paid.duration_days_snapshot or 0)+int(paid.bonus_days or 0)
    if days<=0:return Decimal(0)
    return Decimal(paid.amount)/Decimal(days)


async def _validate_reduction(db,sub,after,force_traffic=False,remote_id=None,remote_client=None):
    if after["devices"] is not None:
        count=await db.scalar(select(func.count()).select_from(UserDevice).where(UserDevice.user_id==sub.user_id,UserDevice.subscription_id==sub.id,UserDevice.status=="active"))
        if int(count or 0)>after["devices"]:raise HTTPException(409,"Сначала отключите лишние устройства")
    before=sub.traffic_limit_gb_snapshot
    if after["traffic_gb"] is not None and (force_traffic or before is None or after["traffic_gb"]<before):
        remote_id=remote_id or sub.remnawave_uuid
        if not remote_id:raise HTTPException(409,"Не удалось проверить использованный трафик")
        remote=await (remote_client or RemnawaveClient()).get_user(remote_id)
        remote=remote.get("response",remote)
        used=(remote.get("userTraffic") or {}).get("usedTrafficBytes")
        if used is None:used=remote.get("trafficUsedBytes",remote.get("usedTrafficBytes"))
        if used is None or isinstance(used,bool):raise HTTPException(409,"Панель не вернула использованный трафик")
        try:used=int(used)
        except (TypeError,ValueError):raise HTTPException(409,"Панель вернула некорректный трафик")
        if used<0:raise HTTPException(409,"Панель вернула некорректный трафик")
        if int(used)>after["traffic_gb"]*1024**3:raise HTTPException(409,"Новый лимит меньше уже использованного трафика")


class QuoteIn(BaseModel):
    kind:str=Field(pattern="^(subscription_change|traffic_addon)$")
    subscription_id:int|None=Field(default=None,gt=0)
    plan_id:int|None=Field(default=None,gt=0)
    package_id:int|None=Field(default=None,gt=0)
    constructor_id:int|None=Field(default=None,gt=0)
    device_option_id:int|None=Field(default=None,gt=0)
    traffic_option_id:int|None=Field(default=None,gt=0)
    days_option_id:int|None=Field(default=None,gt=0)


class PurchaseIn(BaseModel):
    quote_id:str=Field(min_length=1,max_length=64)


class PackageIn(BaseModel):
    name:str=Field(min_length=1,max_length=255)
    traffic_gb:int=Field(ge=1,le=100000)
    price:Decimal=Field(gt=0,le=1000000,max_digits=12,decimal_places=2)
    plan_id:int|None=Field(default=None,gt=0)
    enabled:bool=True
    sort_order:int=Field(default=0,ge=-10000,le=10000)


def package_out(row):
    return {"id":row.id,"name":row.name,"traffic_gb":row.traffic_gb,"price":str(row.price),
            "plan_id":row.plan_id,"enabled":row.enabled,"sort_order":row.sort_order}


@router.get("/api/me/subscription/commerce")
async def commerce_catalog(request:Request,db:AsyncSession=Depends(get_db)):
    user=await _owner(request,db);sub=await _subscription(db,user.id)
    packages=(await db.execute(select(TrafficPackage).where(TrafficPackage.enabled.is_(True),
        or_(TrafficPackage.plan_id.is_(None),TrafficPackage.plan_id==sub.plan_id)).order_by(TrafficPackage.sort_order,TrafficPackage.id))).scalars().all()
    from .models import TariffConstructor
    plans=(await db.execute(select(Plan).where(Plan.enabled.is_(True),Plan.price>0,
        ~Plan.id.in_(select(TariffConstructor.plan_id).where(TariffConstructor.plan_id.is_not(None)))).order_by(Plan.id))).scalars().all()
    return {"subscription_id":sub.id,"current":public_state(entitlement_state(sub)),"balance":str(user.wallet_balance),
            "currency":settings.default_currency,"packages":[package_out(p) for p in packages],
            "plans":[{"id":p.id,"name":p.name,"price":str(p.price),"duration_days":p.duration_days,"traffic_gb":p.traffic_limit_gb,"devices":p.device_limit} for p in plans]}


@router.post("/api/me/subscription/quote")
async def quote_change(payload:QuoteIn,request:Request,db:AsyncSession=Depends(get_db)):
    user=await _owner(request,db);sub=await _subscription(db,user.id,payload.subscription_id)
    before=entitlement_state(sub);after=dict(before)
    if payload.kind=="traffic_addon":
        package=await db.get(TrafficPackage,payload.package_id) if payload.package_id else None
        if not package or not package.enabled or package.plan_id not in (None,sub.plan_id):raise HTTPException(404,"Пакет трафика недоступен")
        if before["traffic_gb"] is None:raise HTTPException(409,"У подписки безлимитный трафик")
        after["traffic_gb"]=before["traffic_gb"]+package.traffic_gb
        amount=Decimal(package.price)
    else:
        if payload.constructor_id:
            from .tariff_api import quote_constructor
            choice=await quote_constructor(db,payload.model_dump())
            plan=await db.get(Plan,choice["plan_id"])
            price,days,traffic,devices,profile=choice["amount"],choice["days"],choice["traffic_gb"],choice["devices"],choice["profile_id"]
        else:
            plan=await db.get(Plan,payload.plan_id) if payload.plan_id else None
            if not plan or not plan.enabled or plan.price<=0:raise HTTPException(404,"Тариф недоступен")
            from .tariff_api import linked_constructor_id
            if await linked_constructor_id(db,plan.id):raise HTTPException(400,"Выберите опции конструктора")
            price,days,traffic,devices,profile=plan.price,plan.duration_days,plan.traffic_limit_gb,plan.device_limit,plan.remnawave_profile_id
        if not plan or not plan.enabled or days<=0:raise HTTPException(404,"Тариф недоступен")
        new_rate=Decimal(price)/Decimal(days)
        amount=prorated_amount(await _effective_rate(db,sub),new_rate,(sub.expires_at-datetime.utcnow()).total_seconds())
        after.update(plan_id=plan.id,traffic_gb=traffic,devices=devices,profile=profile,unit_price=str(new_rate.quantize(Decimal("0.00000001"))))
        after['renewal_terms']=({'amount':str(price),'days':days,'traffic_gb':traffic,'devices':devices,'profile_id':profile,'currency':settings.default_currency}
                                if payload.constructor_id else None)
        if after==before:raise HTTPException(409,"Эти условия уже применены")
        await _validate_reduction(db,sub,after)
    quote=EntitlementQuote(id=secrets.token_urlsafe(24),user_id=user.id,subscription_id=sub.id,kind=payload.kind,
        amount=amount,currency=settings.default_currency,before=before,after=after,expires_at=datetime.utcnow()+timedelta(seconds=60))
    db.add(quote);await db.commit()
    return {"id":quote.id,"amount":str(amount),"currency":quote.currency,"expires_at":quote.expires_at,
            "before":public_state(before),"after":public_state(after),"kind":quote.kind}


@router.post("/api/me/subscription/purchase")
async def purchase_change(payload:PurchaseIn,request:Request,db:AsyncSession=Depends(get_db)):
    from .main import record_financial_event,ensure_required_channel,maintenance_enabled,feature_enabled,_risk_score
    user=await _owner(request,db)
    if await maintenance_enabled(db) or not await feature_enabled(db,"payments",True):raise HTTPException(503,"Продажи временно отключены")
    await ensure_required_channel(user)
    key=request.headers.get("Idempotency-Key")
    if not key or len(key)>128:raise HTTPException(400,"Idempotency-Key обязателен")
    # Serializes all wallet reservations and quote consumption for this buyer.
    user=await db.scalar(select(User).where(User.id==user.id).execution_options(populate_existing=True).with_for_update())
    old=await db.scalar(select(Payment).where(Payment.user_id==user.id,Payment.idempotency_key==key))
    if old:
        operation=await db.scalar(select(EntitlementOperation).where(EntitlementOperation.payment_id==old.id))
        if not operation or operation.quote_id!=payload.quote_id:raise HTTPException(409,"Ключ уже использован другим заказом")
        return {"id":old.id,"status":old.status,"fulfillment_status":old.fulfillment_status}
    quote=await db.scalar(select(EntitlementQuote).where(EntitlementQuote.id==payload.quote_id,EntitlementQuote.user_id==user.id).with_for_update())
    if not quote:raise HTTPException(404,"Расчёт не найден")
    previous=await db.scalar(select(EntitlementOperation).where(EntitlementOperation.quote_id==quote.id))
    if previous:
        payment=await db.get(Payment,previous.payment_id)
        return {"id":payment.id,"status":payment.status,"fulfillment_status":payment.fulfillment_status}
    if quote.expires_at<=datetime.utcnow() or quote.currency!=settings.default_currency:raise HTTPException(409,"Расчёт истёк; запросите новый")
    sub=await _subscription(db,user.id,quote.subscription_id,lock=True)
    if any(entitlement_state(sub).get(k)!=v for k,v in quote.before.items()):raise HTTPException(409,"Условия подписки изменились; запросите новый расчёт")
    from .subscriptions import ensure_no_pending_purchase
    await ensure_no_pending_purchase(db,sub.id)
    if Decimal(user.wallet_balance or 0)<quote.amount:raise HTTPException(402,"Недостаточно средств в кошельке")
    if (await _risk_score(db,user,quote.amount,request))[1]=="block":raise HTTPException(403,"Операция отклонена системой защиты")
    payment=Payment(user_id=user.id,subscription_id=sub.id,plan_id=quote.after["plan_id"],provider="wallet",order_id="adjust-"+quote.id,
        amount=quote.amount,original_amount=quote.amount,currency=quote.currency,status="paid",paid_at=datetime.utcnow(),
        purpose=quote.kind,idempotency_key=key,fulfillment_status="pending",next_retry_at=datetime.utcnow(),
        duration_days_snapshot=0,traffic_limit_gb_snapshot=quote.after["traffic_gb"],device_limit_snapshot=quote.after["devices"],remnawave_profile_id_snapshot=quote.after["profile"])
    db.add(payment);await db.flush()
    user.wallet_balance=Decimal(user.wallet_balance or 0)-quote.amount
    operation=EntitlementOperation(quote_id=quote.id,payment_id=payment.id,user_id=user.id,subscription_id=sub.id,
        kind=quote.kind,before=quote.before,after=quote.after,status="queued")
    db.add(operation)
    if quote.amount>0:await record_financial_event(db,operation_key=f"wallet-spend:{payment.id}",user_id=user.id,payment_id=payment.id,kind="wallet_spend",direction="debit",amount=quote.amount,currency=quote.currency,metadata={"purpose":quote.kind})
    db.add(Job(job_key=f"fulfillment:{payment.id}",kind="fulfillment",status="queued",payload={"payment_id":payment.id},next_retry_at=datetime.utcnow()))
    await db.commit()
    return {"id":payment.id,"status":payment.status,"fulfillment_status":payment.fulfillment_status}


async def apply_change(payment_id,db):
    from .main import (_acquire_user_fulfillment_lock,_acquire_payment_side_effect_lock,
                       _release_payment_side_effect_lock,audit,sandbox_local_vpn)
    discovery=await db.get(Payment,payment_id)
    if not discovery:raise RuntimeError("Payment not found")
    user_lock,user_token=await _acquire_user_fulfillment_lock(discovery.user_id,ttl=300)
    payment_lock=token=None
    try:
        payment_lock,token=await _acquire_payment_side_effect_lock(payment_id)
        user=await db.scalar(select(User).where(User.id==discovery.user_id).execution_options(populate_existing=True).with_for_update())
        payment=await db.scalar(select(Payment).where(Payment.id==payment_id).execution_options(populate_existing=True).with_for_update())
        op=await db.scalar(select(EntitlementOperation).where(EntitlementOperation.payment_id==payment_id).with_for_update())
        if not user or user.deleted_at or not op:raise RuntimeError("Owner or operation missing")
        if op.status=="applied" and payment.fulfillment_status=="completed":return
        if payment.fulfillment_terminal: return
        if (payment.fulfillment_attempts or 0) >= (payment.fulfillment_max_attempts or settings.fulfillment_max_attempts):
            payment.fulfillment_terminal=True; await db.commit(); return
        if payment.status!="paid" or op.status not in {"queued","applying"}:raise RuntimeError("Operation is not payable")
        sub=await db.scalar(select(Subscription).where(Subscription.id==op.subscription_id,Subscription.user_id==user.id).with_for_update())
        if not sub or any(entitlement_state(sub).get(k)!=v for k,v in op.before.items()):raise RuntimeError("Entitlement changed; refund or reconcile this operation")
        if not sub.expires_at or sub.expires_at<=datetime.utcnow():raise RuntimeError("Subscription expired before application")
        op.status="applying";payment.fulfillment_status="processing";payment.fulfillment_attempts=(payment.fulfillment_attempts or 0)+1
        await db.commit() # Durable before the remote call; replay always sets absolute limits.
        if not sub.remnawave_uuid:raise RuntimeError("Remote subscription is not provisioned")
        if not (sandbox_local_vpn() and sub.remnawave_uuid.startswith("sandbox-")):
            await _validate_reduction(db,sub,op.after)
            await RemnawaveClient().update_entitlements(sub.remnawave_uuid,op.after["traffic_gb"],op.after["profile"])
        sub.plan_id=op.after["plan_id"];sub.traffic_limit_gb_snapshot=op.after["traffic_gb"]
        sub.device_limit_snapshot=op.after["devices"];sub.remnawave_profile_id_snapshot=op.after["profile"]
        sub.unit_price_per_day=Decimal(op.after["unit_price"]) if op.after["unit_price"] is not None else None
        if op.kind=='subscription_change':sub.renewal_terms=op.after.get('renewal_terms')
        op.status="applied";op.completed_at=datetime.utcnow();op.error=None
        payment.fulfillment_status="completed";payment.fulfillment_terminal=True;payment.next_retry_at=None;payment.fulfillment_error=None
        job=await db.scalar(select(Job).where(Job.job_key==f"fulfillment:{payment.id}"))
        if job:job.status="completed";job.completed_at=datetime.utcnow();job.error=None
        db.add(Notification(user_id=user.id,channel="in_app",kind=op.kind,title="Условия подписки обновлены",body="Операция выполнена. Срок подписки сохранён.",status="sent",dedupe_key=f"entitlement:{op.id}:applied",sent_at=datetime.utcnow()))
        await audit(db,"subscription.commerce.applied","system",str(op.id),{"payment_id":payment.id});await db.commit()
    except Exception as exc:
        await db.rollback()
        payment=await db.get(Payment,payment_id)
        op=await db.scalar(select(EntitlementOperation).where(EntitlementOperation.payment_id==payment_id))
        if payment and payment.status=="paid" and op and op.status not in {"applied","refunded"}:
            payment.fulfillment_status="failed";payment.fulfillment_error=str(exc)[:1000]
            payment.fulfillment_terminal=(payment.fulfillment_attempts or 0)>=(payment.fulfillment_max_attempts or settings.fulfillment_max_attempts)
            payment.next_retry_at=None if payment.fulfillment_terminal else datetime.utcnow()+timedelta(seconds=60)
            op.error=str(exc)[:1000];await db.commit()
        raise
    finally:
        if payment_lock and token:await _release_payment_side_effect_lock(payment_lock,token)
        await _release_payment_side_effect_lock(user_lock,user_token)


@router.get("/api/admin/traffic-packages")
async def admin_packages(db:AsyncSession=Depends(get_db),admin=Depends(require_permission("read"))):
    return [package_out(p) for p in (await db.execute(select(TrafficPackage).order_by(TrafficPackage.sort_order,TrafficPackage.id))).scalars().all()]


@router.post("/api/admin/traffic-packages")
async def create_package(payload:PackageIn,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("manage_plans"))):
    from .main import audit
    if not payload.name.strip():raise HTTPException(400,"Укажите название")
    if payload.plan_id and not await db.get(Plan,payload.plan_id):raise HTTPException(404,"Тариф не найден")
    row=TrafficPackage(**payload.model_dump());db.add(row);await db.flush();await audit(db,"traffic_package.created",admin.email,str(row.id));await db.commit()
    return package_out(row)


@router.put("/api/admin/traffic-packages/{package_id}")
async def edit_package(package_id:int,payload:PackageIn,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("manage_plans"))):
    from .main import audit
    row=await db.get(TrafficPackage,package_id)
    if not row:raise HTTPException(404,"Пакет не найден")
    if not payload.name.strip():raise HTTPException(400,"Укажите название")
    if payload.plan_id and not await db.get(Plan,payload.plan_id):raise HTTPException(404,"Тариф не найден")
    for key,value in payload.model_dump().items():setattr(row,key,value)
    await audit(db,"traffic_package.updated",admin.email,str(row.id));await db.commit()
    return package_out(row)


def operation_out(op,payment):
    return {"id":op.id,"payment_id":payment.id,"kind":op.kind,"amount":str(payment.amount),
            "currency":payment.currency,"status":op.status,"fulfillment_status":payment.fulfillment_status,
            "created_at":op.created_at,"before":public_state(op.before),"after":public_state(op.after)}


@router.get("/api/me/subscription/operations")
async def commerce_history(request:Request,db:AsyncSession=Depends(get_db)):
    user=await _owner(request,db)
    rows=(await db.execute(select(EntitlementOperation,Payment).join(Payment,Payment.id==EntitlementOperation.payment_id)
        .where(EntitlementOperation.user_id==user.id,Payment.user_id==user.id).order_by(EntitlementOperation.id.desc()).limit(100))).all()
    return [operation_out(op,payment) for op,payment in rows]


@router.get("/api/admin/subscription-operations")
async def admin_operations(db:AsyncSession=Depends(get_db),admin=Depends(require_permission("payments.read"))):
    rows=(await db.execute(select(EntitlementOperation,Payment).join(Payment,Payment.id==EntitlementOperation.payment_id)
        .order_by(EntitlementOperation.id.desc()).limit(100))).all()
    return [{**operation_out(op,payment),"user_id":op.user_id,"error":op.error} for op,payment in rows]


@router.post("/api/admin/subscription-operations/{operation_id}/refund")
async def refund_change(operation_id:int,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("payments.refund"))):
    """Restore the snapshot before crediting the wallet, including uncertain remote writes."""
    from .main import (_acquire_user_fulfillment_lock,_acquire_payment_side_effect_lock,
                       _release_payment_side_effect_lock,audit,record_financial_event,sandbox_local_vpn)
    op=await db.get(EntitlementOperation,operation_id)
    if not op:raise HTTPException(404,"Операция не найдена")
    user_id,payment_id=op.user_id,op.payment_id
    user_lock,user_token=await _acquire_user_fulfillment_lock(user_id,ttl=300)
    payment_lock=token=None
    try:
        payment_lock,token=await _acquire_payment_side_effect_lock(payment_id)
        user=await db.scalar(select(User).where(User.id==user_id).execution_options(populate_existing=True).with_for_update())
        payment=await db.scalar(select(Payment).where(Payment.id==payment_id).execution_options(populate_existing=True).with_for_update())
        op=await db.scalar(select(EntitlementOperation).where(EntitlementOperation.id==operation_id).execution_options(populate_existing=True).with_for_update())
        if not user or user.deleted_at or not payment or payment.provider!="wallet":raise HTTPException(409,"Возврат недоступен")
        if op.status=="refunded":return {"ok":True,"already_refunded":True}
        if payment.status!="paid" or op.status not in {"queued","applying","applied","refund_pending"}:raise HTTPException(409,"Возврат недоступен")
        sub=await db.scalar(select(Subscription).where(Subscription.id==op.subscription_id,Subscription.user_id==user.id).execution_options(populate_existing=True).with_for_update())
        state=entitlement_state(sub) if sub else None
        if state not in (op.before,op.after):raise HTTPException(409,"Подписка изменена последующим заказом; требуется ручная сверка")
        needs_remote=op.status!="queued"
        if needs_remote and (not sub.expires_at or sub.expires_at<=datetime.utcnow()):raise HTTPException(409,"Подписка истекла; требуется ручная сверка")
        if needs_remote:
            if not sub.remnawave_uuid:raise HTTPException(409,"Удалённая подписка не найдена")
            # Stop fulfillment retries before restoring the remote snapshot.
            op.status="refund_pending";payment.fulfillment_terminal=True;payment.next_retry_at=None
            await db.commit()
            if not (sandbox_local_vpn() and sub.remnawave_uuid.startswith("sandbox-")):
                await _validate_reduction(db,sub,op.before,force_traffic=True)
                await RemnawaveClient().update_entitlements(sub.remnawave_uuid,op.before["traffic_gb"],op.before["profile"])
            # Reacquire wallet row after the remote call: unrelated deposits can arrive meanwhile.
            user=await db.scalar(select(User).where(User.id==user_id).execution_options(populate_existing=True).with_for_update())
            sub.plan_id=op.before["plan_id"];sub.traffic_limit_gb_snapshot=op.before["traffic_gb"]
            sub.device_limit_snapshot=op.before["devices"];sub.remnawave_profile_id_snapshot=op.before["profile"]
            sub.unit_price_per_day=Decimal(op.before["unit_price"]) if op.before["unit_price"] is not None else None
        user.wallet_balance=Decimal(user.wallet_balance or 0)+Decimal(payment.amount)
        if payment.amount>0:
            await record_financial_event(db,operation_key=f"commerce-refund:{op.id}",user_id=user.id,payment_id=payment.id,
                kind="wallet_purchase_refund",direction="credit",amount=payment.amount,currency=payment.currency,metadata={"operation_id":op.id})
        op.status="refunded";op.error=None;op.completed_at=datetime.utcnow()
        payment.status="refunded";payment.fulfillment_terminal=True;payment.next_retry_at=None
        payment.fulfillment_status="refunded";payment.fulfillment_error=None
        job=await db.scalar(select(Job).where(Job.job_key==f"fulfillment:{payment.id}"))
        if job:job.status="cancelled";job.completed_at=datetime.utcnow()
        await audit(db,"subscription.commerce.refunded",admin.email,str(op.id),{"payment_id":payment.id})
        await db.commit();return {"ok":True,"already_refunded":False}
    except Exception as exc:
        await db.rollback()
        op=await db.get(EntitlementOperation,operation_id)
        if op and op.status=="refund_pending":op.error=str(exc)[:1000];await db.commit()
        raise
    finally:
        if payment_lock and token:await _release_payment_side_effect_lock(payment_lock,token)
        await _release_payment_side_effect_lock(user_lock,user_token)
