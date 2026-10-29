"""Admin recovery and reconciliation endpoints moved out of main.py (v28.31.0).

Names that belong to main are read through ``shop.<name>`` at call time, so tests and
operators that patch ``app.main`` keep affecting this code exactly as before."""
from .gateways import instances as extra_gateways
from . import main as shop

# ---------- Admin Recovery / Reconciliation ----------
@shop.app.get("/api/admin/recovery/operations")
async def recovery_operations(db:shop.AsyncSession=shop.Depends(shop.get_db),admin=shop.Depends(shop.require_permission("read"))):
    rows=(await db.execute(shop.select(shop.ProvisioningOperation).order_by(shop.ProvisioningOperation.updated_at.desc()).limit(200))).scalars().all()
    return [{"id":x.id,"payment_id":x.payment_id,"user_id":x.user_id,"operation_key":x.operation_key,"status":x.status,"attempts":x.attempts,"last_error":"unavailable" if x.last_error else None,"remote_user_id":x.remote_user_id,"updated_at":x.updated_at} for x in rows]

@shop.app.post("/api/admin/recovery/operations/{operation_id}/retry")
async def retry_operation(operation_id:int,db:shop.AsyncSession=shop.Depends(shop.get_db),admin=shop.Depends(shop.require_permission("payments.retry"))):
    opx=await db.get(shop.ProvisioningOperation,operation_id)
    if not opx: raise shop.HTTPException(404,"Operation not found")
    opx.status="retry"; opx.updated_at=shop.datetime.utcnow(); await db.commit()
    try: await shop.fulfill(opx.payment_id,db)
    except Exception as exc:
        shop.logger.warning("Provisioning retry failed for operation %s: %s", operation_id, exc)
        return {"ok":False,"error":"Повтор выдачи не выполнен"}
    return {"ok":True,"status":"completed"}

@shop.app.get("/api/admin/refunds")
async def admin_refunds(db:shop.AsyncSession=shop.Depends(shop.get_db),admin=shop.Depends(shop.require_permission("read"))):
    rows=(await db.execute(shop.select(shop.RefundRequest).order_by(shop.RefundRequest.id.desc()).limit(200))).scalars().all()
    return [{"id":x.id,"payment_id":x.payment_id,"user_id":x.user_id,"amount":str(x.amount),"status":x.status,"reason":shop._public_refund_reason(x.reason),"provider_refund_id":x.provider_refund_id,"created_at":x.created_at} for x in rows]

@shop.app.post("/api/admin/payments/{payment_id}/refund-request")
async def request_refund(payment_id:int,payload:shop.RefundIn,db:shop.AsyncSession=shop.Depends(shop.get_db),admin=shop.Depends(shop.require_permission("payments.reconcile"))):
    # Serialize refund creation on the payment row to avoid duplicate refund requests under concurrent admin actions.
    p=(await db.execute(shop.select(shop.Payment).where(shop.Payment.id==payment_id).execution_options(populate_existing=True).with_for_update())).scalar_one_or_none()
    if not p: raise shop.HTTPException(404,"Payment not found")
    if p.status not in {"paid","fulfilled"}: raise shop.HTTPException(400,"Payment is not refundable in its current state")
    existing=(await db.execute(shop.select(shop.RefundRequest).where(shop.RefundRequest.payment_id==payment_id).execution_options(populate_existing=True).with_for_update())).scalar_one_or_none()
    if existing: return {"id":existing.id,"status":existing.status}
    r=shop.RefundRequest(payment_id=p.id,user_id=p.user_id,amount=p.amount,reason=payload.reason,status="requested")
    db.add(r); await shop.audit(db,"payment.refund.requested",admin.email,str(p.id),payload.reason); await db.commit(); await db.refresh(r)
    return {"id":r.id,"status":r.status,"note":"Provider-specific refund must be confirmed through the configured provider adapter."}

@shop.app.post("/api/admin/refunds/{refund_id}/approve")
async def approve_refund(refund_id:int,db:shop.AsyncSession=shop.Depends(shop.get_db),admin=shop.Depends(shop.require_permission("payments.reconcile"))):
    r=await db.get(shop.RefundRequest,refund_id)
    if not r: raise shop.HTTPException(404,"Refund not found")
    if r.status not in {"requested","review"}: raise shop.HTTPException(400,"Invalid refund state")
    r.status="approved"; r.updated_at=shop.datetime.utcnow(); await shop.audit(db,"payment.refund.approved",admin.email,str(r.payment_id)); await db.commit()
    return {"ok":True,"status":r.status}

async def _reverse_referral_reward_for_refund(db:shop.AsyncSession, payment:shop.Payment, actor:str):
    """Claw back a referral reward exactly once when its payment is refunded.

    The balance update is atomic and may become negative when the referrer has
    already withdrawn/spent the reward; that represents an outstanding
    clawback instead of silently creating money.
    """
    from .referral_program import reverse_extra
    from .partners import reverse as reverse_partner
    await reverse_partner(db, payment)
    await db.scalar(shop.select(shop.Payment.id).where(shop.Payment.id==payment.id).with_for_update())
    reward=(await db.execute(shop.select(shop.ReferralReward).where(shop.ReferralReward.payment_id==payment.id).execution_options(populate_existing=True).with_for_update())).scalar_one_or_none()
    if not reward or reward.status == "reversed":
        extra = await reverse_extra(db, payment)
        return {"reversed":extra > 0,"amount":str(extra),"reason":"already_reversed_or_missing"}
    result=await db.execute(shop.update(shop.User).where(shop.User.id==reward.referrer_id).values(referral_balance=shop.User.referral_balance-reward.amount))
    if result.rowcount != 1:
        raise RuntimeError("Referrer account not found during reward reversal")
    reward.status="reversed"
    db.add(shop.ReferralLedger(user_id=reward.referrer_id,source_user_id=reward.referred_user_id,payment_id=None,amount=-reward.amount,kind=f"refund_reversal:{payment.id}"))
    await shop.audit(db,"referral.reward.reversed",actor,str(reward.id),{"payment_id":payment.id,"amount":str(reward.amount)})
    extra = await reverse_extra(db, payment)
    return {"reversed":True,"amount":str(reward.amount + extra)}

