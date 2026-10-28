"""Customer account API (moved from main.py in v28.36.0): subscription, billing and security centres, wallet, gifts, referral, auto-renew and connection info.

Names that belong to main are read through ``shop.<name>`` at call time, so tests and
operators that patch ``app.main`` keep affecting this code exactly as before."""
from .sub_proxy import client_url
from . import main as shop

# ---------- Customer account: subscription, wallet, gifts, referral, auto-renew ----------
@shop.app.get("/api/me/subscription")
async def my_subscription(request:shop.Request,db:shop.AsyncSession=shop.Depends(shop.get_db)):
    user=await shop.user_from_token(request,db); sub=(await db.execute(shop.select(shop.Subscription).where(shop.Subscription.user_id==user.id,shop.Subscription.is_primary.is_(True)))).scalar_one_or_none()
    return {"subscription":None if not sub else {"id":sub.id,"plan_id":sub.plan_id,"expires_at":sub.expires_at,"subscription_url":client_url(sub.subscription_url),"remnawave_uuid":sub.remnawave_uuid},"auto_renew_enabled":user.auto_renew_enabled}

@shop.app.get("/api/me/billing-center")
async def billing_center(request:shop.Request,db:shop.AsyncSession=shop.Depends(shop.get_db)):
    user=await shop.user_from_token(request,db)
    sub=(await db.execute(shop.select(shop.Subscription).where(shop.Subscription.user_id==user.id,shop.Subscription.is_primary.is_(True)))).scalar_one_or_none()
    payments=(await db.execute(shop.select(shop.Payment).where(shop.Payment.user_id==user.id).order_by(shop.Payment.id.desc()).limit(50))).scalars().all()
    return {"subscription": None if not sub else {"id":sub.id,"plan_id":sub.plan_id,"status":sub.lifecycle_status,"expires_at":sub.expires_at,"grace_until":sub.grace_until,"scheduled_cancel_at":sub.scheduled_cancel_at,"auto_renew":user.auto_renew_enabled},"payments":[{"id":p.id,"order_id":p.order_id,"amount":str(p.amount),"currency":p.currency,"status":p.status,"fulfillment_status":p.fulfillment_status,"created_at":p.created_at,"paid_at":p.paid_at} for p in payments],"imported_payments":await shop.customer_imported_payments(db,user.id)}

@shop.app.get("/api/me/security-center")
async def security_center(request:shop.Request,db:shop.AsyncSession=shop.Depends(shop.get_db)):
    user=await shop.user_from_token(request,db)
    devices=(await db.execute(shop.select(shop.UserDevice).where(shop.UserDevice.user_id==user.id).order_by(shop.UserDevice.last_seen_at.desc().nullslast()))).scalars().all()
    events=(await db.execute(shop.select(shop.AuditLog).where(shop.AuditLog.actor==f"user:{user.id}").order_by(shop.AuditLog.id.desc()).limit(20))).scalars().all()
    sessions=(await db.execute(shop.select(shop.UserSession).where(shop.UserSession.user_id==user.id).order_by(shop.UserSession.id.desc()).limit(20))).scalars().all()
    return {"user_id":user.id,"sessions":[{"id":x.id,"ip":x.ip,"user_agent":x.user_agent,"created_at":x.created_at,"last_seen_at":x.last_seen_at,"expires_at":x.expires_at,"revoked_at":x.revoked_at} for x in sessions],"devices":[{"id":d.id,"name":d.name,"platform":d.platform,"last_ip":d.last_ip,"last_seen_at":d.last_seen_at,"status":d.status,"revoked_at":d.revoked_at} for d in devices],"events":[{"action":e.action,"target":e.target,"created_at":e.created_at} for e in events]}

