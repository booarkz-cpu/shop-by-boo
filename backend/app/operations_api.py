"""V32 Operations / Monitoring / Fraud / Privacy: admin and customer endpoints moved out of main.py (v28.28.0).

Names that belong to main are read through ``shop.<name>`` at call time, so tests and
operators that patch ``app.main`` keep affecting this code exactly as before."""
from .db import get_db
from .security import require_permission
from fastapi import Depends
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from . import main as shop

# ---------- V32 Operations / Monitoring / Fraud / Privacy ----------
@shop.app.get("/api/me/traffic")
async def my_traffic(request:Request,db:AsyncSession=Depends(get_db)):
    user=await shop.user_from_token(request,db); sub=(await db.execute(shop.select(shop.Subscription).where(shop.Subscription.user_id==user.id,shop.Subscription.is_primary.is_(True)))).scalar_one_or_none()
    limit_bytes=int(sub.traffic_limit_gb_snapshot)*1024**3 if sub and sub.traffic_limit_gb_snapshot else None
    if not sub or not sub.remnawave_uuid: return {"available":False,"traffic_used_bytes":None,"traffic_limit_bytes":limit_bytes,"devices":None}
    try:
        data=await shop.RemnawaveClient().get_user(sub.remnawave_uuid)
        remote_limit=data.get("trafficLimitBytes")
        return {"available":True,"traffic_used_bytes":data.get("trafficUsedBytes") or data.get("usedTrafficBytes"),"traffic_limit_bytes":remote_limit if remote_limit is not None else limit_bytes,"devices":data.get("devices") or data.get("deviceCount"),"status":data.get("status"),"expires_at":data.get("expireAt") or data.get("expiresAt")}
    except Exception:
        return {"available":False,"traffic_used_bytes":None,"traffic_limit_bytes":limit_bytes,"devices":None}

@shop.app.get("/api/me/privacy/export")
async def privacy_export(request:Request,db:AsyncSession=Depends(get_db)):
    user=await shop.user_from_token(request,db)
    from .models import AccountMergeAlias
    aliases=(await db.scalars(shop.select(AccountMergeAlias).where(AccountMergeAlias.target_user_id==user.id).order_by(AccountMergeAlias.id))).all()
    sub=(await db.execute(shop.select(shop.Subscription).where(shop.Subscription.user_id==user.id,shop.Subscription.is_primary.is_(True)))).scalar_one_or_none()
    payments=(await db.execute(shop.select(shop.Payment).where(shop.Payment.user_id==user.id).order_by(shop.Payment.id))).scalars().all()
    tickets=(await db.execute(shop.select(shop.SupportTicket).where(shop.SupportTicket.user_id==user.id).order_by(shop.SupportTicket.id))).scalars().all()
    withdrawals=(await db.execute(shop.select(shop.WithdrawalRequest).where(shop.WithdrawalRequest.user_id==user.id).order_by(shop.WithdrawalRequest.id))).scalars().all()
    from .models import SupportMessage
    messages=(await db.execute(shop.select(SupportMessage).join(shop.SupportTicket,SupportMessage.ticket_id==shop.SupportTicket.id).where(shop.SupportTicket.user_id==user.id).order_by(SupportMessage.id))).scalars().all()
    subscriptions=(await db.execute(shop.select(shop.Subscription).where(shop.Subscription.user_id==user.id).order_by(shop.Subscription.id))).scalars().all()
    from .models import SurveyResponse
    survey_answers=(await db.execute(shop.select(SurveyResponse).where(SurveyResponse.user_id==user.id).order_by(SurveyResponse.id))).scalars().all()
    from .models import GiveawayEntry
    giveaway_entries=(await db.scalars(shop.select(GiveawayEntry).where(GiveawayEntry.user_id==user.id).order_by(GiveawayEntry.id))).all()
    return {"login_aliases":[{"telegram_id":x.telegram_id,"yandex_id":x.yandex_id,"vk_id":x.vk_id,"email":x.email,"referral_code":x.referral_code,"merged_at":x.merged_at} for x in aliases],"giveaway_entries":[{"giveaway_id":x.giveaway_id,"outcome":x.outcome,"reward_amount":str(x.reward_amount),"created_at":x.created_at} for x in giveaway_entries],"survey_answers":[{"survey_id":x.survey_id,"answers":x.answers,"reward_amount":str(x.reward_amount),"currency":x.currency,"created_at":x.created_at} for x in survey_answers],"subscriptions":[{"id":x.id,"name":x.name,"plan_id":x.plan_id,"is_primary":x.is_primary,"status":x.lifecycle_status,"expires_at":x.expires_at} for x in subscriptions],"exported_at":shop.datetime.utcnow(),"user":{"id":user.id,"telegram_id":user.telegram_id,"yandex_id":user.yandex_id,"username":user.username,"referral_code":user.referral_code,"created_at":user.created_at},"subscription":None if not sub else {"id":sub.id,"name":sub.name,"plan_id":sub.plan_id,"remnawave_uuid":sub.remnawave_uuid,"expires_at":sub.expires_at},"payments":[{"id":x.id,"amount":str(x.amount),"currency":x.currency,"provider":x.provider,"status":x.status,"created_at":x.created_at} for x in payments],"tickets":[{"id":x.id,"subject":x.subject,"message":x.message,"admin_reply":x.admin_reply,"status":x.status,"created_at":x.created_at} for x in tickets],"support_messages":[{"ticket_id":x.ticket_id,"role":x.role,"body":x.body,"created_at":x.created_at} for x in messages],"withdrawals":[{"id":x.id,"amount":str(x.amount),"status":x.status,"created_at":x.created_at} for x in withdrawals]}