async def _safe_revoke_for_refunded_payment(db:shop.AsyncSession, payment:shop.Payment, admin_email:str, audit_action:str):
    """Reverse the purchased benefit, without touching unrelated subscriptions."""
    if payment.purpose == "topup":
        from .refund_accounting import reverse_wallet_topup
        return await reverse_wallet_topup(db, payment)
    sub=await shop.payment_target(db,payment,lock=True)
    if not sub or not sub.remnawave_uuid:
        return {"revoked":False,"reason":"no_remote_subscription"}
    later_paid=await db.scalar(shop.select(shop.func.count()).select_from(shop.Payment).where(
        shop.Payment.user_id==payment.user_id, shop.Payment.subscription_id==payment.subscription_id, shop.Payment.id>payment.id,
        shop.Payment.status.in_({"paid","fulfilled"}), shop.Payment.fulfillment_status=="completed"))
    if later_paid:
        await shop.audit(db,"subscription.revoke.skipped_refund_older_payment",admin_email,str(sub.id),{"payment_id":payment.id,"later_paid_count":int(later_paid)})
        return {"revoked":False,"reason":"newer_fulfilled_payment"}
    now=shop.datetime.utcnow()
    marker_key=f"refund_revoke:{payment.id}"
    if await db.get(shop.AppSetting,marker_key):
        # Already taken back once (retries and reconcile calls must not subtract again).
        return {"revoked":True,"already_applied":True}
    paid_days=int(payment.duration_days_snapshot or 0)
    if not paid_days and payment.purpose=="subscription" and payment.plan_id:
        # Payments from releases before the snapshot column: the plan's term is what was sold.
        plan=await db.get(shop.Plan,payment.plan_id)
        paid_days=int(plan.duration_days or 0) if plan else 0
    days=paid_days+int(payment.bonus_days or 0)
    if days>0 and sub.expires_at and sub.expires_at-shop.timedelta(days=days)>now:
        # Only the refunded payment's days are taken back: time paid by earlier
        # payments, gifts and operator extensions stays with the customer.
        remaining=sub.expires_at-shop.timedelta(days=days)
        await shop.RemnawaveClient().patch_user(sub.remnawave_uuid,{"expireAt":remaining.isoformat()})
        sub.expires_at=remaining
        db.add(shop.AppSetting(key=marker_key,value=now.isoformat()))
        await shop.audit(db,audit_action,admin_email,str(sub.id),{"payment_id":payment.id,"days_removed":days,"expires_at":remaining.isoformat()})
        return {"revoked":True,"days_removed":days,"expires_at":remaining.isoformat()}
    await shop.RemnawaveClient().disable_user(sub.remnawave_uuid)
    sub.expires_at=now
    db.add(shop.AppSetting(key=marker_key,value=now.isoformat()))
    await shop.audit(db,audit_action,admin_email,str(sub.id),{"payment_id":payment.id})
    return {"revoked":True}