@shop.app.post("/api/me/subscription/lifecycle")
async def subscription_lifecycle(payload:shop.SubscriptionActionIn,request:shop.Request,db:shop.AsyncSession=shop.Depends(shop.get_db)):
    user=await shop.user_from_token(request,db)
    lock,token=await shop._acquire_user_fulfillment_lock(user.id,ttl=300)
    try:
        user=(await db.execute(shop.select(shop.User).where(shop.User.id==user.id).with_for_update())).scalar_one()
        sub=(await db.execute(shop.select(shop.Subscription).where(shop.Subscription.user_id==user.id,shop.Subscription.is_primary.is_(True)).with_for_update())).scalar_one_or_none()
        if not sub: raise shop.HTTPException(404,"Subscription not found")
        now=shop.datetime.utcnow()
        if payload.action=="cancel":
            if sub.lifecycle_status in {"expired","cancelled"}: raise shop.HTTPException(409,"Subscription is already inactive")
            sub.scheduled_cancel_at=sub.expires_at or now; sub.lifecycle_status="cancel_scheduled"
            if payload.reason:
                from .models import CancellationFeedback
                db.add(CancellationFeedback(user_id=user.id,subscription_id=sub.id,reason=payload.reason,comment=payload.comment.strip()))
        else:
            if sub.lifecycle_status not in {"cancel_scheduled","grace"}: raise shop.HTTPException(409,"Subscription cannot be resumed from its current state")
            sub.scheduled_cancel_at=None; sub.cancelled_at=None; sub.lifecycle_status="active" if (sub.expires_at and sub.expires_at>now) else "grace"
        await shop.audit(db,f"subscription.{payload.action}",f"user:{user.id}",str(sub.id)); await db.commit()
        return {"ok":True,"status":sub.lifecycle_status,"scheduled_cancel_at":sub.scheduled_cancel_at,"grace_until":sub.grace_until}
    finally:
        await shop._release_payment_side_effect_lock(lock,token)

YOOKASSA_METHODS={"bank_card","sbp","yoo_money","sberbank","tinkoff_bank"}

def _money(value) -> shop.Decimal:
    return shop.Decimal(str(value)).quantize(shop.Decimal("0.01"), rounding=shop.ROUND_HALF_UP)

