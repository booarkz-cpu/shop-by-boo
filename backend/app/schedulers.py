"""Background schedulers (moved from main.py in v28.35.0): fulfillment retries, refund revocation, auto-renew with saved YooKassa cards, reconciliation, subscription lifecycle and expiry reminders.

Names that belong to main are read through ``shop.<name>`` at call time, so tests and
operators that patch ``app.main`` keep affecting this code exactly as before."""
from . import main as shop

# ---------- Background schedulers: retries, refunds, auto-renew, reconciliation, lifecycle, reminders ----------
async def fulfillment_retry_scheduler():
    while True:
        try:
            async with shop.AsyncSession(shop.engine,expire_on_commit=False) as db:
                rows=(await db.execute(shop.select(shop.Payment).where(shop.Payment.fulfillment_status=="failed",shop.Payment.next_retry_at<=shop.datetime.utcnow()).order_by(shop.Payment.next_retry_at).limit(10))).scalars().all()
                for p in rows:
                    try: await shop.fulfill(p.id,db)
                    except Exception as exc:
                        shop.logger.warning("Non-critical operation failed: %s", exc)
            await shop.asyncio.sleep(15)
        except Exception: await shop.asyncio.sleep(15)

async def refund_revoke_scheduler():
    while True:
        try:
            async with shop.AsyncSession(shop.engine,expire_on_commit=False) as db:
                providers={"yookassa":shop.YooKassaProvider(),"platega":shop.PlategaProvider(),"rollypay":shop.RollyPayProvider(),"stripe":shop.StripePlatform(),"paypal":shop.PayPalPlatform(),"telegram_stars":shop.TelegramStarsProvider()}
                pending=(await db.execute(shop.select(shop.RefundRequest).where(shop.RefundRequest.status=="processing",shop.RefundRequest.provider_refund_id.is_not(None)).order_by(shop.RefundRequest.updated_at).limit(50))).scalars().all()
                for r in pending:
                    p=await db.get(shop.Payment,r.payment_id); provider=providers.get(p.provider) if p else None
                    if not p or not provider or not hasattr(provider,"get_refund_status"): continue
                    try:
                        status=await provider.get_refund_status(r.provider_refund_id)
                        if status in {"succeeded","paid","completed","refunded"}:
                            # Reconciliation is another refund side-effect entry point. It must
                            # serialize with fulfillment just like manual refund execution;
                            # otherwise a background poll can mark a payment refunded while
                            # an already-running fulfillment is still provisioning it.
                            user_lock, user_token = await shop._acquire_user_fulfillment_lock(p.user_id,ttl=300)
                            payment_lock = payment_token = None
                            try:
                                payment_lock, payment_token = await shop._acquire_payment_side_effect_lock(p.id)
                                p=(await db.execute(shop.select(shop.Payment).where(shop.Payment.id==p.id).execution_options(populate_existing=True).with_for_update())).scalar_one()
                                r=(await db.execute(shop.select(shop.RefundRequest).where(shop.RefundRequest.id==r.id).execution_options(populate_existing=True).with_for_update())).scalar_one()
                                if p.status == "refunded" and r.status == "refunded":
                                    continue
                                r.status="refunded"; p.status="refunded"; p.fulfillment_terminal=True; r.updated_at=shop.datetime.utcnow()
                                await shop.record_financial_event(db,operation_key=f"payment:{p.id}:refund:{r.id}",user_id=p.user_id,payment_id=p.id,kind="refund",direction="debit",amount=shop.Decimal(str(p.amount)),currency=p.currency,metadata={"provider":p.provider,"refund_id":r.id,"provider_refund_id":r.provider_refund_id})
                                try:
                                    revoke_result=await shop._safe_revoke_for_refunded_payment(db,p,"system","subscription.revoked.refund.reconciled")
                                except Exception as exc:
                                    r.status="refunded_pending_revoke"; r.reason=(r.reason or "")+"\nRevoke pending: "+str(exc)[:500]; revoke_result={"revoked":False,"reason":"revoke_failed"}
                                reversal_result=await shop._reverse_referral_reward_for_refund(db,p,"system") if r.status == "refunded" else {"reversed":False}
                                await shop.audit(db,"payment.refund.reconciled","system",str(p.id),{"provider_status":status,**revoke_result,**reversal_result})
                            finally:
                                if payment_lock and payment_token:
                                    await shop._release_payment_side_effect_lock(payment_lock, payment_token)
                                await shop._release_payment_side_effect_lock(user_lock,user_token)
                        elif status in {"canceled","cancelled","failed","rejected"}:
                            r.status="failed"; r.reason=(r.reason or "")+f"\nProvider refund status: {status}"; r.updated_at=shop.datetime.utcnow()
                    except Exception as exc:
                        r.reason=(r.reason or "")+"\nRefund reconciliation pending: "+str(exc)[:300]
                rows=(await db.execute(shop.select(shop.RefundRequest).where(shop.RefundRequest.status=="refunded_pending_revoke").order_by(shop.RefundRequest.updated_at).limit(20))).scalars().all()
                for r in rows:
                    p=await db.get(shop.Payment,r.payment_id)
                    if not p: continue
                    payment_lock=payment_token=None
                    user_lock=user_token=None
                    try:
                        user_lock,user_token=await shop._acquire_user_fulfillment_lock(p.user_id,ttl=300)
                        payment_lock,payment_token=await shop._acquire_payment_side_effect_lock(p.id)
                        # Re-check terminal state after acquiring the shared lock. This is the
                        # same critical section used by fulfillment and manual refund execution.
                        p=(await db.execute(shop.select(shop.Payment).where(shop.Payment.id==p.id).execution_options(populate_existing=True).with_for_update())).scalar_one()
                        r=(await db.execute(shop.select(shop.RefundRequest).where(shop.RefundRequest.id==r.id).execution_options(populate_existing=True).with_for_update())).scalar_one()
                        if r.status != "refunded_pending_revoke": continue
                        revoke_result=await shop._safe_revoke_for_refunded_payment(db,p,"system","subscription.revoked.refund.retry")
                        r.status="refunded"; r.updated_at=shop.datetime.utcnow()
                        reversal_result=await shop._reverse_referral_reward_for_refund(db,p,"system")
                        await shop.audit(db,"subscription.revoked.refund.retry","system",str(p.id),{"payment_id":p.id,**revoke_result,**reversal_result})
                    except Exception as exc:
                        r.reason=(r.reason or "")+"\nRevoke retry pending: "+str(exc)[:500]
                    finally:
                        if payment_lock and payment_token:
                            await shop._release_payment_side_effect_lock(payment_lock,payment_token)
                        if user_lock and user_token:
                            await shop._release_payment_side_effect_lock(user_lock,user_token)
                await db.commit()
        except Exception as exc:
            shop.logger.warning("Refund scheduler failure: %s", exc)
            await shop.send_alert("Refund scheduler failure")
        await shop.asyncio.sleep(30)