@shop.app.delete("/api/me/privacy/account")
async def privacy_delete(request:Request,db:AsyncSession=Depends(get_db)):
    user=await shop.user_from_token(request,db)
    user_lock, user_token = await shop._acquire_user_fulfillment_lock(user.id)
    try:
        user=(await db.execute(shop.select(shop.User).where(shop.User.id==user.id).execution_options(populate_existing=True).with_for_update())).scalar_one()
        if user.deleted_at is not None:
            raise shop.HTTPException(409,"Account is already anonymized")
        from .models import SupportImportLink
        pending_import=await db.scalar(shop.select(SupportImportLink.source_key).join(shop.SupportTicket,shop.SupportTicket.id==SupportImportLink.ticket_id).where(shop.SupportTicket.user_id==user.id,SupportImportLink.completed.is_(False)).limit(1))
        if pending_import:raise shop.HTTPException(409,"Сначала завершите перенос истории поддержки")
        unresolved_gift=await db.scalar(shop.select(shop.GiftRedemption.id).where(shop.GiftRedemption.user_id==user.id,shop.GiftRedemption.status!="completed").limit(1))
        unresolved_payment=await db.scalar(shop.select(shop.Payment.id).where(shop.Payment.user_id==user.id,shop.Payment.status.in_(("creating","pending","creation_unknown","paid","fulfilled","refunded_pending_revoke")),shop.Payment.fulfillment_status!="completed").limit(1))
        if unresolved_gift or unresolved_payment:raise shop.HTTPException(409,"Сначала завершите обработку покупок и подарков")
        from .models import Reseller, PartnerWithdrawal, CustomerPasskey, CustomerPasskeyChallenge, AccountMergeAlias
        partner=await db.scalar(shop.select(Reseller).where(Reseller.owner_user_id==user.id).execution_options(populate_existing=True).with_for_update())
        if partner:
            pending_payout=await db.scalar(shop.select(PartnerWithdrawal.id).where(PartnerWithdrawal.reseller_id==partner.id,PartnerWithdrawal.status.in_(("pending","approved"))).limit(1))
            pending_partner_purchase=await db.scalar(shop.select(shop.Payment.id).where(shop.Payment.reseller_id==partner.id,shop.Payment.status.in_(("creating","pending","creation_unknown","paid","fulfilled","refunded_pending_revoke")),shop.Payment.fulfillment_status!="completed").limit(1))
            if partner.balance != 0 or pending_payout or pending_partner_purchase:
                raise shop.HTTPException(409,"Сначала завершите партнёрские расчёты и выплаты")
        subscriptions=(await db.execute(shop.select(shop.Subscription).where(shop.Subscription.user_id==user.id).execution_options(populate_existing=True).with_for_update())).scalars().all()
        if any(x.lifecycle_status in {"active","cancel_scheduled","grace","revoke_pending"} and (x.expires_at is None or x.expires_at>shop.datetime.utcnow()) for x in subscriptions):
            raise shop.HTTPException(409,"Active subscription must expire before account deletion")
        for active in subscriptions:
            if active.remnawave_uuid:
                try:
                    await shop.RemnawaveClient().disable_user(active.remnawave_uuid)
                except Exception as exc:
                    raise shop.HTTPException(503,"Не удалось отключить удалённую VPN-подписку; удаление аккаунта остановлено") from exc
            active.expires_at=shop.datetime.utcnow();active.lifecycle_status="cancelled";active.auto_renew_enabled=False;active.name="Подписка"
            active.subscription_url=None;active.remnawave_uuid=None
        from .models import SupportAttachment
        from sqlalchemy import delete
        await db.execute(delete(SupportAttachment).where(SupportAttachment.ticket_id.in_(shop.select(shop.SupportTicket.id).where(shop.SupportTicket.user_id==user.id))))
        await db.execute(__import__('sqlalchemy').update(shop.SupportTicket).where(shop.SupportTicket.user_id==user.id).values(updated_at=shop.datetime.utcnow()))
        if user.telegram_id: user.telegram_id=None
        user.yandex_id=None
        user.vk_id=None;user.email=None;user.email_password_hash=None;user.email_verified_at=None
        from .account_actions import revoke_access
        from .models import AccountAction
        await revoke_access(db,user)
        alias_source_ids=shop.select(AccountMergeAlias.source_user_id).where(AccountMergeAlias.target_user_id==user.id)
        await db.execute(delete(AccountAction).where(shop.or_(
            AccountAction.user_id==user.id,
            AccountAction.user_id.in_(alias_source_ids),
        )))
        await db.execute(delete(CustomerPasskey).where(CustomerPasskey.user_id==user.id))
        await db.execute(delete(CustomerPasskeyChallenge).where(CustomerPasskeyChallenge.user_id==user.id))
        await db.execute(delete(AccountMergeAlias).where(AccountMergeAlias.target_user_id==user.id))
        from .models import TorrentDetection
        await db.execute(delete(TorrentDetection).where(TorrentDetection.user_id==user.id))
        user.passkey_user_handle=None
        if partner:
            partner.enabled=False
            partner.api_key_hash=shop.hashlib.sha256(shop.secrets.token_bytes(32)).hexdigest()
        from .surveys import anonymize as anonymize_surveys
        await anonymize_surveys(db,user.id)
        from .giveaways import anonymize as anonymize_giveaways
        await anonymize_giveaways(db,user.id)
        user.username=f"deleted_{user.id}"
        user.referral_code=f"deleted_{user.id}"
        user.auto_renew_enabled=False
        user.deleted_at=shop.datetime.utcnow()
        method=(await db.execute(shop.select(shop.AutoRenewMethod).where(shop.AutoRenewMethod.user_id==user.id).with_for_update())).scalar_one_or_none()
        if method:
            method.enabled=False
            method.status="deleted"
            method.external_token_encrypted="DELETED"
        await db.execute(shop.sql_text("UPDATE user_devices SET status='revoked', revoked_at=COALESCE(revoked_at, NOW()) WHERE user_id=:uid"), {"uid":user.id})
        await shop.audit(db,"privacy.account.anonymized",f"user:{user.id}",str(user.id))
        await db.commit()
        return {"ok":True,"anonymized":True}
    finally:
        await shop._release_payment_side_effect_lock(user_lock, user_token)