@shop.app.post("/api/me/wallet/topup")
async def wallet_topup(payload:dict, request:shop.Request, db:shop.AsyncSession=shop.Depends(shop.get_db)):
    if await shop.maintenance_enabled(db): raise shop.HTTPException(503,"Service is in maintenance mode")
    if not await shop.feature_enabled(db, "payments", True): raise shop.HTTPException(503,"Платежи отключены администратором")
    requested_provider=str(payload.get("provider") or "").lower()
    sandbox_requested=shop.sandbox_checkout_requested(requested_provider)
    if not sandbox_requested and not await shop.production_payments_allowed(db):
        raise shop.HTTPException(503,"Приём платежей временно остановлен администратором")
    user=await shop.user_from_token(request,db)
    from .app_config import require_consent
    await require_consent(db,user)
    idem=request.headers.get("Idempotency-Key")
    if not idem or len(idem)>128: raise shop.HTTPException(400,"Idempotency-Key is required")
    method=str(payload.get("method") or "")
    if method and method not in shop.YOOKASSA_METHODS: raise shop.HTTPException(400,"Unsupported payment method")
    try:
        amount=shop._money(payload.get("amount"))
    except Exception:
        raise shop.HTTPException(400,"Invalid amount")
    if amount < shop.Decimal("50") or amount > shop.Decimal("100000"):
        raise shop.HTTPException(400,"Amount is outside the allowed top-up range")
    existing=(await db.execute(shop.select(shop.Payment).where(shop.Payment.user_id==user.id,shop.Payment.idempotency_key==idem).order_by(shop.Payment.id.desc()))).scalar_one_or_none()
    if existing:
        if (existing.purpose or "subscription") != "topup":
            raise shop.HTTPException(409,"Idempotency-Key уже использован для другого платежа")
        return {"id":existing.provider_payment_id,"url":existing.checkout_url,"provider":existing.provider,"status":existing.status,"purpose":"topup"}
    await shop.ensure_required_channel(user)
    routed={"bank_card":"card","sbp":"sbp"}.get(method) or (str(payload.get("pay_method") or "") or None)
    provider_order=await shop._payment_provider_order(db,payload.get("provider"),*([routed] if routed else []))
    if not provider_order: raise shop.HTTPException(503,"Нет доступных платёжных провайдеров")
    candidate=provider_order[0]
    # Every routable gateway (a reserve one may be first in line while the main one cools down).
    from .payments_api import _checkout_provider
    provider=_checkout_provider(candidate)
    order_id=f"topup-{user.id}-{shop.hashlib.sha256(idem.encode()).hexdigest()[:24]}"
    row=shop.Payment(user_id=user.id,plan_id=0,provider=candidate,order_id=order_id,amount=amount,original_amount=amount,discount_amount=shop.Decimal("0.00"),currency=shop.settings.default_currency,status="creating",fulfillment_status="pending",idempotency_key=idem,purpose="topup",bonus_days=0)
    db.add(row); await db.commit(); await db.refresh(row)
    try:
        back=shop._return_url(order_id,request=request)
        meta={"order_id":order_id,"user_id":user.id,"email":user.email,"return_url":back,"cancel_url":back}
        if candidate in {"stripe","paypal","crypto"}: result=await provider.create(amount,shop.settings.default_currency,"Wallet top-up",meta)
        elif candidate=="yookassa" and method: result=await provider.create(amount,order_id,"Wallet top-up",shop._return_url(order_id,shop.settings.mini_app_url,request),method=method)
        else: result=await provider.create(amount,order_id,"Wallet top-up",shop._return_url(order_id,shop.settings.mini_app_url,request))
        if not result.get("id"): raise RuntimeError("Payment provider returned no payment ID")
        row=(await db.execute(shop.select(shop.Payment).where(shop.Payment.id==row.id).with_for_update())).scalar_one()
        row.provider_payment_id=result["id"]; row.checkout_url=result.get("url")
        if candidate=="sandbox" and result.get("status")=="succeeded":
            row.status="paid"; row.paid_at=shop.datetime.utcnow(); await db.commit()
            try:
                await shop.fulfill(row.id, db)
            except Exception:
                shop.logger.exception("Sandbox wallet top-up fulfillment failed for payment %s", row.id)
            fresh=await db.get(shop.Payment, row.id)
            return {"id":result.get("id"),"url":result.get("url"),"provider":candidate,"status": None if fresh is None else fresh.status,"fulfillment_status": None if fresh is None else fresh.fulfillment_status,"purpose":"topup"}
        row.status="pending"
        await db.commit()
        return {"id":result.get("id"),"url":result.get("url"),"provider":candidate,"status":"pending","purpose":"topup"}
    except Exception as exc:
        row=(await db.execute(shop.select(shop.Payment).where(shop.Payment.id==row.id).with_for_update())).scalar_one()
        row.status="creation_unknown"; row.fulfillment_terminal=True; row.fulfillment_error=str(exc)[:1000]
        await db.commit()
        raise shop.HTTPException(503,"Результат создания платежа не определён. Повторное списание заблокировано; операция будет сверена.")

@shop.app.post("/api/me/wallet/spend")
async def wallet_spend(payload:dict, request:shop.Request, db:shop.AsyncSession=shop.Depends(shop.get_db)):
    if await shop.maintenance_enabled(db): raise shop.HTTPException(503,"Service is in maintenance mode")
    user=await shop.user_from_token(request,db)
    return await spend_from_wallet(db,user,payload,request.headers.get("Idempotency-Key"))


