"""Gift purchase snapshots and owner-bound, replay-safe redemption."""
from datetime import datetime,timedelta
from decimal import Decimal
import hashlib,json,secrets
from fastapi import HTTPException
from sqlalchemy import select,func
from .models import User,Plan,GiftCode,GiftRedemption,Subscription,UserDevice
from .subscriptions import reserve_target,owned,remote_username,selection


def fingerprint(payload):
    fields=('plan_id','constructor_id','device_option_id','traffic_option_id','days_option_id')
    data={}
    for key in fields:
        if payload.get(key) not in (None,''):
            try:data[key]=int(payload[key])
            except (TypeError,ValueError):raise HTTPException(400,'Некорректные параметры подарка')
            if data[key]<=0 or isinstance(payload[key],bool):raise HTTPException(400,'Некорректные параметры подарка')
    return hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()


def result(gift,user=None):
    from .main import settings
    return {'ok':True,'code':gift.code,'bot_claim_url':f'https://t.me/{settings.bot_username}?start={gift.code}' if settings.bot_username else None,
            **({'wallet_balance':str(user.wallet_balance)} if user else {})}


def check_retry(gift,payload,digest):
    if gift.purchase_fingerprint and gift.purchase_fingerprint!=digest:raise HTTPException(409,'Ключ использован для другого подарка')
    if not gift.purchase_fingerprint and payload.get('plan_id') and gift.plan_id!=int(payload['plan_id']):raise HTTPException(409,'Ключ использован для другого подарка')


async def purchase_gift(payload,request,db):
    from . import main
    from .platform_api import reject_restricted
    if await main.maintenance_enabled(db):raise HTTPException(503,'Service is in maintenance mode')
    user=await main.user_from_token(request,db);reject_restricted(user)
    from .app_config import require_consent
    await require_consent(db,user)
    key=request.headers.get('Idempotency-Key')
    if not key or len(key)>128:raise HTTPException(400,'Idempotency-Key is required')
    digest=fingerprint(payload)
    gift=await db.scalar(select(GiftCode).where(GiftCode.purchaser_user_id==user.id,GiftCode.idempotency_key==key))
    if gift:check_retry(gift,payload,digest);return result(gift)
    await main.ensure_required_channel(user)
    from .tariff_api import quote_constructor,linked_constructor_id
    if payload.get('constructor_id'):
        choice=await quote_constructor(db,payload);plan=await db.get(Plan,choice['plan_id'])
        price=main._money(choice['amount'])
        snapshot={k:choice[k] for k in ('days','traffic_gb','devices','profile_id')}
    else:
        try:plan_id=int(payload.get('plan_id'))
        except (TypeError,ValueError):raise HTTPException(400,'Invalid plan_id')
        plan=await db.get(Plan,plan_id)
        if not plan or not plan.enabled:raise HTTPException(404,'Not found')
        if await linked_constructor_id(db,plan.id):raise HTTPException(400,'Подарок собирается через конструктор тарифа')
        price=main._money(plan.price)
        snapshot={'days':plan.duration_days,'traffic_gb':plan.traffic_limit_gb,'devices':plan.device_limit,'profile_id':plan.remnawave_profile_id}
    if price<=0:raise HTTPException(400,'Gift plan must have a positive price')
    snapshot['currency']=main.settings.default_currency
    lock,token=await main._acquire_user_fulfillment_lock(user.id,ttl=300)
    try:
        user=await db.scalar(select(User).where(User.id==user.id).execution_options(populate_existing=True).with_for_update())
        if not user or user.deleted_at:raise HTTPException(409,'Аккаунт недоступен')
        gift=await db.scalar(select(GiftCode).where(GiftCode.purchaser_user_id==user.id,GiftCode.idempotency_key==key).with_for_update())
        if gift:check_retry(gift,payload,digest);return result(gift,user)
        # Legacy gift keys are globally unique; report conflicts without a second debit.
        if await db.scalar(select(GiftCode.id).where(GiftCode.idempotency_key==key)):raise HTTPException(409,'Ключ уже использован')
        balance=main._money(user.wallet_balance or 0)
        if balance<price:raise HTTPException(402,'Недостаточно средств на балансе')
        user.wallet_balance=balance-price
        gift=GiftCode(code='GIFT_'+secrets.token_hex(20).upper(),plan_id=plan.id,duration_days=snapshot['days'],
            max_uses=1,purchaser_user_id=user.id,idempotency_key=key,entitlements_snapshot=snapshot,purchase_fingerprint=digest,purchase_amount=price)
        db.add(gift);await db.flush()
        await main.record_financial_event(db,operation_key=f'gift-purchase:{gift.id}',user_id=user.id,payment_id=None,
            kind='gift_purchase',direction='debit',amount=price,currency=main.settings.default_currency,metadata={'plan_id':plan.id})
        await main.audit(db,'gift.purchased',f'user:{user.id}',str(gift.id),{'plan_id':plan.id});await db.commit()
        return result(gift,user)
    finally:await main._release_payment_side_effect_lock(lock,token)