@shop.app.post("/api/admin/refunds/{refund_id}/execute")
async def execute_refund(refund_id:int,db:shop.AsyncSession=shop.Depends(shop.get_db),admin=shop.Depends(shop.require_permission("payments.refund"))):
    r=await db.get(shop.RefundRequest,refund_id)
    if not r: raise shop.HTTPException(404,"Refund not found")
    if r.status not in {"requested","approved","review"}: raise shop.HTTPException(400,"Refund must be requested, approved, or retried from review")
    p=await db.get(shop.Payment,r.payment_id)
    if not p: raise shop.HTTPException(404,"Payment not found")
    provider={"yookassa":shop.YooKassaProvider(),"platega":shop.PlategaProvider(),"rollypay":shop.RollyPayProvider(),"stripe":shop.StripePlatform(),"paypal":shop.PayPalPlatform(),"telegram_stars":shop.TelegramStarsProvider()}.get(p.provider)
    if not provider or not hasattr(provider,"refund"): raise shop.HTTPException(409,"Automatic refund is not supported by this provider adapter")
    # Claim the refund before calling the external provider. The state transition is
    # committed separately so a second admin request cannot issue a second refund.
    await db.execute(shop.sql_text("SELECT id FROM refund_requests WHERE id=:id FOR UPDATE"), {"id": refund_id})
    r=await db.get(shop.RefundRequest,refund_id)
    if not r or r.status not in {"requested","approved","review"}: raise shop.HTTPException(409,"Refund is already processing or completed")
    if r.provider_refund_id: raise shop.HTTPException(409,"Refund provider operation already exists; reconcile its status")
    user_lock, user_token = await shop._acquire_user_fulfillment_lock(p.user_id,ttl=300)
    payment_lock = payment_token = None
    try:
        payment_lock, payment_token = await shop._acquire_payment_side_effect_lock(p.id)
        p=(await db.execute(shop.select(shop.Payment).where(shop.Payment.id==p.id).execution_options(populate_existing=True).with_for_update())).scalar_one()
        r=(await db.execute(shop.select(shop.RefundRequest).where(shop.RefundRequest.id==refund_id).execution_options(populate_existing=True).with_for_update())).scalar_one()
        if r.status not in {"requested","approved","review"} or r.provider_refund_id:
            raise shop.HTTPException(409,"Refund is already processing or completed")
        r.status="processing"; r.updated_at=shop.datetime.utcnow(); await shop.audit(db,"payment.refund.processing",admin.email,str(p.id)); await db.commit()
        result=await provider.refund(p.provider_payment_id,p.amount,p.currency,f"Refund for order {p.order_id}")
        provider_refund_id=result.get("id")
        if not provider_refund_id: raise RuntimeError("Provider returned no refund ID")
        async with shop.AsyncSession(shop.engine,expire_on_commit=False) as edb:
            rr=await edb.get(shop.RefundRequest,refund_id); pp=await edb.get(shop.Payment,p.id)
            rr.provider_refund_id=provider_refund_id; rr.updated_at=shop.datetime.utcnow()
            status=str(result.get("status") or "processing").lower()
            if status in {"succeeded","paid","completed","refunded"}:
                rr.status="refunded"; pp.status="refunded"; pp.fulfillment_terminal=True
                await shop.record_financial_event(edb, operation_key=f"payment:{pp.id}:refund:{rr.id}", user_id=pp.user_id, payment_id=pp.id, kind="refund", direction="debit", amount=shop.Decimal(str(pp.amount)), currency=pp.currency, metadata={"provider": pp.provider, "refund_id": rr.id, "provider_refund_id": provider_refund_id})
                try:
                    await shop._safe_revoke_for_refunded_payment(edb,pp,admin.email,"subscription.revoked.refund")
                except Exception as exc:
                    rr.status="refunded_pending_revoke"; rr.reason=(rr.reason or "")+"\nRevoke pending: "+str(exc)[:500]
            else:
                rr.status="processing"
            if rr.status == "refunded":
                await shop._reverse_referral_reward_for_refund(edb,pp,admin.email)
            await shop.audit(edb,"payment.refund.executed",admin.email,str(pp.id),result); await edb.commit()
        return {"ok":True,"status":rr.status,"provider_refund_id":provider_refund_id}
    except Exception as exc:
        async with shop.AsyncSession(shop.engine,expire_on_commit=False) as edb:
            rr=await edb.get(shop.RefundRequest,refund_id)
            if rr and not rr.provider_refund_id:
                rr.status="review"; rr.reason=(rr.reason or "")+"\nProvider refund outcome uncertain/failed: "+str(exc)[:500]; rr.updated_at=shop.datetime.utcnow()
                await shop.audit(edb,"payment.refund.execute_failed",admin.email,str(p.id),{"error":str(exc)[:500]}); await edb.commit()
        raise shop.HTTPException(503,"Refund provider operation failed or has an uncertain outcome; reconcile before retrying") from exc
    finally:
        if payment_lock and payment_token:
            await shop._release_payment_side_effect_lock(payment_lock, payment_token)
        await shop._release_payment_side_effect_lock(user_lock, user_token)

@shop.app.post("/api/admin/refunds/{refund_id}/retry-revoke")
async def retry_refund_revoke(refund_id:int,db:shop.AsyncSession=shop.Depends(shop.get_db),admin=shop.Depends(shop.require_permission("payments.refund"))):
    r=await db.get(shop.RefundRequest,refund_id)
    if not r or r.status != "refunded_pending_revoke": raise shop.HTTPException(404,"Refund requiring revoke not found")
    p=await db.get(shop.Payment,r.payment_id)
    if not p: raise shop.HTTPException(404,"Payment not found")
    user_lock, user_token = await shop._acquire_user_fulfillment_lock(p.user_id,ttl=300)
    payment_lock = payment_token = None
    try:
        payment_lock, payment_token = await shop._acquire_payment_side_effect_lock(p.id)
        p=(await db.execute(shop.select(shop.Payment).where(shop.Payment.id==p.id).execution_options(populate_existing=True).with_for_update())).scalar_one()
        r=(await db.execute(shop.select(shop.RefundRequest).where(shop.RefundRequest.id==r.id).execution_options(populate_existing=True).with_for_update())).scalar_one()
        if r.status != "refunded_pending_revoke" or p.status not in {"refunded","refunded_pending_revoke"}:
            raise shop.HTTPException(409,"Refund is not pending revoke")
        result=await shop._safe_revoke_for_refunded_payment(db,p,admin.email,"subscription.revoked.refund.retry")
        r.status="refunded"; r.updated_at=shop.datetime.utcnow()
        reversal_result=await shop._reverse_referral_reward_for_refund(db,p,admin.email)
        await db.commit()
        return {"ok":True,"status":"refunded",**result,**reversal_result}
    except Exception as exc:
        r.status="refunded_pending_revoke"; r.reason=(r.reason or "")+"\nRevoke retry pending: "+str(exc)[:500]; await db.commit(); raise shop.HTTPException(503,"Remnawave revoke failed") from exc
    finally:
        if payment_lock and payment_token:
            await shop._release_payment_side_effect_lock(payment_lock, payment_token)
        await shop._release_payment_side_effect_lock(user_lock, user_token)