async def spend_from_wallet(db:shop.AsyncSession,user:shop.User,payload:dict,idem:str|None):
    """A purchase paid from the wallet; also used by the smart cart and daily plans (the same checks and ledger)."""
    from .platform_api import reject_restricted
    reject_restricted(user)
    from .app_config import require_consent
    await require_consent(db,user)
    constructor_requested=payload.get("constructor_id") not in (None, "", 0, "0")
    constructor_quote=None
    quote_error=None
    plan_id=None
    if constructor_requested:
        from .tariff_api import quote_constructor
        try:
            constructor_quote=await quote_constructor(db, payload)
            plan_id=int(constructor_quote["plan_id"])
        except shop.HTTPException as exc:
            quote_error=exc
    else:
        try:
            plan_id=int(payload.get("plan_id"))
        except (TypeError, ValueError):
            raise shop.HTTPException(400,"Invalid plan_id")
    if not idem or len(idem)>128: raise shop.HTTPException(400,"Idempotency-Key is required")
    existing=(await db.execute(shop.select(shop.Payment).where(shop.Payment.user_id==user.id,shop.Payment.idempotency_key==idem))).scalar_one_or_none()
    if existing:
        shop.check_retry(existing,payload)
        from .partners import check_retry as check_partner_retry
        check_partner_retry(existing,payload)
        if existing.provider != "wallet":
            raise shop.HTTPException(409,"Idempotency-Key уже использован для другого платежа")
        if constructor_quote and (existing.plan_id != plan_id or existing.duration_days_snapshot != constructor_quote["days"] or existing.traffic_limit_gb_snapshot != constructor_quote["traffic_gb"] or existing.device_limit_snapshot != constructor_quote["devices"]):
            raise shop.HTTPException(409,"Idempotency-Key уже использован для другой конфигурации тарифа")
        elif plan_id is not None and existing.plan_id != plan_id:
            raise shop.HTTPException(409,"Idempotency-Key уже использован для другого платежа")
        return {"ok":True,"payment_id":existing.id,"status":existing.status,"fulfillment_status":existing.fulfillment_status}
    if quote_error:
        raise quote_error
    if plan_id is None:
        raise shop.HTTPException(400,"Invalid plan_id")
    await shop.ensure_required_channel(user)
    plan=await db.get(shop.Plan,plan_id)
    if not plan or not plan.enabled: raise shop.HTTPException(404,"Not found")
    from .partners import checkout_terms
    partner_terms=await checkout_terms(db,payload.get("reseller_slug"),plan.id,user.id)
    from .tariff_api import linked_constructor_id
    linked=await linked_constructor_id(db, plan.id)
    if linked and (not constructor_quote or int(constructor_quote["constructor_id"]) != int(linked)):
        raise shop.HTTPException(400,"Этот тариф собирается в конструкторе")
    if constructor_quote:
        base_amount=shop.Decimal(str(constructor_quote["amount"]))
        snap_days=int(constructor_quote["days"])
        snap_traffic=constructor_quote["traffic_gb"]
        snap_devices=int(constructor_quote["devices"])
        snap_profile=constructor_quote["profile_id"]
    else:
        base_amount=shop.Decimal(str(plan.price))
        snap_days=plan.duration_days
        snap_traffic=plan.traffic_limit_gb
        snap_devices=plan.device_limit
        snap_profile=plan.remnawave_profile_id
    promo, promo_discount_amount=await shop.promo_discount(db,payload.get("promo_code"),plan.id,base_amount,user.id)
    if promo is None:
        promotion=await shop.active_promotion(db,plan.id)
        discount_amount=shop.discounted_amount(base_amount,promotion.kind,promotion.value) if promotion else shop.Decimal("0.00")
    else:
        promotion=None; discount_amount=promo_discount_amount
    final_amount=shop._money(base_amount-discount_amount)
    bonus_days=int(shop.Decimal(str(promo.value))) if promo is not None and promo.kind=="days" else (int(shop.Decimal(str(promotion.value))) if promotion is not None and promotion.kind=="days" else 0)
    if final_amount <= 0: raise shop.HTTPException(400,"Amount must be positive")
    lock,token=await shop._acquire_user_fulfillment_lock(user.id,ttl=900)
    try:
        user=(await db.execute(shop.select(shop.User).where(shop.User.id==user.id).execution_options(populate_existing=True).with_for_update())).scalar_one()
        reject_restricted(user)
        existing=(await db.execute(shop.select(shop.Payment).where(shop.Payment.user_id==user.id,shop.Payment.idempotency_key==idem).with_for_update())).scalar_one_or_none()
        if existing:
            shop.check_retry(existing,payload)
            from .partners import check_retry as check_partner_retry
            check_partner_retry(existing,payload)
            return {"ok":True,"payment_id":existing.id,"status":existing.status,"fulfillment_status":existing.fulfillment_status}
        target=await shop.reserve_target(db,user,plan.id,payload)
        cutoff=shop.datetime.utcnow()-shop.timedelta(seconds=30)
        duplicate_filters=[shop.Payment.user_id==user.id,shop.Payment.subscription_id==target.id,shop.Payment.provider=="wallet",shop.Payment.purpose=="subscription",shop.Payment.plan_id==plan.id,shop.Payment.amount==final_amount,shop.Payment.duration_days_snapshot==snap_days,shop.Payment.traffic_limit_gb_snapshot==snap_traffic,shop.Payment.device_limit_snapshot==snap_devices,shop.Payment.created_at>=cutoff,shop.Payment.status.notin_(["failed","canceled","cancelled","refunded","refunded_pending_revoke"])]
        duplicate_filters.append(shop.Payment.promo_code==promo.code if promo is not None else shop.Payment.promo_code.is_(None))
        duplicate=(await db.execute(shop.select(shop.Payment).where(*duplicate_filters).order_by(shop.Payment.id.desc()))).scalars().first()
        if duplicate:
            raise shop.HTTPException(409,"Повторное списание с баланса заблокировано. Подождите полминуты и повторите покупку.")
        balance=shop._money(user.wallet_balance or 0)
        if balance < final_amount: raise shop.HTTPException(402,"Недостаточно средств на балансе")
        order_id=f"wallet-{user.id}-{plan.id}-{shop.hashlib.sha256(idem.encode()).hexdigest()[:24]}"
        reservation=await shop.reserve_promo(db,promo,user.id,order_id)
        row=shop.Payment(user_id=user.id,subscription_id=target.id,new_subscription=bool(payload.get("new_subscription",False)),plan_id=plan.id,provider="wallet",order_id=order_id,amount=final_amount,original_amount=base_amount,discount_amount=discount_amount,duration_days_snapshot=snap_days,traffic_limit_gb_snapshot=snap_traffic,device_limit_snapshot=snap_devices,remnawave_profile_id_snapshot=snap_profile,referrer_id_snapshot=user.referred_by_id,referral_terms_snapshot=await shop.referral_snapshot(db,user),promo_code=(promo.code if promo else None),currency=shop.settings.default_currency,status="paid",fulfillment_status="pending",idempotency_key=idem,purpose="subscription",bonus_days=bonus_days,paid_at=shop.datetime.utcnow(),**partner_terms)
        user.wallet_balance=shop._money(balance-final_amount)
        db.add(row); await db.flush()
        if reservation:reservation.payment_id=row.id
        await shop.record_financial_event(db,operation_key=f"wallet-spend:{row.id}",user_id=user.id,payment_id=row.id,kind="wallet_spend",direction="debit",amount=final_amount,currency=row.currency,metadata={"plan_id":plan.id})
        await db.commit()
        try:
            await shop.fulfill(row.id, db, existing_user_lock_token=token)
        except Exception:
            return {"ok":True,"payment_id":row.id,"fulfillment":"queued","wallet_balance":str(user.wallet_balance)}
        return {"ok":True,"payment_id":row.id,"wallet_balance":str(user.wallet_balance)}
    finally:
        await shop._release_payment_side_effect_lock(lock,token)