def auto_renew_chargeable(user:shop.User,sub:shop.Subscription)->bool:
    """Only a live subscription of an unrestricted customer may be charged automatically."""
    return (user.restricted_at is None and sub.scheduled_cancel_at is None
            and (sub.lifecycle_status or "active") in {"active","grace"})


RECURRING_IDEMPOTENCE_WINDOW=shop.timedelta(hours=23)


async def adopt_or_retry_recurring(payment:shop.Payment,method:shop.AutoRenewMethod,plan:shop.Plan)->str:
    """Resolve a recurring intent left in «creating»: adopt / retry / unknown."""
    provider=shop.YooKassaProvider()
    created=payment.created_at or shop.datetime.utcnow()
    found=await provider.find_by_order_id(payment.order_id,created-shop.timedelta(hours=1))
    if found and found.get("id"):
        payment.provider_payment_id=str(found["id"]); payment.status="pending"
        return "adopted"
    if shop.datetime.utcnow()-created>shop.RECURRING_IDEMPOTENCE_WINDOW:
        payment.status="creation_unknown"; payment.fulfillment_terminal=True
        payment.fulfillment_error="Recurring charge outcome unknown after the idempotence window; reconciliation required"
        return "unknown"
    token=shop.decrypt_secret(method.external_token_encrypted)
    result=await provider.charge_recurring(shop.Decimal(str(payment.amount)),payment.order_id,f"Auto-renew {plan.name}",token)
    payment.provider_payment_id=result["id"]; payment.status="pending"
    return "retried"