@shop.app.post("/api/admin/refunds/{refund_id}/mark-refunded")
async def mark_refunded(refund_id:int,admin=shop.Depends(shop.require_permission("payments.refund"))):
    raise shop.HTTPException(410,"Manual mark-refunded is disabled; execute or reconcile the provider refund instead")

# Store support is canonical; Support Pro uses the scoped bridge API.
@shop.app.get("/api/admin/support/tickets")
async def admin_tickets(db:shop.AsyncSession=shop.Depends(shop.get_db),admin=shop.Depends(shop.require_permission("support.read"))):
    rows=(await db.execute(shop.select(shop.SupportTicket).order_by(shop.SupportTicket.id.desc()).limit(200))).scalars().all()
    return [{"id":x.id,"user_id":x.user_id,"subject":x.subject,"message":x.message,"status":x.status,"admin_reply":x.admin_reply,"merged_into_id":x.merged_into_id,"created_at":x.created_at,"updated_at":x.updated_at} for x in rows]

# Store support is canonical; Support Pro uses the scoped bridge API.
@shop.app.post("/api/admin/support/tickets/{ticket_id}/reply")
async def admin_ticket_reply(ticket_id:int,payload:shop.AdminTicketReplyIn,db:shop.AsyncSession=shop.Depends(shop.get_db),admin=shop.Depends(shop.require_permission("support.write")),request:shop.Request=None):
    from .support_threads import append_message
    t=(await db.execute(shop.select(shop.SupportTicket).where(shop.SupportTicket.id==ticket_id).with_for_update())).scalar_one_or_none()
    if not t: raise shop.HTTPException(404,"Ticket not found")
    reply=payload.reply.strip()
    if not reply: raise shop.HTTPException(400,"Ответ не может быть пустым")
    key=request.headers.get("Idempotency-Key") if request else None
    if not key and not payload.attachment_ids and t.admin_reply==reply and t.status=="resolved": return {"ok":True,"status":t.status}
    message,created=await append_message(db,t,"admin",reply,key,payload.attachment_ids,f"admin:{admin.email}")
    if created:
        db.add(shop.Notification(user_id=t.user_id,channel="in_app",kind="support.reply",title=f"Ответ на обращение #{t.id}",body=reply,status="sent",dedupe_key=f"support-message:{message.id}",sent_at=shop.datetime.utcnow()))
        await shop.audit(db,"support.ticket.replied",admin.email,str(t.id))
    await db.commit()
    return {"ok":True,"status":t.status,"message_id":message.id,"created":created}

@shop.app.get("/api/admin/support/tickets/{ticket_id}/messages")
async def admin_support_messages(ticket_id:int,after:int=shop.Query(0,ge=0),db:shop.AsyncSession=shop.Depends(shop.get_db),admin=shop.Depends(shop.require_permission("support.read"))):
    from .support_threads import read_thread
    ticket=await db.get(shop.SupportTicket,ticket_id)
    if not ticket: raise shop.HTTPException(404,"Ticket not found")
    return await read_thread(db,ticket,after)

@shop.app.get("/api/admin/referrals/withdrawals")
async def admin_withdrawals(db:shop.AsyncSession=shop.Depends(shop.get_db),admin=shop.Depends(shop.require_permission("referrals.withdrawals.read"))):
    rows=(await db.execute(shop.select(shop.WithdrawalRequest).order_by(shop.WithdrawalRequest.id.desc()).limit(200))).scalars().all()
    return [{"id":x.id,"user_id":x.user_id,"amount":str(x.amount),"destination":x.destination,"status":x.status,"created_at":x.created_at} for x in rows]

@shop.app.post("/api/admin/referrals/withdrawals/{withdrawal_id}/reject")
async def reject_withdrawal(withdrawal_id:int,payload:shop.AdminTicketReplyIn|None=None,db:shop.AsyncSession=shop.Depends(shop.get_db),admin=shop.Depends(shop.require_permission("referrals.withdrawals.approve"))):
    await db.execute(shop.sql_text("SELECT id FROM withdrawal_requests WHERE id=:id FOR UPDATE"),{"id":withdrawal_id})
    x=await db.get(shop.WithdrawalRequest,withdrawal_id)
    if not x: raise shop.HTTPException(404,"Withdrawal not found")
    # Once approval created a payout transaction, the amount may already be in the
    # external/manual payout workflow. Restoring the balance while that payout remains
    # payable would create a real double-spend. Only an untouched request is reversible.
    if x.status != "requested": raise shop.HTTPException(409,"Only untouched requested withdrawals can be rejected safely")
    payout=(await db.execute(shop.select(shop.PayoutTransaction).where(shop.PayoutTransaction.withdrawal_id==x.id).with_for_update())).scalar_one_or_none()
    if payout and payout.status not in {"failed","cancelled","canceled"}:
        raise shop.HTTPException(409,"Payout transaction is already active; reconcile it before restoring the balance")
    if payout:
        await db.delete(payout)
    result=await db.execute(shop.sql_text("UPDATE users SET referral_balance=referral_balance+:amount WHERE id=:uid"),{"amount":x.amount,"uid":x.user_id})
    if result.rowcount != 1: raise shop.HTTPException(409,"User balance could not be restored")
    x.status="rejected"; x.admin_note=(payload.reply.strip() if payload else None); x.updated_at=shop.datetime.utcnow()
    db.add(shop.ReferralLedger(user_id=x.user_id,source_user_id=None,payment_id=None,amount=x.amount,kind=f"withdrawal_reversal:{x.id}"))
    await shop.audit(db,"referral.withdrawal.rejected",admin.email,str(x.id),x.admin_note); await db.commit(); return {"ok":True,"status":x.status}