async def redeem_gift(payload,request,db):
    from . import main
    from .platform_api import reject_restricted
    from .subscription_commerce import _validate_reduction,entitlement_state
    user=await main.user_from_token(request,db);reject_restricted(user)
    completed=await db.scalar(select(GiftRedemption.id).join(GiftCode,GiftCode.id==GiftRedemption.gift_code_id).where(
        func.upper(GiftCode.code)==payload.code.strip().upper(),GiftRedemption.user_id==user.id,GiftRedemption.status=='completed'))
    if completed:return {'ok':True,'status':'completed','already_redeemed':True}
    lock,token=await main._acquire_user_fulfillment_lock(user.id,ttl=900)
    try:
        user=await db.scalar(select(User).where(User.id==user.id).execution_options(populate_existing=True).with_for_update())
        if not user or user.deleted_at:raise HTTPException(409,'Аккаунт недоступен')
        code=await db.scalar(select(GiftCode).where(func.upper(GiftCode.code)==payload.code.strip().upper()).with_for_update())
        if not code or not code.enabled:raise HTTPException(404,'Gift code not found')
        if code.purchaser_user_id==user.id:raise HTTPException(403,'Gift purchaser cannot redeem their own gift')
        redemption=await db.scalar(select(GiftRedemption).where(GiftRedemption.gift_code_id==code.id,GiftRedemption.user_id==user.id).with_for_update())
        if redemption and redemption.status=='completed':return {'ok':True,'status':'completed','already_redeemed':True}
        # Once reserved, expiry cannot make an uncertain successful write unrecoverable.
        if not redemption:
            if code.expires_at and code.expires_at<=datetime.utcnow():raise HTTPException(410,'Gift code expired')
            pending=await db.scalar(select(func.count()).select_from(GiftRedemption).where(GiftRedemption.gift_code_id==code.id,GiftRedemption.status!='completed'))
            if code.used_count+int(pending or 0)>=code.max_uses:raise HTTPException(409,'Gift code already exhausted or reserved')
        plan=await db.get(Plan,code.plan_id)
        if not plan and not code.entitlements_snapshot:raise HTTPException(409,'Gift plan is unavailable')
        terms=code.entitlements_snapshot or {'days':code.duration_days or plan.duration_days,'traffic_gb':plan.traffic_limit_gb,'devices':plan.device_limit,'profile_id':plan.remnawave_profile_id}
        if not redemption:
            sub=await reserve_target(db,user,code.plan_id,payload.model_dump(exclude={'code'}))

            redemption=GiftRedemption(gift_code_id=code.id,user_id=user.id,subscription_id=sub.id,operation_key=f'gift:{code.id}:{user.id}',status='processing')
            db.add(redemption);await db.flush()
        else:
            sub=await owned(db,user.id,redemption.subscription_id,lock=True)
            if not sub:raise HTTPException(409,'Gift subscription is missing')
            if payload.subscription_id is not None and payload.subscription_id!=sub.id:raise HTTPException(409,'Подарок закреплён за другой подпиской')
        if redemption.before_snapshot and any(entitlement_state(sub).get(k)!=v for k,v in redemption.before_snapshot.items()):
            raise HTTPException(409,'Подписка изменилась после начала активации; требуется проверка оператором')
        if not redemption.before_snapshot:redemption.before_snapshot=entitlement_state(sub)
        rw=main.RemnawaveClient();now=datetime.utcnow()
        if sub.remnawave_uuid in {'None','none','null'}:sub.remnawave_uuid=None  # stored by releases before v28.22.0
        remote_id=sub.remnawave_uuid or (redemption.remote_user_id if redemption.remote_user_id not in {'None','none','null'} else None)
        if remote_id:
            await _validate_reduction(db,sub,{'traffic_gb':terms['traffic_gb'],'devices':terms['devices']},remote_id=remote_id,remote_client=rw)
        if redemption.expected_after_expires_at is None:
            before=max(sub.expires_at or now,now)
            if remote_id:before=max(before,await rw.get_expiry(remote_id) or now)
            redemption.expected_before_expires_at=before
            redemption.expected_after_expires_at=before+timedelta(days=int(terms['days']))
        redemption.status='processing';redemption.error=None
        await db.commit() # Claims this gift use and freezes the target before any remote write.
        target=redemption.expected_after_expires_at
        code_id,user_id=code.id,user.id
        try:
            if not remote_id:
                existing=await rw.get_user_by_username(remote_username(user.id,sub))
                if existing and existing.get('id'):
                    remote_id=str(existing['id'])
                    await _validate_reduction(db,sub,{'traffic_gb':terms['traffic_gb'],'devices':terms['devices']},force_traffic=True,remote_id=remote_id,remote_client=rw)
                else:
                    data=await rw.create_user(remote_username(user.id,sub),target,terms['traffic_gb']*1024**3 if terms['traffic_gb'] else 0,
                        active_internal_squads=[terms['profile_id']] if terms['profile_id'] else None,telegram_id=user.telegram_id)
                    if not data.get('id'):raise RuntimeError('Remnawave returned no user id')
                    remote_id=str(data['id']);sub.subscription_url=data.get('subscriptionUrl') or data.get('subscription_url')
                redemption.remote_user_id=remote_id;await db.commit()
            await rw.update_entitlements(remote_id,terms['traffic_gb'],terms['profile_id'])
            await rw.extend_idempotent(remote_id,int(terms['days']),redemption.expected_before_expires_at,target)
            sub.remnawave_uuid=remote_id;sub.plan_id=code.plan_id;sub.expires_at=target;sub.lifecycle_status='active'
            sub.scheduled_cancel_at=None;sub.grace_until=None;sub.unit_price_per_day=Decimal(0)
            sub.traffic_limit_gb_snapshot=terms['traffic_gb'];sub.device_limit_snapshot=terms['devices'];sub.remnawave_profile_id_snapshot=terms['profile_id']
            from .tariff_api import linked_constructor_id
            sub.renewal_terms=({**terms,'amount':str(code.purchase_amount)}
                if code.purchase_amount and code.purchase_amount>0 and terms.get('currency') and await linked_constructor_id(db,code.plan_id) else None)
            if not sub.subscription_url:
                info=await rw.get_subscription(remote_id);sub.subscription_url=info.get('subscriptionUrl') or info.get('subscription_url')
            code=await db.scalar(select(GiftCode).where(GiftCode.id==code_id).execution_options(populate_existing=True).with_for_update())
            redemption.status='completed';code.used_count+=1
            await main.audit(db,'gift.redeemed',f'user:{user.id}',str(code.id),{'plan_id':code.plan_id,'duration_days':terms['days'],'operation_key':redemption.operation_key})
            await db.commit();return {'ok':True,'plan_id':code.plan_id,'subscription_id':sub.id,'expires_at':target,'operation_key':redemption.operation_key}
        except Exception as exc:
            await db.rollback()
            redemption=await db.scalar(select(GiftRedemption).where(GiftRedemption.gift_code_id==code_id,GiftRedemption.user_id==user_id))
            if redemption and redemption.status!='completed':redemption.status='failed';redemption.error=str(exc)[:1000];await db.commit()
            raise HTTPException(503,'Активация ожидает повторной проверки. Повторите тот же подарок.') from exc
    finally:await main._release_payment_side_effect_lock(lock,token)