@shop.app.post("/api/me/gifts/purchase")
async def purchase_gift(payload:dict,request:shop.Request,db:shop.AsyncSession=shop.Depends(shop.get_db)):
    from .gift_orders import purchase_gift as purchase
    return await purchase(payload,request,db)

@shop.app.post("/api/me/gifts/redeem")
async def redeem_gift(payload:shop.GiftRedeemIn,request:shop.Request,db:shop.AsyncSession=shop.Depends(shop.get_db)):
    from .gift_orders import redeem_gift as redeem
    return await redeem(payload,request,db)

@shop.app.post("/api/me/referral/apply")
async def apply_referral(payload:dict,request:shop.Request,db:shop.AsyncSession=shop.Depends(shop.get_db)):
    user=await shop.user_from_token(request,db)
    user=(await db.execute(shop.select(shop.User).where(shop.User.id==user.id).with_for_update())).scalar_one()
    from .referrals import bind_referrer
    referrer_id=await bind_referrer(db,user,str(payload.get("code") or ""))
    await db.commit(); return {"ok":True,"referrer_id":referrer_id}


@shop.app.get("/api/me/auto-renew")
async def auto_renew_status(request:shop.Request,db:shop.AsyncSession=shop.Depends(shop.get_db)):
    user=await shop.user_from_token(request,db); method=(await db.execute(shop.select(shop.AutoRenewMethod).where(shop.AutoRenewMethod.user_id==user.id))).scalar_one_or_none()
    last_error="Автопродление не выполнено" if method and method.last_error else None
    sub=await shop.owned_subscription(db,user.id)
    from .subscriptions import renewal_terms
    plan=await db.get(shop.Plan,sub.plan_id) if sub else None
    terms=await renewal_terms(db,sub,plan) if sub and plan else None
    return {"enabled":bool(sub and sub.auto_renew_enabled),"configured":bool(method and method.enabled and method.provider == "yookassa"),"provider":method.provider if method else None,"last_attempt_at":method.last_attempt_at if method else None,"last_success_at":method.last_success_at if method else None,"last_error":last_error,"supported_providers":["yookassa"],
        "renewal_terms":{k:v for k,v in terms.items() if k!='profile_id'} if terms else None}