@shop.app.post("/api/admin/referrals/withdrawals/{withdrawal_id}/approve")
async def approve_withdrawal(withdrawal_id:int,db:shop.AsyncSession=shop.Depends(shop.get_db),admin=shop.Depends(shop.require_permission("referrals.withdrawals.approve"))):
    await db.execute(shop.sql_text("SELECT id FROM withdrawal_requests WHERE id=:id FOR UPDATE"),{"id":withdrawal_id})
    x=await db.get(shop.WithdrawalRequest,withdrawal_id)
    if not x: raise shop.HTTPException(404,"Withdrawal not found")
    if x.status!="requested": raise shop.HTTPException(409,"Withdrawal must be requested before approval")
    payout=(await db.execute(shop.select(shop.PayoutTransaction).where(shop.PayoutTransaction.withdrawal_id==x.id).with_for_update())).scalar_one_or_none()
    if payout: raise shop.HTTPException(409,"Payout transaction already exists")
    x.status="approved"; x.updated_at=shop.datetime.utcnow(); db.add(shop.PayoutTransaction(withdrawal_id=x.id,amount=x.amount,provider="manual",status="processing")); await shop.audit(db,"referral.withdrawal.approved",admin.email,str(x.id)); await db.commit(); return {"ok":True,"status":x.status}

@shop.app.post("/api/admin/referrals/withdrawals/{withdrawal_id}/paid")
async def paid_withdrawal(withdrawal_id:int,db:shop.AsyncSession=shop.Depends(shop.get_db),admin=shop.Depends(shop.require_permission("referrals.withdrawals.pay"))):
    await db.execute(shop.sql_text("SELECT id FROM withdrawal_requests WHERE id=:id FOR UPDATE"),{"id":withdrawal_id})
    x=await db.get(shop.WithdrawalRequest,withdrawal_id)
    payout=(await db.execute(shop.select(shop.PayoutTransaction).where(shop.PayoutTransaction.withdrawal_id==withdrawal_id).with_for_update())).scalar_one_or_none()
    if not x or not payout: raise shop.HTTPException(404,"Withdrawal/payout not found")
    if x.status not in {"approved","processing"}: raise shop.HTTPException(409,"Withdrawal must be approved or processing")
    x.status="paid"; x.updated_at=shop.datetime.utcnow(); payout.status="paid"; payout.paid_at=shop.datetime.utcnow(); payout.updated_at=shop.datetime.utcnow(); await shop.audit(db,"referral.withdrawal.paid",admin.email,str(x.id)); await db.commit(); return {"ok":True,"status":"paid"}

@shop.app.get("/api/admin/workers")
async def admin_workers(db:shop.AsyncSession=shop.Depends(shop.get_db),admin=shop.Depends(shop.require_permission("read"))):
    rows=(await db.execute(shop.select(shop.WorkerState).order_by(shop.WorkerState.last_seen_at.desc()))).scalars().all()
    now=shop.datetime.utcnow()
    return [{"worker_id":x.worker_id,"role":x.role,"status":"stale" if now-x.last_seen_at>shop.timedelta(seconds=90) else x.status,"current_job":x.current_job,"last_seen_at":x.last_seen_at} for x in rows]

@shop.app.get("/api/admin/releases")
async def admin_releases(db:shop.AsyncSession=shop.Depends(shop.get_db),admin=shop.Depends(shop.require_permission("read"))):
    rows=(await db.execute(shop.select(shop.ReleaseRecord).order_by(shop.ReleaseRecord.id.desc()).limit(50))).scalars().all()
    return [{"id":x.id,"version":x.version,"status":x.status,"rollback_archive":x.rollback_archive,"details":x.details,"created_at":x.created_at,"completed_at":x.completed_at} for x in rows]

@shop.app.post("/api/admin/releases/check")
async def check_release(db:shop.AsyncSession=shop.Depends(shop.get_db),admin=shop.Depends(shop.require_permission("read"))):
    return {"current":shop.APP_VERSION,"channel":"stable","update_available":False,"manifest_configured":bool(shop.settings.release_manifest_url and shop.settings.release_manifest_public_key),"note":"Only a signed release manifest may be activated by production update tooling."}

@shop.app.get("/api/admin/security/secrets/status")
async def secret_status(admin=shop.Depends(shop.require_permission("manage_admins"))):
    return {"APP_SECRET":"configured" if shop.settings.app_secret else "missing","TELEGRAM_BOT_TOKEN":"configured" if shop.settings.bot_token else "missing","REMNAWAVE_API_TOKEN":"configured" if shop.settings.remnawave_token else "missing","S3":"configured" if shop.settings.s3_access_key and shop.settings.s3_secret_key else "missing","METRICS_TOKEN":"configured" if shop.settings.metrics_token else "missing"}