async def _record_paid(db:shop.AsyncSession,payment:shop.Payment):
    await shop.record_financial_event(db, operation_key=f"payment:{payment.id}:paid", user_id=payment.user_id, payment_id=payment.id, kind="payment", direction="credit", amount=shop.Decimal(str(payment.amount)), currency=payment.currency, metadata={"provider": payment.provider, "order_id": payment.order_id})


async def run_auto_renew_pass(db) -> None:
    """One pass of auto-renew: charge saved YooKassa cards of subscriptions that end within the lead time.
    A failed charge is retried with a new idempotency key (backoff 2, 4 … 72 h); after three failures the
    saved card is switched off and the customer pays by hand."""
    # Auto-renew is a real payment operation and must obey the same
    # production gate and payments feature flag as interactive checkout.
    if await shop.maintenance_enabled(db): return
    if await shop.feature_enabled(db, "payments", True) is False: return
    if not await shop.production_payments_allowed(db): return
    cutoff=shop.datetime.utcnow()+shop.timedelta(days=max(1,min(int(shop.settings.auto_renew_lead_days or 3),14)))
    rows=(await db.execute(shop.select(shop.User,shop.Subscription,shop.Plan,shop.AutoRenewMethod).join(shop.Subscription,shop.Subscription.user_id==shop.User.id).join(shop.Plan,shop.Plan.id==shop.Subscription.plan_id).join(shop.AutoRenewMethod,shop.AutoRenewMethod.user_id==shop.User.id).where(shop.User.auto_renew_enabled.is_(True),shop.Subscription.auto_renew_enabled.is_(True),shop.AutoRenewMethod.enabled.is_(True),shop.AutoRenewMethod.status.in_(["active","past_due"]),shop.Subscription.expires_at.is_not(None),shop.Subscription.expires_at<=cutoff,shop.Subscription.expires_at>shop.datetime.utcnow(),((shop.Subscription.next_renewal_at.is_(None))|(shop.Subscription.next_renewal_at<=shop.datetime.utcnow()))).limit(25))).all()
    for user,sub,plan,method in rows:
        candidate_subscription_id=sub.id
        customer_id=user.id
        if method.provider != "yookassa": continue
        # Account deletion shares this user-level lock. Re-load the user after
        # acquiring it so a row selected by the scheduler cannot become a charge
        # after the account has been anonymized.
        user_lock=user_token=None
        renew_lock=renew_token=None  # set per customer: an early «continue» must not release the previous one
        try:
            user_lock,user_token=await shop._acquire_user_fulfillment_lock(user.id,ttl=900)
        except Exception:
            continue
        try:
            user=(await db.execute(shop.select(shop.User).where(shop.User.id==user.id).execution_options(populate_existing=True).with_for_update())).scalar_one_or_none()
            if not user or user.deleted_at is not None or not user.auto_renew_enabled:
                continue
            method=(await db.execute(shop.select(shop.AutoRenewMethod).where(shop.AutoRenewMethod.user_id==user.id).with_for_update())).scalar_one_or_none()
            sub=(await db.execute(shop.select(shop.Subscription).where(shop.Subscription.user_id==user.id,shop.Subscription.id==candidate_subscription_id).execution_options(populate_existing=True).with_for_update())).scalar_one_or_none()
            plan=await db.get(shop.Plan,sub.plan_id) if sub else None
            if not method or not sub or not sub.auto_renew_enabled or not plan or not method.enabled or method.status not in {"active","past_due"} or method.provider != "yookassa":
                continue
            if not sub.expires_at or sub.expires_at <= shop.datetime.utcnow() or sub.expires_at > cutoff:
                continue
            # A cancelled, suspended or restricted subscription is never charged:
            # cancellation keeps auto_renew_enabled so «undo» restores it, and an
            # abuse restriction must not be reversed by a renewal's fulfill().
            if not shop.auto_renew_chargeable(user,sub):
                continue
            from .subscriptions import ensure_no_pending_gift
            try:await ensure_no_pending_gift(db,sub.id)
            except shop.HTTPException:continue
            date_key=(sub.expires_at or shop.datetime.utcnow()).strftime("%Y%m%d")
            order_id=f"auto-renew-{user.id}-sub-{sub.id}-{plan.id}-{date_key}"
            renew_lock=renew_token=None
            try:
                renew_lock,renew_token=await shop._acquire_redis_lock(f"lock:auto-renew:user:{user.id}:{date_key}",ttl=900,conflict_message="Auto-renew is already in progress")
            except RuntimeError:
                continue
            prefix=f"auto-renew-{user.id}-sub-{sub.id}-{plan.id}-{date_key}"
            attempts=(await db.execute(shop.select(shop.Payment).where(shop.Payment.user_id==user.id,shop.Payment.subscription_id==sub.id,shop.or_(shop.Payment.order_id.like(prefix+"%"),shop.Payment.order_id.like(f"auto-renew-{user.id}-{plan.id}-{date_key}%")),shop.Payment.provider=="yookassa").order_by(shop.Payment.id.desc()))).scalars().all()
            existing=attempts[0] if attempts else None
            if existing:
                if existing.currency!=shop.settings.default_currency:
                    method.last_error='Recurring payment currency changed; operator reconciliation required'
                    await db.commit();continue
                if existing.status=="creating" and existing.provider_payment_id is None:
                    # The previous run may have died after YooKassa accepted the
                    # charge. Adopt that payment first; YooKassa keeps idempotence
                    # keys for 24 hours only, so an older intent is never re-sent —
                    # it goes to reconciliation (creation_unknown) instead.
                    adopted=await shop.adopt_or_retry_recurring(existing,method,plan)
                    await db.commit()
                    if adopted=="unknown": continue
                if existing.status=="pending":
                    try:
                        provider=shop.YooKassaProvider()
                        verified=await provider.verify_succeeded(existing.provider_payment_id,shop.Decimal(str(existing.amount)),existing.currency,existing.order_id)
                        if verified:
                            payment_lock, payment_token = await shop._acquire_payment_side_effect_lock(existing.id)
                            try:
                                existing=(await db.execute(shop.select(shop.Payment).where(shop.Payment.id==existing.id).execution_options(populate_existing=True).with_for_update())).scalar_one()
                                if existing.status in {"refunded", "refunded_pending_revoke"}:
                                    continue
                                existing.status="paid"; existing.paid_at=existing.paid_at or shop.datetime.utcnow()
                                await shop._record_paid(db,existing); await db.commit()
                            finally:
                                await shop._release_payment_side_effect_lock(payment_lock, payment_token)
                            try:
                                await shop.fulfill(existing.id,db,existing_user_lock_token=user_token)
                                await db.refresh(existing)
                                if existing.fulfillment_status!='completed':continue
                                method.last_success_at=shop.datetime.utcnow(); method.failure_count=0; method.status="active"; method.last_error=None; method.next_attempt_at=shop.datetime.utcnow()+shop.timedelta(days=20); sub.next_renewal_at=method.next_attempt_at; sub.lifecycle_status="active"; sub.grace_until=None; sub.last_renewal_failure_at=None; await db.commit()
                            except Exception as exc:
                                method.last_error=str(exc)[:1000]; await db.commit()
                        else:
                            provider_status=await provider.get_payment_status(existing.provider_payment_id)
                            if provider_status in {"canceled","cancelled","failed","rejected"}:
                                existing.status="failed"; existing.fulfillment_terminal=True; method.failure_count=(method.failure_count or 0)+1; method.status="past_due"; method.last_error=f"Recurring payment {provider_status}"; method.next_attempt_at=shop.datetime.utcnow()+shop.timedelta(hours=min(72,2**min(method.failure_count,6))); sub.next_renewal_at=method.next_attempt_at; sub.lifecycle_status="grace"; sub.grace_until=(sub.expires_at or shop.datetime.utcnow())+shop.timedelta(hours=72); sub.last_renewal_failure_at=shop.datetime.utcnow()
                                if method.failure_count>=3: method.status="payment_failed"; method.enabled=False; user.auto_renew_enabled=False
                                await db.commit()
                    except Exception as exc:
                        shop.logger.warning("Non-critical operation failed: %s", exc)
                # Never create a second charge while the newest provider attempt
                # is unresolved or already succeeded. Failed/cancelled attempts are
                # the only safe state from which a new idempotency key may be used.
                if existing.status not in {"failed","canceled","cancelled"}:
                    continue
                failed_count=sum(1 for item in attempts if item.status in {"failed","canceled","cancelled"})
                order_id=f"{prefix}-retry-{failed_count+1}"
            token=shop.decrypt_secret(method.external_token_encrypted)
            from .subscriptions import ensure_no_pending_purchase,renewal_terms
            try:await ensure_no_pending_purchase(db,sub.id)
            except shop.HTTPException:continue
            terms=await renewal_terms(db,sub,plan)
            if not terms:
                method.last_error='Constructor renewal terms unavailable; buy or change this subscription explicitly'
                await db.commit();continue
            if terms.get('currency')!=shop.settings.default_currency:
                method.last_error='Renewal currency differs from configured currency; explicit purchase required'
                await db.commit();continue
            renewal_amount=shop.Decimal(terms['amount'])
            if renewal_amount<=0 or int(terms['days'])<=0:continue
            # Persist the payment intent BEFORE the external charge. If the
            # process dies after YooKassa accepts the charge but before the
            # response/DB commit, the next run can safely retry the SAME
            # idempotency key instead of issuing a second charge.
            payment=(await db.execute(shop.select(shop.Payment).where(shop.Payment.order_id==order_id).execution_options(populate_existing=True).with_for_update())).scalar_one_or_none()
            if not payment:
                from .partners import renewal_terms as partner_renewal_terms
                renewal_partner=await partner_renewal_terms(db,sub.id)
                payment=shop.Payment(**renewal_partner,user_id=user.id,subscription_id=sub.id,plan_id=plan.id,provider="yookassa",provider_payment_id=None,order_id=order_id,amount=renewal_amount,original_amount=renewal_amount,discount_amount=shop.Decimal("0"),duration_days_snapshot=int(terms['days']),traffic_limit_gb_snapshot=terms['traffic_gb'],device_limit_snapshot=terms['devices'],remnawave_profile_id_snapshot=terms['profile_id'],referrer_id_snapshot=user.referred_by_id,referral_terms_snapshot=await shop.referral_snapshot(db,user),currency=shop.settings.default_currency,status="creating",fulfillment_status="pending",paid_at=None)
                db.add(payment); await db.flush()
            method.last_attempt_at=shop.datetime.utcnow(); method.next_attempt_at=shop.datetime.utcnow()+shop.timedelta(hours=24); sub.next_renewal_at=method.next_attempt_at; await db.commit()
            result=await shop.YooKassaProvider().charge_recurring(shop.Decimal(str(payment.amount)),order_id,f"Auto-renew {plan.name}",token)
            payment=(await db.execute(shop.select(shop.Payment).where(shop.Payment.order_id==order_id).execution_options(populate_existing=True).with_for_update())).scalar_one()
            payment.provider_payment_id=result["id"]; payment.status="pending"; payment.fulfillment_status="pending"; await db.commit()
            # Never fulfill until YooKassa confirms succeeded + amount/currency.
            if await shop.YooKassaProvider().verify_succeeded(result["id"],shop.Decimal(str(payment.amount)),payment.currency,payment.order_id):
                payment_lock, payment_token = await shop._acquire_payment_side_effect_lock(payment.id)
                try:
                    p=(await db.execute(shop.select(shop.Payment).where(shop.Payment.provider_payment_id==result["id"]).execution_options(populate_existing=True).with_for_update())).scalar_one()
                    if p.status in {"refunded", "refunded_pending_revoke"}:
                        continue
                    p.status="paid"; p.paid_at=p.paid_at or shop.datetime.utcnow()
                    await shop._record_paid(db,p); await db.commit()
                finally:
                    await shop._release_payment_side_effect_lock(payment_lock, payment_token)
                try:
                    await shop.fulfill(p.id,db,existing_user_lock_token=user_token)
                    await db.refresh(p)
                    if p.fulfillment_status!='completed':continue
                    method.last_success_at=shop.datetime.utcnow(); method.failure_count=0; method.status="active"; method.last_error=None; method.next_attempt_at=shop.datetime.utcnow()+shop.timedelta(days=20); sub.next_renewal_at=method.next_attempt_at; sub.lifecycle_status="active"; sub.grace_until=None; sub.last_renewal_failure_at=None; await db.commit()
                except Exception as exc:
                    method.last_error=str(exc)[:1000]; await db.commit()
            else:
                method.failure_count=(method.failure_count or 0)+1; method.status="past_due"; method.last_error="Recurring payment not confirmed as succeeded"
                method.next_attempt_at=shop.datetime.utcnow()+shop.timedelta(hours=min(72,2**min(method.failure_count,6))); sub.next_renewal_at=method.next_attempt_at
                if method.failure_count>=3: method.status="payment_failed"; user.auto_renew_enabled=False; method.enabled=False
                await db.commit()
        except Exception as exc:
            # The rollback expires every loaded row; reload by id (an attribute read here would need
            # IO outside the async context and the whole pass would stop at this customer).
            await db.rollback()
            method=(await db.execute(shop.select(shop.AutoRenewMethod).where(shop.AutoRenewMethod.user_id==customer_id))).scalar_one_or_none()
            if method:
                sub=await db.get(shop.Subscription,candidate_subscription_id)
                user=await db.get(shop.User,customer_id)
                method.last_attempt_at=shop.datetime.utcnow(); method.failure_count=(method.failure_count or 0)+1; method.status="past_due"; method.last_error=str(exc)[:1000]
                method.next_attempt_at=shop.datetime.utcnow()+shop.timedelta(hours=min(72,2**min(method.failure_count,6)))
                if sub: sub.next_renewal_at=method.next_attempt_at
                if method.failure_count>=3:
                    method.status="payment_failed"; method.enabled=False
                    if user: user.auto_renew_enabled=False
                await db.commit()
        finally:
            if renew_lock and renew_token:
                await shop._release_payment_side_effect_lock(renew_lock,renew_token)
            if user_lock and user_token:
                await shop._release_payment_side_effect_lock(user_lock,user_token)


