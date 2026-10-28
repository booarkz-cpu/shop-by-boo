"""Payments: checkout, provider webhooks, fulfillment, provisioning, renewals and refunds (moved from main.py in v28.32.0).

Names that belong to main are read through ``shop.<name>`` at call time, so tests and
operators that patch ``app.main`` keep affecting this code exactly as before."""
from . import main as shop

# ---------- Payments ----------
async def _advisory_lock(db: shop.AsyncSession, key: int) -> None:
    """Serialize PostgreSQL writes while keeping SQLite test/dev mode portable."""
    bind = getattr(db, "bind", None)
    if bind is None:
        bind = getattr(getattr(db, "sync_session", None), "bind", None)
    if bind is not None and bind.dialect.name == "postgresql":
        await db.execute(shop.sql_text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})

def provider_configured() -> dict[str, bool]:
    """Which gateways have the credentials needed to create a payment (shared by checkout and the admin queue)."""
    return {
        "yookassa": bool(shop.settings.yookassa_shop_id and shop.settings.yookassa_secret_key and shop.settings.yookassa_webhook_ip_allowlist),
        "platega": bool(shop.settings.platega_merchant_id and shop.settings.platega_secret),
        "rollypay": bool(shop.settings.rollypay_api_key and shop.settings.rollypay_signing_secret),
        "cryptobot": bool(shop.settings.cryptobot_token),
        "freekassa": shop.FreekassaProvider.configured(),
        "sandbox": shop.payments_sandbox_allowed(),
    }

def _checkout_provider(name: str):
    """One map for every routable gateway: a reserve gateway first in line (main one in cooldown) must work."""
    factories={"yookassa":shop.YooKassaProvider,"platega":shop.PlategaProvider,"rollypay":shop.RollyPayProvider,"cryptobot":shop.CryptoBotProvider,"freekassa":shop.FreekassaProvider,"sandbox":shop.SandboxProvider}
    return factories[name]()

async def _payment_provider_order(db: shop.AsyncSession, requested: str|None, method: str|None=None):
    names=shop.routing_names(shop.payments_sandbox_allowed())
    # Provider health rows are lazily bootstrapped. Serialize that bootstrap so
    # concurrent first requests cannot race into a unique-constraint failure.
    await shop._advisory_lock(db, 1300000002)
    if requested and requested not in names: raise shop.HTTPException(400,"Unsupported provider")
    # A fresh database has no provider-health rows until the admin opens the
    # feature-flags page. Payment availability must not depend on visiting an
    # unrelated admin screen, so bootstrap the provider-health records lazily.
    rows=(await db.execute(shop.select(shop.PaymentProviderHealth).order_by(shop.PaymentProviderHealth.priority,shop.PaymentProviderHealth.provider).with_for_update())).scalars().all()
    existing={x.provider for x in rows}
    for i,p in enumerate((*shop.PAYMENT_AGENTS, "sandbox") if shop.payments_sandbox_allowed() else shop.PAYMENT_AGENTS,1):
        if p not in existing:
            row=shop.PaymentProviderHealth(provider=p,priority=i*10,enabled=True)
            db.add(row); rows.append(row)
    if any(x.provider not in names for x in rows):
        rows=[x for x in rows if x.provider in names]
    await db.flush()
    rows=sorted(rows,key=lambda x:(x.priority,x.provider))
    now=shop.datetime.utcnow()
    # A provider is routable only when it is explicitly enabled, outside the
    # circuit-breaker cooldown, and has the credentials required to create a
    # payment.  Previously `enabled` was accidentally ignored here, so an
    # operator could disable a provider in the admin panel and checkout would
    # still select it.  Empty credentials also caused a late failure after the
    # customer had already started checkout.
    configured = provider_configured()
    enabled=[x.provider for x in rows
             if x.provider in names
             and x.enabled
             and configured.get(x.provider, False)
             and (not x.circuit_open_until or x.circuit_open_until <= now)]
    if method:
        # The customer chose СБП / card / crypto: that method's own chain (payment_methods.py), when routing is on.
        from .payment_methods import load as load_routing, order_for
        routing=await load_routing(db)
        if routing["enabled"]:
            enabled=order_for(routing, method, enabled)
            if not enabled: raise shop.HTTPException(503,"Этот способ оплаты сейчас недоступен — выберите другой")
            if requested not in enabled: requested=None
    if requested:
        if requested not in enabled: raise shop.HTTPException(503,"Выбранный платёжный провайдер отключён или временно недоступен")
        return [requested]+[x for x in enabled if x!=requested]
    return enabled

async def reserve_promo(db:shop.AsyncSession, promo:shop.PromoCode|None, user_id:int, order_id:str):
    if not promo:
        return None
    row=(await db.execute(shop.select(shop.PromoCode).where(shop.PromoCode.id==promo.id).execution_options(populate_existing=True).with_for_update())).scalar_one()
    from .personal_offers import audience_allowed
    if not row.enabled or not await audience_allowed(db,row.id,user_id,lock=True):raise shop.HTTPException(409,"Промокод больше не доступен этому аккаунту")
    now=shop.datetime.utcnow()
    if row.starts_at and now<row.starts_at or row.ends_at and now>row.ends_at:raise shop.HTTPException(409,"Срок промокода истёк")
    if row.max_uses_per_user is not None:
        used=int(await db.scalar(shop.select(shop.func.count(shop.PromoRedemption.id)).where(shop.PromoRedemption.promo_code_id==row.id,shop.PromoRedemption.user_id==user_id)) or 0)
        reserved=int(await db.scalar(shop.select(shop.func.count(shop.PromoReservation.id)).where(shop.PromoReservation.promo_code_id==row.id,shop.PromoReservation.user_id==user_id,shop.PromoReservation.status=="reserved")) or 0)
        if used+reserved>=row.max_uses_per_user:raise shop.HTTPException(409,"Лимит промокода для этого клиента исчерпан")
    active_reserved=int(row.reserved_count or 0)
    if row.usage_limit is not None and int(row.used_count or 0)+active_reserved >= row.usage_limit:
        raise shop.HTTPException(409,"Лимит промокода исчерпан")
    row.reserved_count=active_reserved+1
    reservation=shop.PromoReservation(promo_code_id=row.id,user_id=user_id,order_id=order_id,status="reserved",expires_at=shop.datetime.utcnow()+shop.timedelta(hours=24))
    db.add(reservation); await db.flush()
    return reservation


async def release_promo_reservation(db:shop.AsyncSession, reservation_id:int):
    reservation=(await db.execute(shop.select(shop.PromoReservation).where(shop.PromoReservation.id==reservation_id).with_for_update())).scalar_one_or_none()
    if not reservation or reservation.status!="reserved":
        return False
    promo=(await db.execute(shop.select(shop.PromoCode).where(shop.PromoCode.id==reservation.promo_code_id).with_for_update())).scalar_one_or_none()
    if promo: promo.reserved_count=max(0,int(promo.reserved_count or 0)-1)
    reservation.status="released"
    return True


async def ensure_required_channel(user:shop.User, scope:str="buy"):
    """Required channels of the scope (channel_gate.py: several channels, «везде / пробный / покупки»)."""
    from .channel_gate import ensure
    await ensure(user, scope)