@shop.app.get("/api/admin/financial-ledger")
async def admin_financial_ledger(db:AsyncSession=Depends(get_db), admin=Depends(require_permission("payments.read"))):
    rows=(await db.execute(shop.select(shop.FinancialLedger).order_by(shop.FinancialLedger.id.desc()).limit(500))).scalars().all()
    return [{"id":x.id,"operation_key":x.operation_key,"user_id":x.user_id,"payment_id":x.payment_id,"kind":x.kind,"direction":x.direction,"amount":str(x.amount),"currency":x.currency,"created_at":x.created_at,"metadata":shop.json.loads(x.metadata_json or "{}")} for x in rows]

@shop.app.get("/api/admin/monitoring")
async def admin_monitoring(db:AsyncSession=Depends(get_db),admin=Depends(require_permission("read"))):
    now=shop.datetime.utcnow(); disk=shop.shutil.disk_usage("/")
    workers=(await db.execute(shop.select(shop.WorkerState).order_by(shop.WorkerState.last_seen_at.desc()))).scalars().all()
    jobs=(await db.execute(shop.select(shop.Job).order_by(shop.Job.id.desc()).limit(200))).scalars().all()
    return {"version":shop.APP_VERSION,"disk_percent":round(disk.used/disk.total*100,1),"workers":[{"id":w.worker_id,"role":w.role,"status":"stale" if now-w.last_seen_at>shop.timedelta(seconds=90) else w.status,"last_seen_at":w.last_seen_at} for w in workers],"jobs":{"queued":sum(j.status=="queued" for j in jobs),"processing":sum(j.status=="processing" for j in jobs),"failed":sum(j.status=="failed" for j in jobs)},"requests":dict(shop._METRICS)}