async def auto_renew_scheduler():
    while True:
        try:
            await shop.asyncio.sleep(900)
            if not shop.settings.auto_renew_enabled: continue
            async with shop.AsyncSession(shop.engine,expire_on_commit=False) as db:
                await run_auto_renew_pass(db)
        except Exception: await shop.asyncio.sleep(60)

async def cleanup_expired_promo_reservations(db,now):
    stale=(await db.execute(shop.select(shop.PromoReservation).outerjoin(shop.Payment,shop.Payment.id==shop.PromoReservation.payment_id).where(
        shop.PromoReservation.status=="reserved",shop.PromoReservation.expires_at<=now,
        shop.or_(shop.Payment.id.is_(None),shop.Payment.status.notin_(["paid","fulfilled"]))).with_for_update(skip_locked=True,of=shop.PromoReservation).limit(200))).scalars().all()
    for reservation in stale:await shop.release_promo_reservation(db,reservation.id)
    return len(stale)


async def reconciliation_scheduler():
    while True:
        try:
            await shop.asyncio.sleep(600)
            async with shop.AsyncSession(shop.engine,expire_on_commit=False) as db:
                now=shop.datetime.utcnow()
                await shop.cleanup_expired_promo_reservations(db,now)
                cutoff=now-shop.timedelta(hours=24)
                rows=(await db.execute(shop.select(shop.Payment).where(shop.Payment.created_at>=cutoff,shop.Payment.status.in_(["pending","creation_unknown"])).order_by(shop.Payment.id).limit(50))).scalars().all()
                providers={"yookassa":shop.YooKassaProvider(),"platega":shop.PlategaProvider(),"rollypay":shop.RollyPayProvider(),"stripe":shop.StripePlatform(),"paypal":shop.PayPalPlatform(),"crypto":shop.CryptoGatewayPlatform()}
                for p in rows:
                    provider=providers.get(p.provider)
                    if not provider or not hasattr(provider,"verify_succeeded"): continue
                    try:
                        if p.status=="creation_unknown" and p.provider=="yookassa" and not p.provider_payment_id:
                            found=await provider.find_by_order_id(p.order_id, p.created_at)
                            if not found or not found.get("id"):
                                continue
                            p.provider_payment_id=str(found["id"]); p.checkout_url=(found.get("confirmation") or {}).get("confirmation_url") or p.checkout_url; p.status="pending"; p.fulfillment_terminal=False
                        if not p.provider_payment_id:
                            continue
                        if await provider.verify_succeeded(p.provider_payment_id,shop.Decimal(str(p.amount)),p.currency,p.order_id):
                            try:
                                result=await shop._confirm_and_fulfill_payment(p.id,db)
                                if not result.get("ignored"):
                                    shop._METRICS["payment_fulfillment_total"] += 1
                            except Exception as exc:
                                shop.logger.warning("Non-critical operation failed: %s", exc)
                    except Exception as exc:
                        shop.logger.warning("Non-critical operation failed: %s", exc)
                await db.commit()
        except Exception: await shop.asyncio.sleep(30)