@shop.app.post("/api/payments/create")
async def create_payment(payload:dict, request:shop.Request, db:shop.AsyncSession=shop.Depends(shop.get_db)):
    if await shop.maintenance_enabled(db): raise shop.HTTPException(503,"Service is in maintenance mode")
    if not await shop.feature_enabled(db, "payments", True): raise shop.HTTPException(503,"Платежи отключены администратором")
    sandbox_requested=shop.sandbox_checkout_requested(payload.get("provider"))
    if not sandbox_requested and not await shop.production_payments_allowed(db) and not await shop.e2e_checkout_allowed(db,request,payload):
        raise shop.HTTPException(503,"Приём платежей временно остановлен администратором")
    user=await shop.user_from_token(request,db)
    from .platform_api import reject_restricted
    reject_restricted(user)
    if not await shop.e2e_checkout_allowed(db,request,payload):
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
    idem=request.headers.get("Idempotency-Key")
    if not idem or len(idem)>128: raise shop.HTTPException(400,"Idempotency-Key is required")

    # Resolve an existing durable intent before re-validating mutable commercial state.
    # An idempotent retry must remain recoverable even after a promo expires, is disabled,
    # or its usage counter changes. The immutable Payment snapshot is the source of truth
    # for an already-created intent.
    existing=(await db.execute(shop.select(shop.Payment).where(shop.Payment.user_id==user.id,shop.Payment.idempotency_key==idem).order_by(shop.Payment.id.desc()))).scalar_one_or_none()
    if existing:
        shop.check_retry(existing,payload)
        from .partners import check_retry as check_partner_retry
        check_partner_retry(existing,payload)
        if existing.plan_id != plan_id:
            if not (quote_error is not None and plan_id is None):
                raise shop.HTTPException(409,"Idempotency-Key уже использован для другого платежа")
        if constructor_quote and (existing.duration_days_snapshot != constructor_quote["days"] or existing.traffic_limit_gb_snapshot != constructor_quote["traffic_gb"] or existing.device_limit_snapshot != constructor_quote["devices"]):
            raise shop.HTTPException(409,"Idempotency-Key уже использован для другой конфигурации тарифа")
        if existing.provider_payment_id or existing.status not in {"creating","creation_unknown"}:
            return {"id":existing.provider_payment_id,"url":existing.checkout_url,"provider":existing.provider,"status":existing.status}
        # An unresolved intent has already reserved the commercial terms. Do not recompute
        # price/promo from mutable Plan/PromoCode rows during recovery.
        final_amount=shop.Decimal(str(existing.amount))
        expected_promo=existing.promo_code
        if existing.provider != "yookassa":
            raise shop.HTTPException(409,"Платёж создаётся/имеет неопределённый результат; повторное списание заблокировано. Требуется сверка операции.")
        provider=shop.YooKassaProvider()
        lock_key=f"lock:payment-create:{shop.hashlib.sha256(existing.order_id.encode()).hexdigest()}"
        try:
            lock_key, lock_token=await shop._acquire_redis_lock(lock_key,ttl=300,conflict_message="Payment creation is already in progress")
        except RuntimeError as exc:
            raise shop._lock_conflict(exc, "Payment creation is already in progress") from exc
        try:
            result=await provider.create(final_amount,existing.order_id,f"VPN plan {existing.plan_id}",shop.settings.mini_app_url)
            if not result.get("id"):
                raise RuntimeError("YooKassa returned no payment ID")
            existing.provider_payment_id=result["id"]; existing.status="pending"; existing.checkout_url=result.get("url"); await db.commit()
            return result
        except Exception as exc:
            await db.rollback()
            existing=(await db.execute(shop.select(shop.Payment).where(shop.Payment.id==existing.id).with_for_update())).scalar_one()
            existing.status="creation_unknown"; existing.fulfillment_terminal=True; existing.fulfillment_error=str(exc)[:2000]
            await shop.audit(db,"payment.creation.uncertain",str(user.id),str(existing.id),{"provider":existing.provider,"error":str(exc)[:500]}); await db.commit()
            raise shop.HTTPException(503,"Результат создания платежа не определён. Повторное списание заблокировано; операция будет сверена.")
        finally:
            await shop._release_payment_side_effect_lock(lock_key,lock_token)

    # No durable intent exists for this idempotency key, so mutable commercial state
    # is now safe to validate for a brand-new checkout.
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
    final_amount=(base_amount-discount_amount).quantize(shop.Decimal("0.01"),rounding=shop.ROUND_HALF_UP)
    if final_amount<=0: raise shop.HTTPException(400,"Amount must be positive")
    risk_score,risk_decision,risk_signals=await shop._risk_score(db,user,final_amount,request)
    if risk_decision=="block":
        raise shop.HTTPException(403,"Платёж отклонён системой защиты от мошенничества")
    bonus_days=0
    if promo is not None and promo.kind=="days":
        bonus_days=int(shop.Decimal(str(promo.value)))
    elif promotion is not None and promotion.kind=="days":
        bonus_days=int(shop.Decimal(str(promotion.value)))
    expected_promo=promo.code if promo else None
    config_tag=""
    if constructor_quote:
        config_tag=f":c{constructor_quote['constructor_id']}:dev{constructor_quote['devices']}:tr{constructor_quote['traffic_gb']}:days{constructor_quote['days']}"
    idem_fingerprint=f"{user.id}:{plan.id}:{idem}:{promo.code if promo else promotion.id if promotion else ''}{config_tag}"
    canonical_order_id=f"vpn-{user.id}-{plan.id}-{shop.hashlib.sha256(idem_fingerprint.encode()).hexdigest()[:24]}"

    # A fresh Idempotency-Key must not open a second provider session while this
    # buyer already has an unresolved checkout for the same commercial snapshot.
    intent_lock_key=f"lock:checkout-intent:{user.id}"
    try:
        intent_lock_key, intent_token=await shop._acquire_redis_lock(intent_lock_key,ttl=60,conflict_message="Payment creation is already in progress")
    except RuntimeError as exc:
        raise shop.HTTPException(409,"Payment creation is already in progress") from exc
    try:
        target=await shop.reserve_target(db,user,plan.id,payload)
        open_recent=(await db.execute(shop.select(shop.Payment).where(shop.Payment.user_id==user.id,shop.Payment.subscription_id==target.id,shop.Payment.purpose=="subscription",shop.Payment.provider!="wallet",shop.Payment.plan_id==plan.id,shop.Payment.amount==final_amount,shop.Payment.duration_days_snapshot==snap_days,shop.Payment.traffic_limit_gb_snapshot==snap_traffic,shop.Payment.device_limit_snapshot==snap_devices,shop.Payment.status.in_(["creating","pending","creation_unknown"]),shop.Payment.created_at>=shop.datetime.utcnow()-shop.timedelta(seconds=30)).order_by(shop.Payment.id.desc()))).scalars().first()
        if open_recent:
            if open_recent.status=="pending" and open_recent.provider_payment_id:
                return {"id":open_recent.provider_payment_id,"url":open_recent.checkout_url,"provider":open_recent.provider,"status":open_recent.status}
            raise shop.HTTPException(409,"Платёж создаётся/имеет неопределённый результат; повторное списание заблокировано. Требуется сверка операции.")

        # Idempotency lookup already happened above. The order lock below protects the
        # first-time intent creation from concurrent callers using the same key.
        requested_provider=payload.get("provider")
        from .payment_methods import YOOKASSA_TYPES, load as load_routing
        pay_method=str(payload.get("method") or "") or None
        method_hint=YOOKASSA_TYPES.get(pay_method or "") if pay_method and (await load_routing(db))["enabled"] else None
        provider_order=await shop._payment_provider_order(db,requested_provider,*([pay_method] if pay_method else []))
        if not provider_order: raise shop.HTTPException(503,"Нет доступных платёжных провайдеров")
        provider_name=provider_order[0]
        provider=_checkout_provider(provider_name)
        order_id=canonical_order_id
        lock_key=f"lock:payment-create:{shop.hashlib.sha256(canonical_order_id.encode()).hexdigest()}"
        try:
            lock_key, lock_token=await shop._acquire_redis_lock(lock_key,ttl=300,conflict_message="Payment creation is already in progress")
        except RuntimeError:
            existing=(await db.execute(shop.select(shop.Payment).where(shop.Payment.order_id==order_id))).scalar_one_or_none()
            if existing:
                shop.check_retry(existing,payload)
                from .partners import check_retry as check_partner_retry
                check_partner_retry(existing,payload)
                return {"id":existing.provider_payment_id,"url":existing.checkout_url,"provider":existing.provider,"status":existing.status}
            raise shop.HTTPException(409,"Payment creation is already in progress")
        reservation=None; payment_row=None
        try:
            candidate=provider_order[0]
            candidate_provider=_checkout_provider(candidate)
            # Re-check after acquiring the distributed lock so two first-time callers cannot
            # create two durable intents for the same idempotency key.
            existing=(await db.execute(shop.select(shop.Payment).where(shop.Payment.order_id==order_id).execution_options(populate_existing=True).with_for_update())).scalar_one_or_none()
            if existing:
                shop.check_retry(existing,payload)
                from .partners import check_retry as check_partner_retry
                check_partner_retry(existing,payload)
                return {"id":existing.provider_payment_id,"url":existing.checkout_url,"provider":existing.provider,"status":existing.status}
            if promo:
                reservation=await shop.reserve_promo(db,promo,user.id,canonical_order_id)
            # Durable payment intent BEFORE the external provider call. A process crash after
            # provider acceptance cannot erase the fact that this order already exists.
            payment_row=shop.Payment(user_id=user.id,subscription_id=target.id,new_subscription=bool(payload.get("new_subscription",False)),plan_id=plan.id,provider=candidate,provider_payment_id=None,order_id=order_id,amount=final_amount,original_amount=base_amount,discount_amount=discount_amount,duration_days_snapshot=snap_days,traffic_limit_gb_snapshot=snap_traffic,device_limit_snapshot=snap_devices,remnawave_profile_id_snapshot=snap_profile,referrer_id_snapshot=user.referred_by_id,referral_terms_snapshot=await shop.referral_snapshot(db,user),promo_code=(promo.code if promo else None),currency=shop.settings.default_currency,status="creating",fulfillment_status="pending",idempotency_key=idem,purpose="subscription",bonus_days=bonus_days,**partner_terms)
            db.add(payment_row)
            await db.flush()
            db.add(shop.PaymentRiskAssessment(payment_id=payment_row.id,score=risk_score,decision=risk_decision,signals=risk_signals))
            if reservation: reservation.payment_id=payment_row.id
            await db.commit()
            try:
                back=shop._return_url(canonical_order_id,request=request)
                meta={"order_id":canonical_order_id,"user_id":user.id,"email":user.email,"return_url":back,"cancel_url":back}
                if candidate in {"stripe","paypal","crypto"}: result=await candidate_provider.create(final_amount,shop.settings.default_currency,f"VPN {plan.name}",meta)
                elif candidate=="yookassa" and method_hint: result=await candidate_provider.create(final_amount,canonical_order_id,f"VPN {plan.name}",back,method=method_hint)
                else: result=await candidate_provider.create(final_amount,canonical_order_id,f"VPN {plan.name}",back)
                if not result.get("id"):
                    raise RuntimeError("Payment provider returned no payment ID")
                provider_name=candidate; provider=candidate_provider
                health=(await db.execute(shop.select(shop.PaymentProviderHealth).where(shop.PaymentProviderHealth.provider==candidate).with_for_update())).scalar_one_or_none()
                if health:
                    health.success_count += 1; health.failure_count=0; health.last_error=None; health.circuit_open_until=None; health.updated_at=shop.datetime.utcnow()
                await shop._record_provider_metric(db,candidate,attempt=1,success=1,gross=final_amount)
                payment_row=(await db.execute(shop.select(shop.Payment).where(shop.Payment.id==payment_row.id).execution_options(populate_existing=True).with_for_update())).scalar_one()
                payment_row.provider_payment_id=result["id"]; payment_row.checkout_url=result.get("url"); payment_row.fulfillment_terminal=False
                if candidate=="sandbox" and result.get("status")=="succeeded":
                    payment_row.status="pending"; await db.commit()
                    try:
                        await shop._confirm_and_fulfill_payment(payment_row.id, db)
                    except Exception:
                        shop.logger.exception("Sandbox fulfillment failed for payment %s", payment_row.id)
                    fresh=await db.get(shop.Payment, payment_row.id)
                    result={**result, "fulfillment_status": None if fresh is None else fresh.fulfillment_status, "payment_status": None if fresh is None else fresh.status}
                else:
                    payment_row.status="pending"; await db.commit()
            except Exception as exc:
                last_error=str(exc)[:1000]
                await db.rollback()
                health=(await db.execute(shop.select(shop.PaymentProviderHealth).where(shop.PaymentProviderHealth.provider==candidate).with_for_update())).scalar_one_or_none()
                if health:
                    health.failure_count += 1; health.last_error=last_error; health.updated_at=shop.datetime.utcnow()
                await shop._record_provider_metric(db,candidate,attempt=1,failed=1)
                if health and health.failure_count >= 3: health.circuit_open_until=shop.datetime.utcnow()+shop.timedelta(minutes=5)
                payment_row=(await db.execute(shop.select(shop.Payment).where(shop.Payment.id==payment_row.id).execution_options(populate_existing=True).with_for_update())).scalar_one()
                payment_row.status="creation_unknown"; payment_row.fulfillment_terminal=True; payment_row.fulfillment_error=last_error
                await shop.audit(db,"payment.creation.uncertain",str(user.id),str(payment_row.id),{"provider":candidate,"error":last_error,"fallback_blocked":True})
                await db.commit()
                raise shop.HTTPException(503,"Результат создания платежа не определён. Повторное списание заблокировано; операция будет сверена.")
            if result.get("recurring_token") and provider_name == "yookassa" and result.get("status") == "succeeded":
                existing_method=(await db.execute(shop.select(shop.AutoRenewMethod).where(shop.AutoRenewMethod.user_id==user.id).with_for_update())).scalar_one_or_none()
                token_enc=shop.encrypt_secret(str(result["recurring_token"]))
                if existing_method:
                    existing_method.provider="yookassa"; existing_method.external_token_encrypted=token_enc; existing_method.enabled=True
                else:
                    db.add(shop.AutoRenewMethod(user_id=user.id,provider="yookassa",external_token_encrypted=token_enc,enabled=True))
                await db.commit()
            return result
        finally:
            await shop._release_payment_side_effect_lock(lock_key,lock_token)
    finally:
        await shop._release_payment_side_effect_lock(intent_lock_key, intent_token)