@shop.app.post("/api/admin/security/incident")
async def security_incident(payload:shop.IncidentIn,db:shop.AsyncSession=shop.Depends(shop.get_db),admin=shop.Depends(shop.require_permission("manage_admins"))):
    if payload.enabled:
        row=shop.SecurityIncident(kind="incident_mode",severity=payload.severity,details=payload.reason); db.add(row); await shop.set_setting(db,"incident_mode","1"); await shop.set_setting(db,"incident_reason",payload.reason); await shop.audit(db,"security.incident.enabled",admin.email,None,payload.reason)
    else:
        await shop.set_setting(db,"incident_mode","0"); await shop.set_setting(db,"incident_reason",payload.reason); await shop.audit(db,"security.incident.disabled",admin.email,None,payload.reason)
    await db.commit(); return {"ok":True,"enabled":payload.enabled}

@shop.app.get("/api/admin/security/incidents")
async def security_incidents(db:shop.AsyncSession=shop.Depends(shop.get_db),admin=shop.Depends(shop.require_permission("read"))):
    rows=(await db.execute(shop.select(shop.SecurityIncident).order_by(shop.SecurityIncident.id.desc()).limit(100))).scalars().all()
    return [{"id":x.id,"kind":x.kind,"severity":x.severity,"status":x.status,"details":x.details,"created_at":x.created_at,"resolved_at":x.resolved_at} for x in rows]

@shop.app.get("/api/admin/openapi.json")
async def admin_openapi(admin=shop.Depends(shop.require_permission("read"))):
    return shop.app.openapi()

@shop.app.get("/api/admin/recovery")
async def admin_recovery(db:shop.AsyncSession=shop.Depends(shop.get_db),admin=shop.Depends(shop.require_permission("read"))):
    restore_state=await shop.setting_value(db,"restore_state","ok")
    maintenance=await shop.maintenance_enabled(db)
    workers=(await db.execute(shop.select(shop.WorkerState).order_by(shop.WorkerState.last_seen_at.desc()))).scalars().all()
    now=shop.datetime.utcnow()
    heartbeat=[{"worker_id":w.worker_id,"role":w.role,"status":"stale" if now-w.last_seen_at>shop.timedelta(seconds=90) else w.status,"last_seen_at":w.last_seen_at} for w in workers]
    failed=int((await db.execute(shop.select(shop.func.count()).select_from(shop.Payment).where(shop.Payment.fulfillment_status=="failed",shop.Payment.fulfillment_terminal.is_(True)))).scalar() or 0)
    return {"maintenance_mode":maintenance,"incident_mode":await shop.setting_value(db,"incident_mode","0")=="1","restore_state":restore_state,"workers":heartbeat,"terminal_fulfillment_failures":failed,"recovery_required":maintenance or restore_state=="failed" or any(x["status"]=="stale" for x in heartbeat)}

@shop.app.post("/api/admin/incident-mode")
async def incident_mode(payload:dict,db:shop.AsyncSession=shop.Depends(shop.get_db),admin=shop.Depends(shop.require_permission("manage_admins"))):
    enabled=bool(payload.get("enabled")); await shop.set_setting(db,"incident_mode","1" if enabled else "0")
    maintenance_kept=False
    if enabled:
        await shop.set_setting(db,"maintenance_mode","1")
    else:
        # Incident mode switched maintenance on; switching it off lifts maintenance too, unless a
        # restore failed or is running: that state must stay locked until the operator checks it.
        restore_locked=False
        if shop.redis_client is not None:
            try: restore_locked=bool(await shop.redis_client.get("lock:maintenance"))
            except Exception as exc: shop.logger.warning("Maintenance lock check failed: %s", exc)
        if await shop.setting_value(db,"restore_state","ok")=="failed" or restore_locked:
            maintenance_kept=True
        else:
            await shop.set_setting(db,"maintenance_mode","0")
    await shop.audit(db,"security.incident_mode",admin.email,None,{"enabled":enabled,"maintenance_kept":maintenance_kept}); await db.commit()
    return {"enabled":enabled,"maintenance_mode":enabled or maintenance_kept or bool(shop.settings.maintenance_mode),"maintenance_kept":maintenance_kept}

@shop.app.get("/api/admin/incident-mode")
async def incident_mode_status(db:shop.AsyncSession=shop.Depends(shop.get_db),admin=shop.Depends(shop.require_permission("read"))):
    return {"enabled":await shop.setting_value(db,"incident_mode","0")=="1"}

@shop.app.post("/api/admin/referrals/reconcile")
async def reconcile_referrals(db:shop.AsyncSession=shop.Depends(shop.get_db),admin=shop.Depends(shop.require_permission("referrals.reconcile"))):
    users=(await db.execute(shop.select(shop.User).where(shop.User.referral_balance!=None).execution_options(populate_existing=True).with_for_update())).scalars().all(); changed=0
    for u in users:
        total=(await db.execute(shop.select(shop.func.coalesce(shop.func.sum(shop.ReferralLedger.amount),0)).where(shop.ReferralLedger.user_id==u.id))).scalar() or shop.Decimal("0")
        if shop.Decimal(str(u.referral_balance or 0)) != shop.Decimal(str(total)):
            u.referral_balance=total; changed+=1
    await shop.audit(db,"referral.reconciliation",admin.email,None,{"checked":len(users),"changed":changed}); await db.commit(); return {"checked":len(users),"changed":changed}