@shop.app.get("/api/me/connection-qr")
async def connection_qr(request:shop.Request,db:shop.AsyncSession=shop.Depends(shop.get_db)):
    user=await shop.user_from_token(request,db); sub=(await db.execute(shop.select(shop.Subscription).where(shop.Subscription.user_id==user.id,shop.Subscription.is_primary.is_(True)))).scalar_one_or_none()
    url=(client_url(sub.subscription_url) or "").strip() if sub else ""
    if not url or any(ch in url for ch in "\r\n\x00"): raise shop.HTTPException(404,"Subscription is not available")
    import io, qrcode
    img=qrcode.make(url); buf=io.BytesIO(); img.save(buf,format="PNG")
    return shop.Response(content=buf.getvalue(),media_type="image/png",headers={"Cache-Control":"private, no-store"})

@shop.app.get("/api/me/subscription-file")
async def subscription_file(request:shop.Request,db:shop.AsyncSession=shop.Depends(shop.get_db)):
    user=await shop.user_from_token(request,db); sub=(await db.execute(shop.select(shop.Subscription).where(shop.Subscription.user_id==user.id,shop.Subscription.is_primary.is_(True)))).scalar_one_or_none()
    url=(client_url(sub.subscription_url) or "").strip() if sub else ""
    if not url or any(ch in url for ch in "\r\n\x00"): raise shop.HTTPException(404,"Subscription is not available")
    return shop.Response(content=(url+"\n").encode(),media_type="text/plain; charset=utf-8",headers={"Cache-Control":"private, no-store","Content-Disposition":'attachment; filename="remnawave-subscription.txt"'})