async def run_lifecycle_pass(db, now=None) -> None:
    """One pass of the lifecycle scheduler: end cancelled and expired subscriptions and switch their panel user off.
    A panel error leaves the subscription in ``revoke_pending``; the next pass retries it."""
    now=now or shop.datetime.utcnow()
    ids=(await db.execute(shop.select(shop.Subscription.id).where(shop.Subscription.expires_at.is_not(None),shop.or_(shop.Subscription.expires_at<=now,shop.Subscription.scheduled_cancel_at<=now),shop.Subscription.lifecycle_status.not_in(["expired","cancelled"])).limit(100).with_for_update(skip_locked=True))).scalars().all()
    for sub_id in ids:
        sub=await db.get(shop.Subscription,sub_id)
        if not sub: continue
        if sub.grace_until and sub.grace_until>now and sub.lifecycle_status=="grace": continue
        user_lock,user_token=await shop._acquire_user_fulfillment_lock(sub.user_id,ttl=300)
        try:
            user=(await db.execute(shop.select(shop.User).where(shop.User.id==sub.user_id).execution_options(populate_existing=True).with_for_update())).scalar_one_or_none()
            sub=(await db.execute(shop.select(shop.Subscription).where(shop.Subscription.id==sub_id).execution_options(populate_existing=True).with_for_update())).scalar_one_or_none()
            if not user or not sub or user.deleted_at is not None: continue
            now=shop.datetime.utcnow()
            if sub.grace_until and sub.grace_until>now and sub.lifecycle_status=="grace": continue
            if sub.scheduled_cancel_at and sub.scheduled_cancel_at<=now:
                if sub.remnawave_uuid:
                    sub.lifecycle_status="revoke_pending"; await db.commit()
                    try:
                        await shop.RemnawaveClient().disable_user(sub.remnawave_uuid)
                        sub.lifecycle_status="cancelled"; sub.cancelled_at=now; await shop.audit(db,"subscription.lifecycle.cancelled","system",str(sub.id))
                    except Exception as exc:
                        await db.rollback(); sub=await db.get(shop.Subscription,sub_id); sub.lifecycle_status="revoke_pending"; await shop.audit(db,"subscription.lifecycle.revoke_pending","system",str(sub.id),{"error":str(exc)[:500]}); await db.commit(); continue
                else:
                    sub.lifecycle_status="cancelled"; sub.cancelled_at=now; await shop.audit(db,"subscription.lifecycle.cancelled","system",str(sub.id))
            elif sub.expires_at and sub.expires_at<=now and sub.grace_until and sub.grace_until<=now and sub.remnawave_uuid:
                sub.lifecycle_status="revoke_pending"; await db.commit()
                try:
                    await shop.RemnawaveClient().disable_user(sub.remnawave_uuid)
                    sub.lifecycle_status="expired"; await shop.audit(db,"subscription.lifecycle.expired","system",str(sub.id))
                except Exception as exc:
                    await db.rollback(); sub=await db.get(shop.Subscription,sub_id); sub.lifecycle_status="revoke_pending"; await shop.audit(db,"subscription.lifecycle.revoke_pending","system",str(sub.id),{"error":str(exc)[:500]}); await db.commit(); continue
            elif sub.expires_at and sub.expires_at<=now:
                sub.lifecycle_status="expired"; await shop.audit(db,"subscription.lifecycle.expired","system",str(sub.id))
            await db.commit()
        finally:
            await shop._release_payment_side_effect_lock(user_lock,user_token)