_LOCK_RENEW_TASKS: dict[str, shop.asyncio.Task] = {}

async def _renew_redis_lock(key: str, token: str, ttl: int):
    # Keep long-running external side effects serialized even when a Remnawave/provider
    # request takes longer than the initial lease. The token check prevents renewing a
    # lock that has already been acquired by another worker after expiry. The registry
    # entry is also self-cleaned when the renewal task exits unexpectedly, so a caller
    # that hangs or loses Redis cannot leak task references forever.
    interval=max(1, ttl // 3)
    script="if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('expire', KEYS[1], ARGV[2]) else return 0 end"
    try:
        while True:
            await shop.asyncio.sleep(interval)
            if shop.redis_client is None: return
            renewed=await shop.redis_client.eval(script,1,key,token,str(ttl))
            if int(renewed or 0) != 1: return
    except shop.asyncio.CancelledError:
        return
    except Exception as exc:
        shop.logger.warning("Redis lock renewal failed for %s: %s", key, exc)
    finally:
        current=shop.asyncio.current_task()
        if shop._LOCK_RENEW_TASKS.get(token) is current:
            shop._LOCK_RENEW_TASKS.pop(token,None)

async def _acquire_redis_lock(key: str, *, ttl: int, conflict_message: str):
    if shop.redis_client is None:
        raise RuntimeError("Redis is required for distributed locking")
    token=shop.secrets.token_urlsafe(24)
    if not await shop.redis_client.set(key, token, nx=True, ex=ttl):
        raise RuntimeError(conflict_message)
    task=shop.asyncio.create_task(shop._renew_redis_lock(key,token,ttl))
    shop._LOCK_RENEW_TASKS[token]=task
    return key, token

async def _acquire_payment_side_effect_lock(payment_id: int, ttl: int = 300):
    key=f"lock:fulfill:payment:{payment_id}"
    try:
        return await shop._acquire_redis_lock(key,ttl=ttl,conflict_message="Payment side effect is already in progress")
    except RuntimeError:
        raise

async def _release_payment_side_effect_lock(key: str, token: str):
    task=shop._LOCK_RENEW_TASKS.pop(token,None)
    if task:
        task.cancel()
    if shop.redis_client is None:
        return
    try:
        await shop.redis_client.eval("if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end",1,key,token)
    except Exception as exc:
        shop.logger.warning("Non-critical operation failed: %s", exc)

async def _acquire_user_fulfillment_lock(user_id: int, ttl: int = 300):
    key=f"lock:fulfill:user:{user_id}"
    try:
        return await shop._acquire_redis_lock(key,ttl=ttl,conflict_message="User provisioning/deletion is already in progress")
    except RuntimeError as exc:
        raise shop._lock_conflict(exc, "User provisioning/deletion is already in progress") from exc

_SAFE_LOCK_MESSAGES = {
    "Payment creation is already in progress",
    "User provisioning/deletion is already in progress",
    "A backup is already running",
    "Maintenance operation already in progress",
    "Redis is required for distributed locking",
    "Payment side effect is already in progress",
}

def _lock_conflict(exc: BaseException, fallback: str) -> shop.HTTPException:
    message = str(exc)
    if message not in shop._SAFE_LOCK_MESSAGES:
        shop.logger.warning("Unexpected lock error: %s", exc)
        message = fallback
    return shop.HTTPException(409, message)

async def _confirm_and_fulfill_payment(payment_id:int, db:shop.AsyncSession):
    """Confirm a provider-successful payment without ever reviving a refunded payment.

    The user lock is acquired before the payment lock so refund, deletion, auto-renew and
    fulfillment share one critical-section order. The payment is re-read under FOR UPDATE
    immediately before the paid transition; a stale webhook/reconciliation snapshot can
    therefore never move a refunded payment back to paid.
    """
    seed=(await db.execute(shop.select(shop.Payment).where(shop.Payment.id==payment_id))).scalar_one_or_none()
    if not seed:
        raise RuntimeError("Payment not found")
    user_lock,user_token=await shop._acquire_user_fulfillment_lock(seed.user_id,ttl=300)
    confirm_payment_lock=confirm_payment_token=None
    try:
        confirm_payment_lock,confirm_payment_token=await shop._acquire_payment_side_effect_lock(payment_id)
        confirmed=(await db.execute(shop.select(shop.Payment).where(shop.Payment.id==payment_id).execution_options(populate_existing=True).with_for_update())).scalar_one_or_none()
        if not confirmed:
            raise RuntimeError("Payment not found after acquiring locks")
        if confirmed.status in {"refunded","refunded_pending_revoke","creation_unknown"}:
            return {"ok":True,"ignored":True,"reason":"payment_not_eligible"}
        if confirmed.status != "paid":
            confirmed.status="paid"
            confirmed.paid_at=confirmed.paid_at or shop.datetime.utcnow()
            confirmed.fulfillment_status="pending"
            confirmed.fulfillment_terminal=False
            await shop.record_financial_event(db, operation_key=f"payment:{confirmed.id}:paid", user_id=confirmed.user_id, payment_id=confirmed.id, kind="payment", direction="credit", amount=shop.Decimal(str(confirmed.amount)), currency=confirmed.currency, metadata={"provider": confirmed.provider, "order_id": confirmed.order_id})
            await db.commit()
        else:
            await db.commit()
        # Do not hold the payment lock across a second acquisition inside fulfill(); keep
        # the user lock, preserving the global order user -> payment.
        await shop._release_payment_side_effect_lock(confirm_payment_lock,confirm_payment_token)
        confirm_payment_lock=confirm_payment_token=None
        await shop.fulfill(payment_id,db,existing_user_lock_token=user_token)
        await db.refresh(confirmed)
        return {"ok":True,"ignored":False,"reason":"fulfilled" if confirmed.fulfillment_status=='completed' else 'queued'}
    finally:
        if confirm_payment_lock and confirm_payment_token:
            await shop._release_payment_side_effect_lock(confirm_payment_lock,confirm_payment_token)
        await shop._release_payment_side_effect_lock(user_lock,user_token)

async def fulfill(payment_id:int, db:shop.AsyncSession, existing_user_lock_token: str|None = None):
    from .subscription_commerce import KINDS, apply_change
    commerce_payment = await db.get(shop.Payment, payment_id)
    if commerce_payment and commerce_payment.purpose in KINDS:
        return await apply_change(payment_id, db)
    if shop.redis_client is None:
        raise RuntimeError("Redis is required for fulfillment locking")
    # Global lock order: user -> payment. Auto-renew already owns the user lock
    # before it verifies/fulfills a recurring payment. Fulfillment must follow the
    # same order or concurrent webhook/worker and auto-renew paths can strand a
    # paid payment when each holds one lock and the other is busy.
    payment_lock = token = None
    user_token=None
    user_lock=None
    user_lock_key=None
    try:
        payment=(await db.execute(shop.select(shop.Payment).where(shop.Payment.id==payment_id))).scalar_one_or_none()
        if not payment: raise RuntimeError("Payment not found")
        if payment.status != "paid": raise RuntimeError("Payment is not confirmed")
        if payment.fulfillment_status=="completed" or payment.fulfillment_terminal: return
        if payment.fulfillment_attempts >= (payment.fulfillment_max_attempts or shop.settings.fulfillment_max_attempts):
            payment.fulfillment_status="failed"; payment.fulfillment_terminal=True; await db.commit(); raise RuntimeError("Fulfillment reached maximum attempts")
        user=await db.get(shop.User,payment.user_id)
        is_topup=(payment.purpose or "subscription")=="topup"
        plan=None if is_topup else await db.get(shop.Plan,payment.plan_id)
        if not user or user.deleted_at is not None or (not is_topup and not plan): raise RuntimeError("Payment references missing or deleted user/plan")
        # Purchased payments use their immutable checkout snapshot. Legacy rows without
        # snapshots fall back to the current plan for backward compatibility.
        if not is_topup:
            duration_days=(payment.duration_days_snapshot or plan.duration_days)+int(payment.bonus_days or 0)
            traffic_limit_gb=payment.traffic_limit_gb_snapshot if payment.duration_days_snapshot is not None else plan.traffic_limit_gb
            profile_id=payment.remnawave_profile_id_snapshot if payment.duration_days_snapshot is not None else plan.remnawave_profile_id
        user_token = existing_user_lock_token
        if not existing_user_lock_token:
            user_lock,user_token=await shop._acquire_user_fulfillment_lock(user.id,ttl=300)
            user_lock_key=user_lock
        # The first User read above is only a discovery snapshot. Account deletion uses
        # the same user lock, so after acquiring it we must always re-read the row under
        # FOR UPDATE, including when the caller already supplied the held user-lock token.
        # Otherwise auto-renew/webhook paths could keep a stale `deleted_at=None` object
        # and start a Remnawave side effect for an account that has already been anonymized.
        user=(await db.execute(shop.select(shop.User).where(shop.User.id==user.id).execution_options(populate_existing=True).with_for_update())).scalar_one_or_none()
        if not user or user.deleted_at is not None:
            raise RuntimeError("User is deleted or no longer available for fulfillment")
        plan=None if (payment.purpose or "subscription")=="topup" else await db.get(shop.Plan,payment.plan_id)
        if (payment.purpose or "subscription")!="topup" and not plan:
            raise RuntimeError("Payment plan no longer exists")
        if (payment.purpose or "subscription")!="topup":
            duration_days=(payment.duration_days_snapshot or plan.duration_days)+int(payment.bonus_days or 0)
            traffic_limit_gb=payment.traffic_limit_gb_snapshot if payment.duration_days_snapshot is not None else plan.traffic_limit_gb
            profile_id=payment.remnawave_profile_id_snapshot if payment.duration_days_snapshot is not None else plan.remnawave_profile_id
        payment_lock, token = await shop._acquire_payment_side_effect_lock(payment_id)
        # Re-read the payment after acquiring the shared payment lock. A refund/reconcile
        # path can legitimately win the lock after the initial read above. Never start
        # remote provisioning from a stale `paid` snapshot: doing so could provision a
        # payment that has already been refunded, even though the final DB check would
        # eventually reject completion.
        payment=(await db.execute(shop.select(shop.Payment).where(shop.Payment.id==payment_id).execution_options(populate_existing=True).with_for_update())).scalar_one_or_none()
        if not payment:
            raise RuntimeError("Payment not found after acquiring fulfillment lock")
        if payment.status in {"refunded", "refunded_pending_revoke", "creation_unknown"}:
            raise RuntimeError("Payment is no longer eligible for fulfillment")
        if payment.status != "paid":
            raise RuntimeError("Payment is not confirmed")
        if payment.fulfillment_status=="completed" or payment.fulfillment_terminal:
            return
        if (payment.purpose or "subscription")=="topup":
            amount=shop.Decimal(str(payment.amount)).quantize(shop.Decimal("0.01"))
            user.wallet_balance=(shop.Decimal(str(user.wallet_balance or 0))+amount).quantize(shop.Decimal("0.01"))
            await shop.record_financial_event(db,operation_key=f"wallet-topup:{payment.id}",user_id=user.id,payment_id=payment.id,kind="wallet_topup",direction="credit",amount=amount,currency=payment.currency,metadata={"order_id":payment.order_id})
            payment.fulfillment_status="completed"; payment.fulfillment_terminal=True; payment.fulfillment_attempts=(payment.fulfillment_attempts or 0)+1
            await shop.audit(db,"wallet.topup",f"user:{user.id}",str(payment.id),{"amount":str(amount)}); await db.commit()
            await shop.notify_user_telegram(user.telegram_id, f"Баланс пополнен на {amount} {payment.currency}. Wallet topped up by {amount} {payment.currency}.")
            # The smart cart (smart_cart.py) buys what did not fit the wallet before, once this lock is released.
            from .models import ShopCart
            if await db.get(ShopCart, user.id):
                from .smart_cart import after_topup
                shop._track_task(after_topup(user.id))
            return
        from .subscriptions import pending_absolute_write
        target=await shop.payment_target(db,payment,lock=True)
        if target and await pending_absolute_write(db,target.id):
            # Confirmation may arrive after a gift/change froze an absolute write.
            # Wait without spending a provisioning attempt or changing that snapshot.
            payment.fulfillment_status='failed';payment.fulfillment_terminal=False
            payment.fulfillment_error='Waiting for an earlier subscription operation'
            payment.next_retry_at=shop.datetime.utcnow()+shop.timedelta(seconds=60)
            waiting_job=await db.scalar(shop.select(shop.Job).where(shop.Job.job_key==f'fulfillment:{payment.id}').with_for_update())
            if waiting_job:
                waiting_job.status='queued';waiting_job.attempts=payment.fulfillment_attempts or 0
                waiting_job.next_retry_at=payment.next_retry_at;waiting_job.locked_at=None;waiting_job.worker_id=None
            await db.commit()
            return
        payment.fulfillment_status="processing"; payment.fulfillment_attempts=(payment.fulfillment_attempts or 0)+1; payment.fulfillment_error=None
        job=(await db.execute(shop.select(shop.Job).where(shop.Job.job_key==f"fulfillment:{payment.id}").with_for_update())).scalar_one_or_none()
        if not job:
            job=shop.Job(job_key=f"fulfillment:{payment.id}",kind="fulfillment",status="processing",attempts=payment.fulfillment_attempts,max_attempts=payment.fulfillment_max_attempts or shop.settings.fulfillment_max_attempts,payload={"payment_id":payment.id})
            db.add(job)
        else:
            job.status="processing"; job.attempts=payment.fulfillment_attempts; job.error=None; job.locked_at=shop.datetime.utcnow()
        await db.commit()
        sub=await shop.payment_target(db,payment)
        now=shop.datetime.utcnow(); rw=shop.RemnawaveClient()
        op_row=(await db.execute(shop.select(shop.ProvisioningOperation).where(shop.ProvisioningOperation.payment_id==payment.id))).scalar_one_or_none()
        if not op_row:
            op_row=shop.ProvisioningOperation(payment_id=payment.id,user_id=user.id,operation_key=f"payment:{payment.id}:v1",action="extend" if sub and sub.remnawave_uuid else "provision",status="pending",attempts=0,created_at=now,updated_at=now)
            db.add(op_row); await db.commit()
        op_row.status="processing"; op_row.attempts=(op_row.attempts or 0)+1; op_row.updated_at=now; await db.commit()
        try:
            if sub and sub.remnawave_uuid in {"None","none","null"}:
                # Releases before v28.21.0 read the panel answer without its "response" wrapper and
                # stored the literal "None". Forget it: the user is then found again by username.
                sub.remnawave_uuid=None
            if payment.provider == "sandbox" and shop.sandbox_local_vpn():
                sub=await shop.payment_target(db,payment)
                local_now=shop.datetime.utcnow()
                expires=local_now+shop.timedelta(days=duration_days)
                if sub and sub.expires_at and sub.expires_at > local_now:
                    expires=sub.expires_at+shop.timedelta(days=duration_days)
                if not sub:
                    sub=shop.Subscription(user_id=user.id, plan_id=plan.id)
                    db.add(sub)
                await db.flush(); payment.subscription_id=sub.id
                sub.plan_id=plan.id
                sub.remnawave_uuid=sub.remnawave_uuid or f"sandbox-user-{user.id}-sub-{sub.id}"
                sub.expires_at=expires
                sub.lifecycle_status="active"
                sub.unit_price_per_day=shop.Decimal(payment.amount)/shop.Decimal(duration_days)
                sub.traffic_limit_gb_snapshot=traffic_limit_gb
                sub.device_limit_snapshot=payment.device_limit_snapshot
                sub.remnawave_profile_id_snapshot=profile_id
                sub.subscription_url=f"sandbox://local/{user.id}/{payment.id}"
                op_row.status="completed"
                op_row.remote_user_id=sub.remnawave_uuid
                op_row.completed_at=shop.datetime.utcnow()
                op_row.updated_at=shop.datetime.utcnow()
            elif sub and sub.remnawave_uuid:
                # Refunds disable the remote user. A later legitimate purchase must re-enable it.
                remote_before=await rw.get_user(sub.remnawave_uuid)
                remote_status=str(remote_before.get("status") or remote_before.get("state") or "").lower() if isinstance(remote_before,dict) else ""
                if remote_status in {"disabled","blocked","inactive"}:
                    await rw.enable_user(sub.remnawave_uuid)
                remote_expiry=await rw.get_expiry(sub.remnawave_uuid)
                persisted_before=op_row.expected_before_expires_at
                persisted_after=op_row.expected_after_expires_at
                if persisted_before is not None and persisted_after is not None:
                    before_local=persisted_before
                    expected_after=persisted_after
                else:
                    before_local=max(sub.expires_at or now, remote_expiry or now, now)
                    expected_after=before_local+shop.timedelta(days=duration_days)
                    op_row.expected_before_expires_at=before_local
                    op_row.expected_after_expires_at=expected_after
                    await db.commit()
                # Existing remote users must receive the purchased traffic/profile terms too;
                # otherwise a plan upgrade can pay for more traffic while the old remote
                # quota remains in force (or a downgrade can leave excess quota active).
                await rw.update_entitlements(sub.remnawave_uuid,traffic_limit_gb,profile_id,device_limit=payment.device_limit_snapshot)
                from .grace_access import reset_traffic_on_payment
                if await reset_traffic_on_payment(db):
                    # «Сбрасывать трафик при оплате»: a renewal starts the traffic limit from zero (a retry resets again, harmless).
                    await rw.reset_traffic(sub.remnawave_uuid)
                extension=await rw.extend_idempotent(sub.remnawave_uuid,duration_days,before_local,expected_after)
                rw_sub=await rw.get_subscription(sub.remnawave_uuid)
                verified_expiry=extension.get("expires_at") if isinstance(extension,dict) else None
                sub.plan_id=plan.id; sub.expires_at=max(expected_after,verified_expiry or expected_after)
                sub.unit_price_per_day=shop.Decimal(payment.amount)/shop.Decimal(duration_days)
                sub.traffic_limit_gb_snapshot=traffic_limit_gb
                sub.device_limit_snapshot=payment.device_limit_snapshot
                sub.remnawave_profile_id_snapshot=profile_id
                sub.subscription_url=rw_sub.get("subscriptionUrl") or rw_sub.get("subscription_url") or sub.subscription_url
                op_row.remote_user_id=str(sub.remnawave_uuid)
            else:
                username=shop.remote_username(user.id,sub); first_wait=0
                # Recover a successful create whose response was lost before the shop received it.
                existing_remote=None
                try: existing_remote=await rw.get_user_by_username(username)
                except Exception: existing_remote=None
                if existing_remote and existing_remote.get("id"):
                    data=existing_remote; op_row.remote_user_id=str(data.get("id"))
                    remote_id=str(data.get("id"))
                    remote_status=str(data.get("status") or data.get("state") or "").lower()
                    if remote_status in {"disabled","blocked","inactive"}:
                        await rw.enable_user(remote_id)
                    await rw.update_entitlements(remote_id,traffic_limit_gb,profile_id,device_limit=payment.device_limit_snapshot)
                    remote_expiry=await rw.get_expiry(remote_id)
                    # Time the customer already has (shop ledger or panel) is kept: the purchase
                    # is added on top. A create whose response was lost already holds
                    # now+duration, which the one-hour tolerance recognises as applied.
                    base_expiry=max(now, sub.expires_at if sub and sub.expires_at else now)
                    target_expiry=base_expiry+shop.timedelta(days=duration_days)
                    if remote_expiry and remote_expiry>=target_expiry-shop.timedelta(hours=1):
                        target_expiry=remote_expiry
                    if not remote_expiry or remote_expiry < target_expiry:
                        before_remote=remote_expiry or now
                        extension_seconds=(target_expiry-max(before_remote,now)).total_seconds()
                        extension_days=max(1, int((extension_seconds + 86399) // 86400))
                        await rw.extend_idempotent(str(data.get("id")),extension_days,before_remote,target_expiry)
                        data=await rw.get_user(str(data.get("id")))
                    final_remote_expiry=await rw.get_expiry(str(data.get("id"))) or target_expiry
                else:
                    from .first_connect import wait_days
                    first_wait=await wait_days(db,plan.id,duration_days)  # «срок с первого подключения»: the wait is added up front
                    expires=now+shop.timedelta(days=duration_days+first_wait); traffic=traffic_limit_gb*1024**3 if traffic_limit_gb else 0
                    data=await rw.create_user(username,expires,traffic,active_internal_squads=[profile_id] if profile_id else None,telegram_id=user.telegram_id,device_limit=payment.device_limit_snapshot)
                    if not isinstance(data,dict) or not data.get("id"): raise RuntimeError("Remnawave returned no user id")
                    op_row.remote_user_id=str(data.get("id")); final_remote_expiry=expires
                if not sub:
                    sub=shop.Subscription(user_id=user.id,plan_id=plan.id); db.add(sub)
                await db.flush(); payment.subscription_id=sub.id
                sub.plan_id=plan.id; sub.remnawave_uuid=str(data.get("id")); sub.expires_at=final_remote_expiry
                sub.unit_price_per_day=shop.Decimal(payment.amount)/shop.Decimal(duration_days)
                sub.traffic_limit_gb_snapshot=traffic_limit_gb
                sub.device_limit_snapshot=payment.device_limit_snapshot
                sub.remnawave_profile_id_snapshot=profile_id
                sub.subscription_url=data.get("subscriptionUrl") or data.get("subscription_url")
                if first_wait:
                    from .first_connect import start_waiting
                    await start_waiting(db,sub,duration_days,now+shop.timedelta(days=first_wait))
            sub.lifecycle_status="active";sub.scheduled_cancel_at=None;sub.cancelled_at=None;sub.grace_until=None
            from .tariff_api import linked_constructor_id
            sub.renewal_terms=({'amount':str(payment.original_amount if payment.original_amount is not None else payment.amount),
                'days':payment.duration_days_snapshot or plan.duration_days,'traffic_gb':traffic_limit_gb,
                'devices':payment.device_limit_snapshot,'profile_id':profile_id,'currency':payment.currency}
                if await linked_constructor_id(db,plan.id) else None)
            op_row.status="completed"; op_row.completed_at=shop.datetime.utcnow(); op_row.updated_at=shop.datetime.utcnow()
        except Exception as remote_exc:
            op_row.status="retry"; op_row.last_error=str(remote_exc)[:2000]; op_row.updated_at=shop.datetime.utcnow(); job.status="failed" if payment.fulfillment_attempts >= payment.fulfillment_max_attempts else "queued"; job.error=str(remote_exc)[:2000]; job.next_retry_at=shop.datetime.utcnow()+shop.timedelta(minutes=min(30,max(1,2**min(payment.fulfillment_attempts,5)))); job.locked_at=None; await db.commit(); raise
        payment=(await db.execute(shop.select(shop.Payment).where(shop.Payment.id==payment.id).execution_options(populate_existing=True).with_for_update())).scalar_one()
        if payment.status != "paid" or payment.fulfillment_terminal:
            raise RuntimeError("Payment state changed while fulfillment was in progress; reconciliation is required")
        payment.fulfillment_status="completed"; payment.next_retry_at=None; payment.fulfillment_terminal=False
        job.status="completed"; job.completed_at=shop.datetime.utcnow(); job.locked_at=None; job.worker_id=None; job.error=None
        if payment.promo_code:
            reservation=(await db.execute(shop.select(shop.PromoReservation).where(shop.PromoReservation.payment_id==payment.id).with_for_update())).scalar_one_or_none()
            promo_row=(await db.execute(shop.select(shop.PromoCode).where(shop.PromoCode.code==payment.promo_code).with_for_update())).scalar_one_or_none()
            if reservation and reservation.status=="reserved" and promo_row:
                promo_row.reserved_count=max(0,int(promo_row.reserved_count or 0)-1)
                promo_row.used_count += 1
                reservation.status="consumed"
                db.add(shop.PromoRedemption(promo_code_id=promo_row.id,user_id=user.id,payment_id=payment.id))
            elif not reservation and promo_row and (promo_row.usage_limit is None or promo_row.used_count < promo_row.usage_limit):
                # Legacy payments created before reservation support.
                promo_row.used_count += 1
                db.add(shop.PromoRedemption(promo_code_id=promo_row.id,user_id=user.id,payment_id=payment.id))
        from .referral_program import credit as credit_referrals
        await credit_referrals(db, payment, user.id)
        from .bonus_days import queue_referral_bonus
        await queue_referral_bonus(db, payment)
        from .partners import credit as credit_partner
        await credit_partner(db, payment)
        await shop.audit(db,"payment.fulfilled","system",str(payment.id),{"provider":payment.provider,"attempt":payment.fulfillment_attempts})
        await shop.enqueue_notification(db,user_id=user.id,channel="in_app",kind="payment_success",title="Оплата подтверждена",body=f"Заказ {payment.order_id} оплачен. Подписка готовится или уже активирована.",dedupe_key=f"payment:{payment.id}:success")
        await shop.enqueue_notification(db,user_id=user.id,channel="in_app",kind="subscription_ready",title="Подписка активирована",body="Ваша VPN-подписка активирована. Откройте раздел подключения, чтобы получить ссылку.",dedupe_key=f"payment:{payment.id}:ready")
        from .activity_log import record as record_activity
        record_activity(db, user.id, "system", "payment.fulfilled", {"id": payment.id, "amount": payment.amount})
        await db.commit()
        from .ad_postbacks import fire as fire_conversion
        fire_conversion(user.id, "purchase", amount=str(payment.amount), currency=payment.currency, order_id=payment.order_id)
        await shop.notify_user_telegram(user.telegram_id, "Оплата подтверждена. Подписка активирована. Откройте раздел «Подключение».\nPayment confirmed. The subscription is active. Open Connection.")
    except Exception as exc:
        try:
            await db.rollback(); payment=(await db.execute(shop.select(shop.Payment).where(shop.Payment.id==payment_id))).scalar_one_or_none()
            if payment:
                attempts=payment.fulfillment_attempts or 1; terminal=attempts >= (payment.fulfillment_max_attempts or shop.settings.fulfillment_max_attempts)
                payment.fulfillment_status="failed"; payment.fulfillment_terminal=terminal; payment.fulfillment_error=str(exc)[:2000]
                payment.next_retry_at=None if terminal else shop.datetime.utcnow()+shop.timedelta(seconds=min(3600,60*(2**max(0,attempts-1))))
                job=(await db.execute(shop.select(shop.Job).where(shop.Job.job_key==f"fulfillment:{payment.id}").with_for_update())).scalar_one_or_none()
                if job:
                    job.status="failed" if terminal else "queued"; job.error=str(exc)[:2000]; job.locked_at=None; job.worker_id=None; job.next_retry_at=payment.next_retry_at
                await shop.audit(db,"payment.fulfillment.failed","system",str(payment.id),{"error":str(exc)[:500],"terminal":terminal}); await db.commit()
        except Exception: await db.rollback()
        raise
    finally:
        if payment_lock and token:
            await shop._release_payment_side_effect_lock(payment_lock, token)
        if user_token and not existing_user_lock_token:
            try:
                await shop._release_payment_side_effect_lock(user_lock_key,user_token)
            except Exception as exc:
                shop.logger.warning("Non-critical operation failed: %s", exc)
async def payment_by_provider(db, provider, pid):
    return (await db.execute(shop.select(shop.Payment).where(shop.Payment.provider==provider,shop.Payment.provider_payment_id==str(pid)))).scalar_one_or_none()

async def payment_by_provider_or_order(db: shop.AsyncSession, provider: str, pid: str|None, order_id: str|None):
    payment = await shop.payment_by_provider(db, provider, pid) if pid else None
    if payment or not order_id:
        return payment
    return (await db.execute(shop.select(shop.Payment).where(shop.Payment.provider==provider, shop.Payment.order_id==str(order_id)).execution_options(populate_existing=True).with_for_update())).scalar_one_or_none()

async def bind_provider_payment_id(db: shop.AsyncSession, payment: shop.Payment, provider_payment_id: str):
    provider_payment_id=str(provider_payment_id)
    if payment.provider_payment_id and payment.provider_payment_id != provider_payment_id:
        raise shop.HTTPException(409,"Payment provider identifier mismatch")
    payment.provider_payment_id=provider_payment_id
    if payment.status in {"creating","creation_unknown"}:
        payment.status="pending"
        payment.fulfillment_terminal=False

def _ip_allowed(value: str, allowlist: str) -> bool:
    try: ip=shop.ipaddress.ip_address(value)
    except ValueError: return False
    for item in allowlist.split(","):
        try:
            net=shop.ipaddress.ip_network(item.strip(), strict=False)
            if ip in net: return True
        except ValueError: continue
    return False

async def register_provider_event(db:shop.AsyncSession, provider:str, event_id:str, payment_id:int|None):
    """Atomically claim a verified event. Failed/retry events may be reclaimed; processed events are immutable."""
    if not event_id: return True
    stmt=shop.sql_text("""INSERT INTO payment_provider_events (provider,event_id,payment_id,status,attempts,received_at)
        VALUES (:p,:e,:pid,'processing',1,NOW())
        ON CONFLICT (provider,event_id) DO UPDATE SET payment_id=COALESCE(payment_provider_events.payment_id,EXCLUDED.payment_id),
        status='processing', attempts=payment_provider_events.attempts+1, last_error=NULL, received_at=NOW()
        WHERE payment_provider_events.provider = EXCLUDED.provider
          AND (payment_provider_events.status IN ('failed','retry')
           OR (payment_provider_events.status='processing' AND payment_provider_events.received_at < NOW() - INTERVAL '10 minutes'))
        RETURNING id""")
    result=await db.execute(stmt,{"p":provider,"e":event_id,"pid":payment_id})
    return result.first() is not None

async def finish_provider_event(db:shop.AsyncSession, provider:str, event_id:str, *, ok:bool, error:str|None=None):
    await db.execute(shop.sql_text("UPDATE payment_provider_events SET status=:status,last_error=:error,processed_at=:processed WHERE provider=:p AND event_id=:e"),
                     {"status":"processed" if ok else "retry","error":None if ok else (error or "")[:2000],"processed":shop.datetime.utcnow() if ok else None,"p":provider,"e":event_id})

async def _external_refund(provider:str, refund_id:str, db:shop.AsyncSession):
    """A refund made in the provider's own dashboard: record it and revoke access like a shop refund.

    The notification is only a hint. The refund is read back from the provider and must be
    succeeded, belong to a paid payment of this shop and cover its full amount. Partial refunds
    are recorded in the audit log for an operator and do not revoke access."""
    readers={"yookassa":lambda: shop.YooKassaProvider().get_refund(refund_id),
             # Platega/RollyPay report the refund on the payment itself: refund_id is their payment id.
             "platega":lambda: shop.PlategaProvider().read_refund(refund_id),
             "rollypay":lambda: shop.RollyPayProvider().read_refund(refund_id)}
    if provider not in readers: return {"ok":True}
    try: info=await readers[provider]()
    except Exception: raise shop.HTTPException(503,"Refund verification unavailable")
    if provider!="yookassa": refund_id=str(info.get("id") or refund_id)
    if info.get("status")!="succeeded" or not info.get("payment_id"): return {"ok":True,"ignored":True}
    p=await shop.payment_by_provider(db,provider,str(info["payment_id"]))
    if not p: return {"ok":True,"ignored":True}
    existing=(await db.execute(shop.select(shop.RefundRequest).where(shop.RefundRequest.payment_id==p.id))).scalar_one_or_none()
    if existing and existing.status in {"refunded","refunded_pending_revoke"}: return {"ok":True,"duplicate":True}
    try: full=shop.Decimal(str(info.get("amount") or "0"))>=shop.Decimal(str(p.amount)) and (info.get("currency") or p.currency)==p.currency
    except Exception: full=False
    if not full:
        await shop.audit(db,"payment.refund.partial_external","provider",str(p.id),{"refund_id":refund_id,"amount":info.get("amount")}); await db.commit()
        return {"ok":True,"partial":True}
    if p.status not in {"paid","fulfilled","refunded_pending_revoke"}: return {"ok":True,"ignored":True}
    if existing:
        if existing.provider_refund_id and existing.provider_refund_id!=refund_id:
            await shop.audit(db,"payment.refund.external_conflict","provider",str(p.id),{"refund_id":refund_id}); await db.commit()
            return {"ok":True,"conflict":True}
        existing.provider_refund_id=refund_id; existing.status="processing"; existing.updated_at=shop.datetime.utcnow(); r=existing
    else:
        r=shop.RefundRequest(payment_id=p.id,user_id=p.user_id,amount=p.amount,reason="Возврат оформлен в кабинете провайдера",status="processing",provider_refund_id=refund_id)
        db.add(r)
    await shop.audit(db,"payment.refund.external","provider",str(p.id),{"refund_id":refund_id}); await db.commit(); await db.refresh(r)
    from types import SimpleNamespace
    result=await shop.reconcile_refund(r.id,db,SimpleNamespace(email=f"{provider}-webhook"))
    return {"ok":True,"refund":result.get("status")}

@shop.app.post("/api/webhooks/yookassa")
async def yookassa_webhook(request:shop.Request, db:shop.AsyncSession=shop.Depends(shop.get_db)):
    client_ip=shop._client_ip(request)
    # Fail closed: an empty allowlist must not accept unsigned YooKassa notifications.
    if not shop.settings.yookassa_webhook_ip_allowlist or not shop._ip_allowed(client_ip,shop.settings.yookassa_webhook_ip_allowlist): raise shop.HTTPException(403,"Webhook IP not allowed")
    raw=await request.body()
    try: d=shop.json.loads(raw)
    except Exception: raise shop.HTTPException(400,"Invalid JSON")
    obj=d.get("object",{}) or {}
    pid=obj.get("id"); event_id=str(d.get("id") or shop.hashlib.sha256(raw).hexdigest())
    order_id=(obj.get("metadata") or {}).get("order_id")
    if d.get("event")=="refund.succeeded" and pid:
        return await shop._external_refund("yookassa",str(pid),db)
    if d.get("event")!="payment.succeeded" or not pid: return {"ok":True}
    p=await shop.payment_by_provider_or_order(db,"yookassa",pid,order_id)
    if not p: return {"ok":True}
    if order_id and order_id != p.order_id: raise shop.HTTPException(403,"Order mismatch")
    # Verify the provider object itself, including immutable order metadata, before
    # binding a previously-unknown provider payment ID to a durable local intent.
    if not await shop.YooKassaProvider().verify_succeeded(pid,shop.Decimal(str(p.amount)),p.currency,p.order_id): raise shop.HTTPException(503,"Payment status verification unavailable")
    await shop.e2e_capture_webhook("yookassa",request,raw,p.id)
    if not p.provider_payment_id:
        await shop.bind_provider_payment_id(db,p,pid)
    if not await shop.register_provider_event(db,"yookassa",event_id,p.id): await db.rollback(); return {"ok":True,"duplicate":True}
    await db.commit()
    try:
        # Late-success guard: p.status in {"refunded", "refunded_pending_revoke"} is re-checked atomically inside _confirm_and_fulfill_payment.
        result=await shop._confirm_and_fulfill_payment(p.id,db)
        if result.get("ignored"):
            async with shop.AsyncSession(shop.engine,expire_on_commit=False) as edb:
                await shop.finish_provider_event(edb,"yookassa",event_id,ok=True); await edb.commit()
            return {"ok":True,"ignored":True,"reason":"payment_already_refunded"}
        async with shop.AsyncSession(shop.engine,expire_on_commit=False) as edb: await shop.finish_provider_event(edb,"yookassa",event_id,ok=True); await edb.commit()
    except Exception as exc:
        async with shop.AsyncSession(shop.engine,expire_on_commit=False) as edb: await shop.finish_provider_event(edb,"yookassa",event_id,ok=False,error=str(exc)); await edb.commit()
        raise
    return {"ok":True}

@shop.app.post("/api/webhooks/platega")
async def platega_webhook(request:shop.Request, db:shop.AsyncSession=shop.Depends(shop.get_db)):
    raw=await request.body()
    try: d=shop.PlategaProvider().verify_webhook(dict(request.headers),raw)
    except Exception: raise shop.HTTPException(403,"Invalid Platega webhook")
    pid=d.get("id") or d.get("Id") or d.get("transactionId"); event_id=str(d.get("eventId") or d.get("id") or shop.hashlib.sha256(raw).hexdigest())
    if pid and str(d.get("status") or d.get("Status")).upper() in shop.PLATEGA_REFUNDED:
        return await shop._external_refund("platega",str(pid),db)
    if str(d.get("status") or d.get("Status")).upper() not in {"CONFIRMED","SUCCESS","SUCCEEDED"} or not pid: return {"ok":True}
    payload_order=str(d.get("payload") or d.get("Payload") or "")
    p=await shop.payment_by_provider_or_order(db,"platega",pid,payload_order or None)
    if p:
        if payload_order and payload_order != p.order_id: raise shop.HTTPException(403,"Order mismatch")
        if not await shop.PlategaProvider().verify_succeeded(pid,shop.Decimal(str(p.amount)),p.currency,p.order_id): raise shop.HTTPException(503,"Payment verification unavailable")
        await shop.e2e_capture_webhook("platega",request,raw,p.id)
        if not p.provider_payment_id:
            await shop.bind_provider_payment_id(db,p,pid)
        if not await shop.register_provider_event(db,"platega",event_id,p.id): await db.rollback(); return {"ok":True,"duplicate":True}
        await db.commit()
        try:
            # Late-success guard: p.status in {"refunded", "refunded_pending_revoke"} is re-checked atomically inside _confirm_and_fulfill_payment.
            result=await shop._confirm_and_fulfill_payment(p.id,db)
            if result.get("ignored"):
                async with shop.AsyncSession(shop.engine,expire_on_commit=False) as edb:
                    await shop.finish_provider_event(edb,"platega",event_id,ok=True); await edb.commit()
                return {"ok":True,"ignored":True,"reason":"payment_already_refunded"}
            async with shop.AsyncSession(shop.engine,expire_on_commit=False) as edb: await shop.finish_provider_event(edb,"platega",event_id,ok=True); await edb.commit()
        except Exception as exc:
            async with shop.AsyncSession(shop.engine,expire_on_commit=False) as edb: await shop.finish_provider_event(edb,"platega",event_id,ok=False,error=str(exc)); await edb.commit()
            raise
    return {"ok":True}

@shop.app.post("/api/webhooks/rollypay")
async def rollypay_webhook(request:shop.Request,db:shop.AsyncSession=shop.Depends(shop.get_db)):
    raw=await request.body()
    if not shop.verify_rollypay(raw,request.headers.get("X-Timestamp",""),request.headers.get("X-Signature","")): raise shop.HTTPException(403,"Invalid signature")
    try: d=shop.json.loads(raw)
    except Exception: raise shop.HTTPException(400,"Invalid JSON")
    pid=d.get("payment_id"); event_id=str(d.get("event_id") or d.get("id") or shop.hashlib.sha256(raw).hexdigest())
    if pid and str(d.get("status")).lower() in shop.ROLLYPAY_REFUNDED:
        return await shop._external_refund("rollypay",str(pid),db)
    if str(d.get("status")).lower() not in {"paid","success","succeeded"} or not pid: return {"ok":True}
    order_id=str(d.get("order_id") or "")
    p=await shop.payment_by_provider_or_order(db,"rollypay",pid,order_id or None)
    if p:
        if order_id and order_id != p.order_id: raise shop.HTTPException(403,"Order mismatch")
        if not await shop.RollyPayProvider().verify_succeeded(pid,shop.Decimal(str(p.amount)),p.currency,p.order_id): raise shop.HTTPException(503,"Payment verification unavailable")
        await shop.e2e_capture_webhook("rollypay",request,raw,p.id)
        if not p.provider_payment_id:
            await shop.bind_provider_payment_id(db,p,pid)
        if not await shop.register_provider_event(db,"rollypay",event_id,p.id): await db.rollback(); return {"ok":True,"duplicate":True}
        await db.commit()
        try:
            # Late-success guard: p.status in {"refunded", "refunded_pending_revoke"} is re-checked atomically inside _confirm_and_fulfill_payment.
            result=await shop._confirm_and_fulfill_payment(p.id,db)
            if result.get("ignored"):
                async with shop.AsyncSession(shop.engine,expire_on_commit=False) as edb:
                    await shop.finish_provider_event(edb,"rollypay",event_id,ok=True); await edb.commit()
                return {"ok":True,"ignored":True,"reason":"payment_already_refunded"}
            async with shop.AsyncSession(shop.engine,expire_on_commit=False) as edb: await shop.finish_provider_event(edb,"rollypay",event_id,ok=True); await edb.commit()
        except Exception as exc:
            async with shop.AsyncSession(shop.engine,expire_on_commit=False) as edb: await shop.finish_provider_event(edb,"rollypay",event_id,ok=False,error=str(exc)); await edb.commit()
            raise
    return {"ok":True}



@shop.app.post("/api/webhooks/cryptobot")
async def cryptobot_webhook(request:shop.Request,db:shop.AsyncSession=shop.Depends(shop.get_db)):
    """Crypto Pay «invoice_paid»: signature (HMAC-SHA256 with SHA-256 of the token), then the invoice is re-read
    from Crypto Pay (status, RUB amount and the order id in its payload) before fulfillment."""
    raw=await request.body()
    try: d=shop.CryptoBotProvider().verify_webhook(dict(request.headers),raw)
    except Exception: raise shop.HTTPException(403,"Invalid signature")
    if str(d.get("update_type") or "")!="invoice_paid": return {"ok":True}
    invoice=d.get("payload") or {}
    pid=str(invoice.get("invoice_id") or ""); order_id=str(invoice.get("payload") or "")
    if not pid: return {"ok":True}
    event_id=f"invoice_paid:{pid}"
    p=await shop.payment_by_provider_or_order(db,"cryptobot",pid,order_id or None)
    if not p: return {"ok":True}
    if order_id and order_id != p.order_id: raise shop.HTTPException(403,"Order mismatch")
    if not await shop.CryptoBotProvider().verify_succeeded(pid,shop.Decimal(str(p.amount)),p.currency,p.order_id): raise shop.HTTPException(503,"Payment verification unavailable")
    if not p.provider_payment_id:
        await shop.bind_provider_payment_id(db,p,pid)
    if not await shop.register_provider_event(db,"cryptobot",event_id,p.id): await db.rollback(); return {"ok":True,"duplicate":True}
    await db.commit()
    try:
        result=await shop._confirm_and_fulfill_payment(p.id,db)
        async with shop.AsyncSession(shop.engine,expire_on_commit=False) as edb: await shop.finish_provider_event(edb,"cryptobot",event_id,ok=True); await edb.commit()
        if result.get("ignored"): return {"ok":True,"ignored":True,"reason":"payment_already_refunded"}
    except Exception as exc:
        async with shop.AsyncSession(shop.engine,expire_on_commit=False) as edb: await shop.finish_provider_event(edb,"cryptobot",event_id,ok=False,error=str(exc)); await edb.commit()
        raise
    return {"ok":True}

@shop.app.api_route("/api/webhooks/freekassa", methods=["GET","POST"])
async def freekassa_webhook(request:shop.Request,db:shop.AsyncSession=shop.Depends(shop.get_db)):
    """Freekassa payment notification (GET or form POST): Freekassa's address and SIGN (secret word 2), then the order
    is re-read through API v1 (paid, amount, currency) before fulfillment. Freekassa repeats the call until it reads «YES»."""
    from fastapi.responses import PlainTextResponse
    params=dict(request.query_params)
    if request.method=="POST":
        try: params.update({k:str(v) for k,v in (await request.form()).items()})
        except Exception: raise shop.HTTPException(400,"Invalid form")
    try: shop.FreekassaProvider().verify_notification(params,shop._client_ip(request))
    except Exception: raise shop.HTTPException(403,"Invalid signature")
    order_id=str(params.get("MERCHANT_ORDER_ID") or ""); intid=str(params.get("intid") or "")
    if not order_id: return PlainTextResponse("YES")
    event_id=f"paid:{intid or order_id}"
    p=await shop.payment_by_provider_or_order(db,"freekassa",order_id,order_id)
    if not p: return PlainTextResponse("YES")
    if p.provider!="freekassa": raise shop.HTTPException(403,"Order mismatch")
    if shop.Decimal(str(params.get("AMOUNT") or "0"))!=shop.Decimal(str(p.amount)): raise shop.HTTPException(403,"Amount mismatch")
    if not await shop.FreekassaProvider().verify_succeeded(order_id,shop.Decimal(str(p.amount)),p.currency,p.order_id): raise shop.HTTPException(503,"Payment verification unavailable")
    if not await shop.register_provider_event(db,"freekassa",event_id,p.id): await db.rollback(); return PlainTextResponse("YES")
    await db.commit()
    try:
        await shop._confirm_and_fulfill_payment(p.id,db)
        async with shop.AsyncSession(shop.engine,expire_on_commit=False) as edb: await shop.finish_provider_event(edb,"freekassa",event_id,ok=True); await edb.commit()
    except Exception as exc:
        async with shop.AsyncSession(shop.engine,expire_on_commit=False) as edb: await shop.finish_provider_event(edb,"freekassa",event_id,ok=False,error=str(exc)); await edb.commit()
        raise
    return PlainTextResponse("YES")

__all__ = ['provider_configured', '_LOCK_RENEW_TASKS', '_SAFE_LOCK_MESSAGES', '_acquire_payment_side_effect_lock', '_acquire_redis_lock', '_acquire_user_fulfillment_lock', '_advisory_lock', '_confirm_and_fulfill_payment', '_external_refund', '_ip_allowed', '_lock_conflict', '_payment_provider_order', '_release_payment_side_effect_lock', '_renew_redis_lock', 'bind_provider_payment_id', 'create_payment', 'ensure_required_channel', 'finish_provider_event', 'fulfill', 'payment_by_provider', 'payment_by_provider_or_order', 'cryptobot_webhook', 'freekassa_webhook', 'platega_webhook', 'register_provider_event', 'release_promo_reservation', 'reserve_promo', 'rollypay_webhook', 'yookassa_webhook']
# Imported before main finished (``from app import payments_api`` first)? Then main's star
# import saw a half-loaded module; hand the names over now that they exist.
shop.__dict__.update({_n: globals()[_n] for _n in __all__})