@shop.app.get("/api/me/connection-info")
async def connection_info(request:shop.Request,db:shop.AsyncSession=shop.Depends(shop.get_db)):
    user=await shop.user_from_token(request,db); sub=(await db.execute(shop.select(shop.Subscription).where(shop.Subscription.user_id==user.id,shop.Subscription.is_primary.is_(True)))).scalar_one_or_none()
    guides={}
    accept=(request.headers.get("accept-language") or "").lower()
    guide_lang="en" if accept.startswith("en") else "ru"
    defaults={
        "ru":{
            "android":"Android: установите v2RayTun / Happ / Streisand, вставьте ссылку подписки и подключитесь.",
            "ios":"iOS: установите Streisand или Happ из App Store, импортируйте ссылку подписки и включите VPN.",
            "tv":"TV: откройте VPN-клиент на телевизоре, добавьте подписку по ссылке или через QR с телефона.",
            "windows":"Windows: установите Hiddify / v2rayN, импортируйте ссылку подписки и запустите соединение.",
            "macos":"macOS: установите Hiddify / Streisand, импортируйте ссылку подписки и подключитесь.",
            "linux":"Linux: используйте Hiddify / Nekoray, импортируйте URI подписки и активируйте профиль.",
        },
        "en":{
            "android":"Android: install v2RayTun, Happ or Streisand, import the subscription link and connect.",
            "ios":"iOS: install Streisand or Happ from the App Store, import the subscription link and turn the VPN on.",
            "tv":"TV: open the VPN client on the television, add the subscription by link or by a phone QR code.",
            "windows":"Windows: install Hiddify or v2rayN, import the subscription link and start the connection.",
            "macos":"macOS: install Hiddify or Streisand, import the subscription link and connect.",
            "linux":"Linux: use Hiddify or Nekoray, import the subscription URI and enable the profile.",
        },
    }[guide_lang]
    for key in ("android","ios","tv","windows","macos","linux"):
        row=(await db.execute(shop.select(shop.AppSetting).where(shop.AppSetting.key==f"guide_{key}"))).scalar_one_or_none()
        guides[key]=row.value if row and row.value else defaults[key]
    raw=(client_url(sub.subscription_url) or "").strip() if sub else ""
    safe_url=raw if raw and not any(ch in raw for ch in "\r\n\x00") else None
    return shop.Response(content=shop.json.dumps({"subscription_url":safe_url,"expires_at":sub.expires_at.isoformat() if sub and sub.expires_at else None,"platforms":guides},ensure_ascii=False),media_type="application/json",headers={"Cache-Control":"private, no-store"})

@shop.app.put("/api/me/auto-renew")
async def set_auto_renew(payload:dict,request:shop.Request,db:shop.AsyncSession=shop.Depends(shop.get_db)):
    user=await shop.user_from_token(request,db)
    if not isinstance(payload.get('enabled'),bool):raise shop.HTTPException(400,'enabled must be boolean')
    enabled=payload['enabled']
    user=await db.scalar(shop.select(shop.User).where(shop.User.id==user.id).execution_options(populate_existing=True).with_for_update())
    if not user or user.deleted_at:raise shop.HTTPException(409,'Аккаунт недоступен')
    method=(await db.execute(shop.select(shop.AutoRenewMethod).where(shop.AutoRenewMethod.user_id==user.id).execution_options(populate_existing=True).with_for_update())).scalar_one_or_none()
    if enabled and (not method or not method.enabled or method.provider != "yookassa"): raise shop.HTTPException(409,"No supported recurring payment method is configured")
    sub=await shop.owned_subscription(db,user.id,lock=True)
    if not sub:raise shop.HTTPException(404,"Подписка не найдена")
    if enabled:
        from .subscriptions import FAMILY_TARGET,is_family_subscription
        if await is_family_subscription(db,sub.id):raise shop.HTTPException(409,FAMILY_TARGET)
        from .subscriptions import renewal_terms
        plan=await db.get(shop.Plan,sub.plan_id)
        terms=await renewal_terms(db,sub,plan) if plan else None
        if not terms or terms.get('currency')!=shop.settings.default_currency:
            raise shop.HTTPException(409,'Условия продления недоступны. Сначала явно купите или измените эту подписку.')
    sub.auto_renew_enabled=enabled
    if enabled:sub.next_renewal_at=None
    await db.flush()
    user.auto_renew_enabled=bool(await db.scalar(shop.select(shop.func.count()).select_from(shop.Subscription).where(shop.Subscription.user_id==user.id,shop.Subscription.auto_renew_enabled.is_(True))))
    await db.commit();return {"enabled":enabled,"configured":bool(method and method.enabled)}