@shop.app.get("/api/admin/system/health")
async def system_health(admin=shop.Depends(shop.require_permission("read"))):
    disk=shop.shutil.disk_usage("/")
    mem_total=mem_avail=None
    try:
        vals={}
        for line in shop.pathlib.Path("/proc/meminfo").read_text().splitlines():
            k,v=line.split(":",1); vals[k]=int(v.strip().split()[0])*1024
        mem_total=vals.get("MemTotal"); mem_avail=vals.get("MemAvailable")
    except Exception as exc:
        shop.logger.warning("Non-critical operation failed: %s", exc)
    redis_ok=False; db_ok=False
    if shop.redis_client is not None:
        try: await shop.redis_client.ping(); redis_ok=True
        except Exception as exc:
            shop.logger.warning("Non-critical operation failed: %s", exc)
    try:
        async with shop.AsyncSession(shop.engine,expire_on_commit=False) as hdb: await hdb.execute(shop.sql_text("SELECT 1")); db_ok=True
    except Exception as exc:
        shop.logger.warning("Non-critical operation failed: %s", exc)
    worker_heartbeat=None
    worker_healthy=False
    worker_count=0
    try:
        async with shop.AsyncSession(shop.engine,expire_on_commit=False) as sdb:
            cutoff=shop.datetime.utcnow()-shop.timedelta(seconds=90)
            workers=(await sdb.execute(shop.select(shop.WorkerState).where(shop.WorkerState.role==shop.settings.worker_role, shop.WorkerState.status=="online", shop.WorkerState.last_seen_at>=cutoff).order_by(shop.WorkerState.last_seen_at.desc()))).scalars().all()
            worker_count=len(workers)
            if workers:
                worker_healthy=True
                worker_heartbeat=workers[0].last_seen_at.isoformat()
    except Exception as exc:
        shop.logger.exception("worker health lookup failed: %s", exc)
    incident=False
    try:
        async with shop.AsyncSession(shop.engine,expire_on_commit=False) as sdb: incident=await shop.setting_value(sdb,"incident_mode","0")=="1"
    except Exception as exc:
        shop.logger.exception("incident mode lookup failed: %s", exc)
    return {"api":True,"database":db_ok,"redis":redis_ok,"worker_heartbeat":worker_heartbeat,"worker_healthy":worker_healthy,"worker_count":worker_count,"incident_mode":incident,"disk":{"total":disk.total,"used":disk.used,"free":disk.free,"percent":round(disk.used/disk.total*100,1)},"memory":{"total":mem_total,"available":mem_avail,"percent":round((1-mem_avail/mem_total)*100,1) if mem_total and mem_avail else None},"backup_lock":shop.BACKUP_LOCK.locked(),"worker_role":shop.settings.worker_role}

@shop.app.get("/api/admin/analytics")
async def admin_analytics(db:shop.AsyncSession=shop.Depends(shop.get_db),admin=shop.Depends(shop.require_permission("analytics.read"))):
    now=shop.datetime.utcnow(); day=now-shop.timedelta(days=1); week=now-shop.timedelta(days=7); month=now-shop.timedelta(days=30)
    async def rev(since): return float((await db.execute(shop.select(shop.func.coalesce(shop.func.sum(shop.Payment.amount),0)).where(shop.Payment.status=="paid",shop.Payment.created_at>=since))).scalar() or 0)
    return {"revenue":{"24h":await rev(day),"7d":await rev(week),"30d":await rev(month)},"users":{"total":int((await db.execute(shop.select(shop.func.count()).select_from(shop.User).where(shop.User.deleted_at.is_(None)))).scalar() or 0),"new_24h":int((await db.execute(shop.select(shop.func.count()).select_from(shop.User).where(shop.User.created_at>=day,shop.User.deleted_at.is_(None)))).scalar() or 0)},"subscriptions":{"active":int((await db.execute(shop.select(shop.func.count()).select_from(shop.Subscription).where(shop.Subscription.expires_at>now))).scalar() or 0)},"payments":{"pending":int((await db.execute(shop.select(shop.func.count()).select_from(shop.Payment).where(shop.Payment.status=="pending"))).scalar() or 0),"fulfillment_failed":int((await db.execute(shop.select(shop.func.count()).select_from(shop.Payment).where(shop.Payment.fulfillment_status=="failed"))).scalar() or 0)}}

@shop.app.get("/api/admin/sessions")
async def admin_sessions(db:shop.AsyncSession=shop.Depends(shop.get_db),admin=shop.Depends(shop.require_permission("sessions.manage"))):
    rows=(await db.execute(shop.select(shop.AdminSession,shop.AdminUser.email).join(shop.AdminUser,shop.AdminUser.id==shop.AdminSession.admin_id).where(shop.AdminSession.revoked_at.is_(None),shop.AdminSession.expires_at>shop.datetime.utcnow()).order_by(shop.AdminSession.created_at.desc()).limit(200))).all()
    return [{"id":s.id,"admin_email":email,"ip":s.ip,"user_agent":s.user_agent,"created_at":s.created_at,"last_seen_at":s.last_seen_at,"expires_at":s.expires_at} for s,email in rows]

@shop.app.post("/api/admin/sessions/revoke-all")
async def revoke_all_sessions(request:shop.Request,response:shop.Response,db:shop.AsyncSession=shop.Depends(shop.get_db),admin=shop.Depends(shop.require_permission("sessions.manage"))):
    if admin.mfa_enabled:
        otp=request.headers.get("X-MFA-Code","")
        if not shop.verify_totp(admin,otp): raise shop.HTTPException(401,"Valid MFA code is required")
    await db.execute(__import__("sqlalchemy").update(shop.AdminSession).where(shop.AdminSession.admin_id==admin.id,shop.AdminSession.revoked_at.is_(None)).values(revoked_at=shop.datetime.utcnow()))
    await shop.audit(db,"security.sessions.revoked_all",admin.email,admin.email); await db.commit(); response.delete_cookie("rw_admin"); response.delete_cookie("rw_csrf"); return {"ok":True}