@shop.app.get("/api/admin/jobs")
async def admin_jobs(db:AsyncSession=Depends(get_db),admin=Depends(require_permission("read"))):
    rows=(await db.execute(shop.select(shop.Job).order_by(shop.Job.id.desc()).limit(500))).scalars().all()
    return [{"id":x.id,"job_key":x.job_key,"kind":x.kind,"status":x.status,"attempts":x.attempts,"max_attempts":x.max_attempts,"next_retry_at":x.next_retry_at,"worker_id":x.worker_id,"error":"unavailable" if x.error else None,"created_at":x.created_at,"completed_at":x.completed_at} for x in rows]

@shop.app.post("/api/admin/jobs/{job_id}/retry")
async def retry_job(job_id:int,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("payments.retry"))):
    row=await db.get(shop.Job,job_id)
    if not row: raise shop.HTTPException(404,"Job not found")
    row.status="queued"; row.next_retry_at=shop.datetime.utcnow(); row.error=None; row.locked_at=None; await shop.audit(db,"job.requeued",admin.email,str(job_id)); await db.commit(); return {"ok":True}

@shop.app.get("/api/admin/fraud")
async def admin_fraud(db:AsyncSession=Depends(get_db),admin=Depends(require_permission("security.manage"))):
    rows=(await db.execute(shop.select(shop.FraudSignal).order_by(shop.FraudSignal.id.desc()).limit(500))).scalars().all()
    return [{"id":x.id,"user_id":x.user_id,"ip":x.ip,"fingerprint":x.fingerprint,"kind":x.kind,"score":x.score,"status":x.status,"details":x.details,"created_at":x.created_at,"resolved_at":x.resolved_at} for x in rows]

@shop.app.post("/api/admin/fraud/{signal_id}")
async def fraud_decision(signal_id:int,payload:shop.FraudDecisionIn,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("security.manage"))):
    row=await db.get(shop.FraudSignal,signal_id)
    if not row: raise shop.HTTPException(404,"Fraud signal not found")
    row.status=payload.status; row.resolved_at=shop.datetime.utcnow() if payload.status!="open" else None
    await shop.audit(db,"fraud.signal.updated",admin.email,str(signal_id),payload.note); await db.commit(); return {"ok":True,"status":row.status}

@shop.app.post("/api/admin/fraud/scan")
async def fraud_scan(db:AsyncSession=Depends(get_db),admin=Depends(require_permission("security.manage"))):
    since=shop.datetime.utcnow()-shop.timedelta(hours=24); created=0
    # Velocity checks: repeated payments from the same user and repeated failed fulfillment.
    rows=(await db.execute(shop.select(shop.Payment.user_id,shop.func.count(shop.Payment.id)).where(shop.Payment.created_at>=since).group_by(shop.Payment.user_id).having(shop.func.count(shop.Payment.id)>=10))).all()
    # A repeated scan must not pile up duplicates: one open signal per user and kind is enough.
    open_keys={(u,k) for u,k in (await db.execute(shop.select(shop.FraudSignal.user_id,shop.FraudSignal.kind).where(shop.FraudSignal.status=="open",shop.FraudSignal.kind.in_(("payment_velocity","fulfillment_failure_velocity"))))).all()}
    for uid,count in rows:
        if (uid,"payment_velocity") in open_keys: continue
        db.add(shop.FraudSignal(user_id=uid,kind="payment_velocity",score=min(100,int(count)*5),details=f"{count} payments in 24h")); created+=1
    failed=(await db.execute(shop.select(shop.Payment.user_id,shop.func.count(shop.Payment.id)).where(shop.Payment.created_at>=since,shop.Payment.fulfillment_status=="failed").group_by(shop.Payment.user_id).having(shop.func.count(shop.Payment.id)>=3))).all()
    for uid,count in failed:
        if (uid,"fulfillment_failure_velocity") in open_keys: continue
        db.add(shop.FraudSignal(user_id=uid,kind="fulfillment_failure_velocity",score=min(100,int(count)*15),details=f"{count} failed fulfillments in 24h")); created+=1
    await shop.audit(db,"fraud.scan",admin.email,None,{"created":created}); await db.commit(); return {"created":created}