@shop.app.delete("/api/me/auto-renew/method")
async def remove_auto_renew_method(request:shop.Request,db:shop.AsyncSession=shop.Depends(shop.get_db)):
    user=await shop.user_from_token(request,db)
    user=await db.scalar(shop.select(shop.User).where(shop.User.id==user.id).execution_options(populate_existing=True).with_for_update())
    if not user or user.deleted_at:raise shop.HTTPException(409,'Аккаунт недоступен')
    method=(await db.execute(shop.select(shop.AutoRenewMethod).where(shop.AutoRenewMethod.user_id==user.id).execution_options(populate_existing=True).with_for_update())).scalar_one_or_none()
    if method: await db.delete(method)
    await db.execute(__import__("sqlalchemy").update(shop.Subscription).where(shop.Subscription.user_id==user.id).values(auto_renew_enabled=False))
    user.auto_renew_enabled=False; await db.commit(); return {"ok":True,"enabled":False}

@shop.app.get("/api/me/payments")
async def my_payments(request:shop.Request,db:shop.AsyncSession=shop.Depends(shop.get_db)):
    user=await shop.user_from_token(request,db); rows=(await db.execute(shop.select(shop.Payment).where(shop.Payment.user_id==user.id).order_by(shop.Payment.id.desc()).limit(100))).scalars().all()
    return [{"id":p.id,"provider":p.provider,"amount":float(p.amount),"currency":p.currency,"status":p.status,"fulfillment_status":p.fulfillment_status,"created_at":p.created_at,"paid_at":p.paid_at} for p in rows]

@shop.app.get("/api/me/referral/ledger")
async def my_referral_ledger(request:shop.Request,db:shop.AsyncSession=shop.Depends(shop.get_db)):
    from .models import ReferralLevelReward
    user=await shop.user_from_token(request,db)
    rows=(await db.execute(shop.select(shop.ReferralLedger, ReferralLevelReward.payment_id).outerjoin(
        ReferralLevelReward, shop.ReferralLedger.referral_level_reward_id==ReferralLevelReward.id).where(
        shop.ReferralLedger.user_id==user.id).order_by(shop.ReferralLedger.id.desc()).limit(100))).all()
    return [{"id":x.id,"amount":float(x.amount),"kind":x.kind,"payment_id":x.payment_id or extra_payment_id,"created_at":x.created_at} for x,extra_payment_id in rows]


@shop.app.get("/api/me/referral")
async def my_referral(request:shop.Request,db:shop.AsyncSession=shop.Depends(shop.get_db)):
    from .referral_program import percentages
    from .models import ReferralLevelReward
    user=await shop.user_from_token(request,db)
    count=int(await db.scalar(shop.select(shop.func.count(shop.func.distinct(shop.ReferralReward.referred_user_id))).where(shop.ReferralReward.referrer_id==user.id, shop.ReferralReward.status=="credited")) or 0)
    direct=await db.scalar(shop.select(shop.func.coalesce(shop.func.sum(shop.ReferralReward.amount),0)).where(shop.ReferralReward.referrer_id==user.id, shop.ReferralReward.status=="credited")) or shop.Decimal("0")
    extra=await db.scalar(shop.select(shop.func.coalesce(shop.func.sum(ReferralLevelReward.amount),0)).where(ReferralLevelReward.referrer_id==user.id, ReferralLevelReward.status=="credited")) or shop.Decimal("0")
    rates=[str(x) for x in await percentages(db)]
    return {"code":user.referral_code,"referred_count":count,"reward_total":float(direct+extra),"balance":float(user.referral_balance or 0),"reward_percent":float(rates[0]),"level_percentages":rates}


__all__ = ['YOOKASSA_METHODS', 'spend_from_wallet', '_money', 'apply_referral', 'auto_renew_status', 'billing_center', 'connection_info', 'connection_qr', 'my_payments', 'my_referral', 'my_referral_ledger', 'my_subscription', 'purchase_gift', 'redeem_gift', 'remove_auto_renew_method', 'security_center', 'set_auto_renew', 'subscription_file', 'subscription_lifecycle', 'wallet_spend', 'wallet_topup']
# Imported before main finished (``from app import customer_api`` first)? Then main's star
# import saw a half-loaded module; hand the names over now that they exist.
shop.__dict__.update({_n: globals()[_n] for _n in __all__})