@shop.app.delete("/api/admin/sessions/{session_id}")
async def revoke_admin_session(session_id:int,db:shop.AsyncSession=shop.Depends(shop.get_db),admin=shop.Depends(shop.require_permission("sessions.manage"))):
    s=await db.get(shop.AdminSession,session_id);
    if not s: raise shop.HTTPException(404,"Session not found")
    s.revoked_at=shop.datetime.utcnow(); await shop.audit(db,"security.session.revoked",admin.email,str(session_id)); await db.commit(); return {"ok":True}

@shop.app.post("/api/admin/payments/reconcile")
async def reconcile_payments(db:shop.AsyncSession=shop.Depends(shop.get_db),admin=shop.Depends(shop.require_permission("payments.reconcile"))):
    cutoff=shop.datetime.utcnow()-shop.timedelta(hours=72)
    rows=(await db.execute(shop.select(shop.Payment).where(shop.Payment.created_at>=cutoff,((shop.Payment.status=="pending") | (shop.Payment.status=="creation_unknown") | ((shop.Payment.status=="paid") & (shop.Payment.fulfillment_status!="completed")))).order_by(shop.Payment.id).limit(500))).scalars().all()
    providers={"yookassa":shop.YooKassaProvider(),"platega":shop.PlategaProvider(),"rollypay":shop.RollyPayProvider(),"cryptobot":shop.CryptoBotProvider(),"freekassa":shop.FreekassaProvider(),**extra_gateways(),"stripe":shop.StripePlatform(),"paypal":shop.PayPalPlatform(),"crypto":shop.CryptoGatewayPlatform()}; changed=0; retried=0; recovered=0
    for p in rows:
        provider=providers.get(p.provider)
        if not provider or not hasattr(provider,"verify_succeeded"): continue
        try:
            if p.status=="creation_unknown" and p.provider=="yookassa" and not p.provider_payment_id:
                # A lost create response is recovered by the order id already stored at
                # YooKassa. Calling create() here used a fresh Idempotence-Key and opened
                # a second live charge.
                found=await provider.find_by_order_id(p.order_id, p.created_at)
                if not found or not found.get("id"):
                    continue
                p.provider_payment_id=str(found["id"]); p.checkout_url=(found.get("confirmation") or {}).get("confirmation_url") or p.checkout_url; p.status="pending"; p.fulfillment_terminal=False; recovered += 1
            if not p.provider_payment_id:
                continue
            confirmed=await provider.verify_succeeded(p.provider_payment_id,shop.Decimal(str(p.amount)),p.currency,p.order_id)
            if confirmed:
                try:
                    result=await shop._confirm_and_fulfill_payment(p.id,db)
                    if not result.get("ignored"):
                        changed += 1
                        retried += 1
                except Exception as exc:
                    shop.logger.warning("Non-critical operation failed: %s", exc)
        except Exception: continue
    await shop.audit(db,"payment.reconciliation",admin.email,None,{"checked":len(rows),"confirmed":changed,"retried":retried,"creation_unknown_recovered":recovered}); await db.commit(); return {"checked":len(rows),"confirmed":changed,"retried":retried,"creation_unknown_recovered":recovered}

@shop.app.post("/api/admin/payments/{payment_id}/retry")
async def retry_payment(payment_id:int,db:shop.AsyncSession=shop.Depends(shop.get_db),admin=shop.Depends(shop.require_permission("payments.retry"))):
    p=await db.get(shop.Payment,payment_id);
    if not p: raise shop.HTTPException(404,"Payment not found")
    if p.status in {"refunded", "refunded_pending_revoke"}: raise shop.HTTPException(409,"Refunded payment cannot be fulfilled")
    if p.status!="paid": raise shop.HTTPException(409,"Payment is not confirmed")
    if p.status=="paid" and p.fulfillment_status=="completed": return {"ok":True,"status":"completed"}
    p.next_retry_at=shop.datetime.utcnow(); p.fulfillment_status="pending"; await db.commit()
    try: await shop.fulfill(p.id,db)
    except Exception as exc:
        shop.logger.warning("Payment retry failed for payment %s: %s", payment_id, exc)
        return {"ok":False,"status":"failed","error":"Повтор выдачи не выполнен"}
    return {"ok":True,"status":"completed"}


__all__ = ['_reverse_referral_reward_for_refund', '_safe_revoke_for_refunded_payment', 'admin_analytics', 'admin_openapi', 'admin_recovery', 'admin_refunds', 'admin_releases', 'admin_sessions', 'admin_support_messages', 'admin_ticket_reply', 'admin_tickets', 'admin_withdrawals', 'admin_workers', 'approve_refund', 'approve_withdrawal', 'check_release', 'execute_refund', 'incident_mode', 'incident_mode_status', 'mark_refunded', 'paid_withdrawal', 'reconcile_payments', 'reconcile_referrals', 'recovery_operations', 'reject_withdrawal', 'request_refund', 'retry_operation', 'retry_payment', 'retry_refund_revoke', 'revoke_admin_session', 'revoke_all_sessions', 'secret_status', 'security_incident', 'security_incidents', 'system_health']
# Imported before main finished (``from app import recovery_api`` first)? Then main's star
# import saw a half-loaded module; hand the names over now that they exist.
shop.__dict__.update({_n: globals()[_n] for _n in __all__})