@shop.app.get("/api/admin/payouts")
async def admin_payouts(db:AsyncSession=Depends(get_db),admin=Depends(require_permission("referrals.withdrawals.read"))):
    rows=(await db.execute(shop.select(shop.PayoutTransaction).order_by(shop.PayoutTransaction.id.desc()).limit(200))).scalars().all()
    return [{"id":x.id,"withdrawal_id":x.withdrawal_id,"provider":x.provider,"external_id":x.external_id,"amount":str(x.amount),"status":x.status,"attempts":x.attempts,"last_error":"unavailable" if x.last_error else None,"created_at":x.created_at,"paid_at":x.paid_at} for x in rows]

@shop.app.post("/api/admin/ops/withdrawals/{withdrawal_id}/approve")
async def admin_withdrawal_approve(withdrawal_id:int,payload:shop.WithdrawalActionIn,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("referrals.withdrawals.approve"))):
    await db.execute(shop.sql_text("SELECT id FROM withdrawal_requests WHERE id=:id FOR UPDATE"),{"id":withdrawal_id})
    w=await db.get(shop.WithdrawalRequest,withdrawal_id)
    if not w: raise shop.HTTPException(404,"Withdrawal not found")
    if w.status!="requested": raise shop.HTTPException(409,"Withdrawal is not requested")
    existing_payout=(await db.execute(shop.select(shop.PayoutTransaction).where(shop.PayoutTransaction.withdrawal_id==w.id).with_for_update())).scalar_one_or_none()
    if existing_payout: raise shop.HTTPException(409,"Payout transaction already exists")
    w.status="approved"; w.updated_at=shop.datetime.utcnow(); db.add(shop.PayoutTransaction(withdrawal_id=w.id,amount=w.amount,provider="manual",status="processing")); await shop.audit(db,"referral.withdrawal.approved",admin.email,str(w.id),payload.note); await db.commit(); return {"ok":True,"status":w.status}

@shop.app.post("/api/admin/ops/withdrawals/{withdrawal_id}/paid")
async def admin_withdrawal_paid(withdrawal_id:int,payload:shop.WithdrawalActionIn,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("referrals.withdrawals.pay"))):
    await db.execute(shop.sql_text("SELECT id FROM withdrawal_requests WHERE id=:id FOR UPDATE"),{"id":withdrawal_id})
    w=await db.get(shop.WithdrawalRequest,withdrawal_id); p=(await db.execute(shop.select(shop.PayoutTransaction).where(shop.PayoutTransaction.withdrawal_id==withdrawal_id).with_for_update())).scalar_one_or_none()
    if not w or not p: raise shop.HTTPException(404,"Withdrawal/payout not found")
    if w.status not in {"approved","processing"}: raise shop.HTTPException(409,"Withdrawal is not payable")
    w.status="paid"; w.updated_at=shop.datetime.utcnow(); p.status="paid"; p.paid_at=shop.datetime.utcnow(); p.updated_at=shop.datetime.utcnow(); await shop.audit(db,"referral.withdrawal.paid",admin.email,str(w.id),payload.note); await db.commit(); return {"ok":True,"status":"paid"}