async def subscription_lifecycle_scheduler():
    while True:
        try:
            async with shop.AsyncSession(shop.engine,expire_on_commit=False) as db:
                await run_lifecycle_pass(db)
        except Exception as exc:
            shop.logger.warning("Subscription lifecycle scheduler failed: %s", exc)
        await shop.asyncio.sleep(300)

async def notify_user_telegram(chat_id, text: str) -> None:
    if not chat_id or not shop.settings.bot_token:
        return
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
            response = await client.post(
                f"https://api.telegram.org/bot{shop.settings.bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": text[:1000]},
            )
            if response.status_code >= 400:
                shop.logger.warning("Telegram notify failed: HTTP %s", response.status_code)
    except Exception as exc:
        shop.logger.warning("Telegram notify failed: %s", exc)

async def expiry_notification_scheduler():
    # Notifications are sent at most once per day via Redis markers.
    while True:
        try:
            # In-app notification and push for every customer, with or without Telegram
            # (app-only and e-mail customers got no reminder before v28.32.0).
            from .app_growth import enqueue_expiry_notifications
            async with shop.AsyncSession(shop.engine,expire_on_commit=False) as db:
                await enqueue_expiry_notifications(db)
            if shop.settings.bot_token and shop.redis_client is not None:
                async with shop.AsyncSession(shop.engine,expire_on_commit=False) as db:
                    until=shop.datetime.utcnow()+shop.timedelta(days=shop.settings.notification_expiry_days)
                    rows=(await db.execute(shop.select(shop.User,shop.Subscription).join(shop.Subscription,shop.Subscription.user_id==shop.User.id).where(shop.User.telegram_id.is_not(None),shop.Subscription.expires_at>shop.datetime.utcnow(),shop.Subscription.expires_at<=until).limit(500))).all()
                    import httpx
                    async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
                        for u,sub in rows:
                            key=f"expiry-notify:{u.id}:sub:{sub.id}:{sub.expires_at.date()}"
                            sending_key=key+":sending"
                            if not await shop.redis_client.set(sending_key,"1",nx=True,ex=300):
                                continue
                            try:
                                resp=await client.post(
                                    f"https://api.telegram.org/bot{shop.settings.bot_token}/sendMessage",
                                    json={"chat_id":u.telegram_id,"text":f"⚠️ Ваша VPN-подписка истекает {sub.expires_at:%d.%m.%Y}. Откройте магазин для продления.\nYour VPN subscription expires on {sub.expires_at:%d.%m.%Y}. Open the shop to renew."},
                                )
                                if resp.status_code >= 400:
                                    raise RuntimeError(f"Telegram notification failed: HTTP {resp.status_code}")
                                await shop.redis_client.set(key,"1",ex=86400*7)
                            except Exception as exc:
                                try: await shop.redis_client.delete(sending_key)
                                except Exception as cleanup_exc:
                                    shop.logger.warning("Failed to clear notification delivery lock: %s", cleanup_exc)
                                shop.logger.warning("Expiry notification failed for user %s: %s",u.id,exc)
            await shop.asyncio.sleep(3600)
        except Exception: await shop.asyncio.sleep(3600)


__all__ = ['RECURRING_IDEMPOTENCE_WINDOW', '_record_paid', 'adopt_or_retry_recurring', 'auto_renew_chargeable', 'auto_renew_scheduler', 'cleanup_expired_promo_reservations', 'expiry_notification_scheduler', 'fulfillment_retry_scheduler', 'notify_user_telegram', 'reconciliation_scheduler', 'refund_revoke_scheduler', 'subscription_lifecycle_scheduler', 'run_lifecycle_pass', 'run_auto_renew_pass']
# Imported before main finished (``from app import schedulers`` first)? Then main's star
# import saw a half-loaded module; hand the names over now that they exist.
shop.__dict__.update({_n: globals()[_n] for _n in __all__})