@shop.app.post("/api/admin/refunds/{refund_id}/reconcile")
async def reconcile_refund(refund_id:int,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("payments.reconcile"))):
    r=await db.get(shop.RefundRequest,refund_id)
    if not r: raise shop.HTTPException(404,"Refund not found")
    if not r.provider_refund_id: raise shop.HTTPException(409,"Provider refund ID is missing")
    p=await db.get(shop.Payment,r.payment_id)
    if not p: raise shop.HTTPException(404,"Payment not found")
    from .gateways import refunders
    providers={"yookassa":shop.YooKassaProvider(),"platega":shop.PlategaProvider(),"rollypay":shop.RollyPayProvider(),"stripe":shop.StripePlatform(),"paypal":shop.PayPalPlatform(),"telegram_stars":shop.TelegramStarsProvider(),**refunders()}
    provider=providers.get(p.provider)
    if not provider or not hasattr(provider,"get_refund_status"): raise shop.HTTPException(409,"Refund status adapter is unavailable")
    try:
        dashboard_prefix=f"{p.provider}-refund-"
        if p.provider in {"platega","rollypay"} and str(r.provider_refund_id).startswith(dashboard_prefix):
            # Refund made in the provider's dashboard: its state is read from the payment itself.
            status=str((await provider.read_refund(str(r.provider_refund_id)[len(dashboard_prefix):])).get("status") or "").lower()
        else:
            status=str(await provider.get_refund_status(r.provider_refund_id)).lower()
    except Exception as exc:
        await shop.audit(db,"payment.refund.reconcile_failed",admin.email,str(r.id),{"error":str(exc)[:500]}); await db.commit()
        raise shop.HTTPException(503,"Provider refund status unavailable")
    if status in {"succeeded","paid","completed","refunded"}:
        user_lock, user_token = await shop._acquire_user_fulfillment_lock(p.user_id,ttl=300)
        payment_lock = payment_token = None
        try:
            payment_lock, payment_token = await shop._acquire_payment_side_effect_lock(p.id)
            p=(await db.execute(shop.select(shop.Payment).where(shop.Payment.id==p.id).execution_options(populate_existing=True).with_for_update())).scalar_one()
            r=(await db.execute(shop.select(shop.RefundRequest).where(shop.RefundRequest.id==r.id).execution_options(populate_existing=True).with_for_update())).scalar_one()
            if r.status=="refunded":
                return {"ok":True,"status":"refunded","already_reconciled":True}
            r.status="refunded"; r.updated_at=shop.datetime.utcnow(); p.status="refunded"; p.fulfillment_terminal=True
            await shop.record_financial_event(db,operation_key=f"payment:{p.id}:refund:{r.id}",user_id=p.user_id,payment_id=p.id,kind="refund",direction="debit",amount=shop.Decimal(str(p.amount)),currency=p.currency,metadata={"provider":p.provider,"refund_id":r.id,"provider_refund_id":r.provider_refund_id})
            try:
                revoke_result=await shop._safe_revoke_for_refunded_payment(db,p,admin.email,"subscription.revoked.refund.reconciled")
            except Exception as exc:
                r.status="refunded_pending_revoke"; r.reason=(r.reason or "")+"\nRevoke pending: "+str(exc)[:500]; revoke_result={"revoked":False,"reason":"revoke_failed"}
            reversal_result=await shop._reverse_referral_reward_for_refund(db,p,admin.email) if r.status == "refunded" else {"reversed":False}
            await shop.audit(db,"payment.refund.reconciled",admin.email,str(r.id),{"provider_status":status,**revoke_result,**reversal_result}); await db.commit()
            return {"ok":True,"status":r.status,"verified":True,"provider_status":status,**revoke_result}
        finally:
            if payment_lock and payment_token:
                await shop._release_payment_side_effect_lock(payment_lock, payment_token)
            await shop._release_payment_side_effect_lock(user_lock, user_token)
    if status in {"canceled","cancelled","failed","rejected"}:
        r.status="failed"; r.reason=(r.reason or "")+f"\nProvider refund status: {status}"; r.updated_at=shop.datetime.utcnow(); await db.commit()
        return {"ok":True,"status":"failed","verified":True,"provider_status":status}
    r.status="processing"; r.updated_at=shop.datetime.utcnow(); await db.commit()
    return {"ok":True,"status":"processing","verified":False,"provider_status":status}


__all__ = ['admin_financial_ledger', 'admin_fraud', 'admin_jobs', 'admin_monitoring', 'admin_payouts', 'admin_withdrawal_approve', 'admin_withdrawal_paid', 'fraud_decision', 'fraud_scan', 'my_traffic', 'privacy_delete', 'privacy_export', 'reconcile_refund', 'retry_job']
# Imported before main finished (``from app import operations_api`` first)? Then main's star
# import saw a half-loaded module; hand the names over now that they exist.
shop.__dict__.update({_n: globals()[_n] for _n in __all__})
