"""Enterprise suite V44 / V41 operations: admin and customer endpoints moved out of main.py (v28.28.0).

Names that belong to main are read through ``shop.<name>`` at call time, so tests and
operators that patch ``app.main`` keep affecting this code exactly as before."""
from .db import get_db
from .security import require_permission
from fastapi import Depends
from pydantic import BaseModel
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from . import main as shop

# ---------- Enterprise suite V44 ----------
@shop.app.get("/api/admin/enterprise/monitoring")
async def enterprise_monitoring(db:AsyncSession=Depends(get_db),admin=Depends(require_permission("read"))):
    rows=(await db.execute(shop.select(shop.MonitoringCheck).order_by(shop.MonitoringCheck.id))).scalars().all()
    return [{"id":x.id,"name":x.name,"url":x.url,"method":x.method,"interval_seconds":x.interval_seconds,"timeout_seconds":x.timeout_seconds,"enabled":x.enabled,"last_status":x.last_status,"last_latency_ms":x.last_latency_ms,"last_error":"unavailable" if x.last_error else None,"last_checked_at":x.last_checked_at,"failure_streak":x.failure_streak} for x in rows]

@shop.app.post("/api/admin/enterprise/monitoring")
async def enterprise_monitoring_create(payload:shop.MonitoringCheckIn,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("ops.diagnostics"))):
    shop.validate_public_url(payload.url)
    x=shop.MonitoringCheck(**payload.model_dump()); db.add(x); await db.commit(); await shop.audit(db,"monitoring.check.created",admin.email,str(x.id)); await db.commit(); return {"id":x.id}

@shop.app.delete("/api/admin/enterprise/monitoring/{check_id}")
async def enterprise_monitoring_delete(check_id:int,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("ops.diagnostics"))):
    x=await db.get(shop.MonitoringCheck,check_id)
    if not x: raise shop.HTTPException(404,"Проверка не найдена")
    await db.delete(x); await shop.audit(db,"monitoring.check.deleted",admin.email,str(check_id)); await db.commit(); return {"ok":True}

@shop.app.get("/api/admin/enterprise/campaigns")
async def enterprise_campaigns(db:AsyncSession=Depends(get_db),admin=Depends(require_permission("marketing.read"))):
    rows=(await db.execute(shop.select(shop.Campaign).order_by(shop.Campaign.id.desc()))).scalars().all(); return [{"id":x.id,"name":x.name,"kind":x.kind,"status":x.status,"audience":x.audience,"content":x.content,"starts_at":x.starts_at,"ends_at":x.ends_at,"sent_count":x.sent_count,"failed_count":x.failed_count} for x in rows]

@shop.app.post("/api/admin/enterprise/campaigns")
async def enterprise_campaign_create(payload:shop.CampaignIn,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("manage_marketing"))):
    from .automation import validate_campaign
    validate_campaign(payload.model_dump())
    x=shop.Campaign(**payload.model_dump()); db.add(x); await db.commit(); await shop.audit(db,"campaign.created",admin.email,str(x.id)); await db.commit(); return {"id":x.id,"status":x.status}

@shop.app.put("/api/admin/enterprise/campaigns/{campaign_id}")
async def enterprise_campaign_update(campaign_id:int,payload:shop.CampaignIn,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("manage_marketing"))):
    x=await db.get(shop.Campaign,campaign_id)
    if not x: raise shop.HTTPException(404,"Кампания не найдена")
    if x.status=="running": raise shop.HTTPException(409,"Кампания уже отправляется")
    from .automation import validate_campaign
    validate_campaign(payload.model_dump())
    for k,v in payload.model_dump().items(): setattr(x,k,v)
    x.updated_at=shop.datetime.utcnow(); await db.commit(); return {"ok":True}

@shop.app.get("/api/admin/enterprise/rules")
async def enterprise_rules(db:AsyncSession=Depends(get_db),admin=Depends(require_permission("read"))):
    rows=(await db.execute(shop.select(shop.AutomationRule).order_by(shop.AutomationRule.priority,shop.AutomationRule.id))).scalars().all(); return [{"id":x.id,"name":x.name,"event":x.event,"conditions":x.conditions,"actions":x.actions,"enabled":x.enabled,"priority":x.priority,"run_count":x.run_count,"last_run_at":x.last_run_at} for x in rows]

@shop.app.post("/api/admin/enterprise/rules")
async def enterprise_rule_create(payload:shop.RuleIn,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("feature_flags.manage"))):
    from .automation import validate_rule
    payload.conditions,payload.actions=validate_rule(payload.event,payload.conditions,payload.actions)
    if payload.actions.get("wallet_bonus") and admin.role!="admin": raise shop.HTTPException(403,"Бонус на баланс в правилах настраивает администратор")
    x=shop.AutomationRule(**payload.model_dump()); db.add(x); await db.commit(); await shop.audit(db,"automation.rule.created",admin.email,str(x.id)); await db.commit(); return {"id":x.id}

@shop.app.put("/api/admin/enterprise/rules/{rule_id}")
async def enterprise_rule_update(rule_id:int,payload:shop.RuleIn,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("feature_flags.manage"))):
    x=await db.get(shop.AutomationRule,rule_id)
    if not x: raise shop.HTTPException(404,"Правило не найдено")
    from .automation import validate_rule
    payload.conditions,payload.actions=validate_rule(payload.event,payload.conditions,payload.actions)
    if (payload.actions.get("wallet_bonus") or (x.actions or {}).get("wallet_bonus")) and admin.role!="admin": raise shop.HTTPException(403,"Бонус на баланс в правилах настраивает администратор")
    for k,v in payload.model_dump().items(): setattr(x,k,v)
    x.updated_at=shop.datetime.utcnow(); await shop.audit(db,"automation.rule.updated",admin.email,str(rule_id),{"enabled":x.enabled}); await db.commit(); return {"ok":True}

@shop.app.get("/api/admin/enterprise/summary")
async def enterprise_summary(db:AsyncSession=Depends(get_db),admin=Depends(require_permission("read"))):
    now=shop.datetime.utcnow(); active=(await db.execute(shop.select(shop.func.count()).select_from(shop.Subscription).where(shop.Subscription.expires_at.is_not(None),shop.Subscription.expires_at>now))).scalar() or 0
    return {"monitoring":await db.scalar(shop.select(shop.func.count()).select_from(shop.MonitoringCheck).where(shop.MonitoringCheck.enabled.is_(True))),"campaigns":await db.scalar(shop.select(shop.func.count()).select_from(shop.Campaign).where(shop.Campaign.status.in_(["scheduled","running"]))),"rules":await db.scalar(shop.select(shop.func.count()).select_from(shop.AutomationRule).where(shop.AutomationRule.enabled.is_(True))),"devices":await db.scalar(shop.select(shop.func.count()).select_from(shop.UserDevice).where(shop.UserDevice.status=="active")),"active_subscriptions":active,"features":["24/7 мониторинг","маршрутизация платежей","антифрод","личный кабинет","мультиустройства","автопродление","конструктор бота","конструктор Mini App","тарифы 2.0","trial","campaign manager","аналитика","node manager","rules engine","support center","disaster recovery"]}

# ---------- V41 Enterprise Operations ----------
V41_FEATURE_DEFAULTS = {
    "passkeys": (False, "Вход администратора по Passkey/WebAuthn"),
    "payment_failover": (True, "Автоматический fallback платёжного провайдера"),
    "incident_center": (True, "Центр инцидентов"),
    "diagnostics_center": (True, "Центр диагностики"),
    "backup_test_restore": (True, "Проверка backup и безопасный test-restore"),
    "advanced_analytics": (True, "Расширенная бизнес-аналитика"),
    "advanced_promos": (True, "Расширенные промокампании"),
    "referral_v2": (True, "Реферальная система второго уровня"),
    "payments": (True, "Создание реальных платежей"),
}

async def _ensure_v41_defaults(db):
    for key,(enabled,desc) in shop.V41_FEATURE_DEFAULTS.items():
        row=await shop._feature_flag(db,key)
        if not row: db.add(shop.FeatureFlag(key=key,enabled=enabled,description=desc))
    for i,p in enumerate(("yookassa","platega","rollypay"),1):
        row=(await db.execute(shop.select(shop.PaymentProviderHealth).where(shop.PaymentProviderHealth.provider==p))).scalar_one_or_none()
        if not row: db.add(shop.PaymentProviderHealth(provider=p,priority=i*10,enabled=True))
    await db.commit()

@shop.app.get("/api/admin/v41/features")
async def v41_features(db:AsyncSession=Depends(get_db),admin=Depends(require_permission("read"))):
    await shop._ensure_v41_defaults(db)
    rows=(await db.execute(shop.select(shop.FeatureFlag).order_by(shop.FeatureFlag.key))).scalars().all()
    return [{"key":x.key,"enabled":x.enabled,"description":x.description,"updated_at":str(x.updated_at)} for x in rows]

class FeatureFlagIn(BaseModel):
    enabled: bool

@shop.app.put("/api/admin/v41/features/{key}")
async def v41_feature_update(key:str,payload:FeatureFlagIn,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("feature_flags.manage"))):
    if key not in shop.V41_FEATURE_DEFAULTS: raise shop.HTTPException(404,"Функция не найдена")
    row=await shop._feature_flag(db,key)
    if not row: row=shop.FeatureFlag(key=key,description=shop.V41_FEATURE_DEFAULTS[key][1]); db.add(row)
    row.enabled=payload.enabled; row.updated_at=shop.datetime.utcnow()
    await shop.audit(db,"feature_flag.updated",admin.email,key,{"enabled":payload.enabled}); await db.commit()
    return {"key":key,"enabled":payload.enabled}

@shop.app.get("/api/admin/v41/analytics")
async def v41_analytics(db:AsyncSession=Depends(get_db),admin=Depends(require_permission("analytics.read"))):
    now=shop.datetime.utcnow(); since=now-shop.timedelta(days=30)
    users_total=int((await db.execute(shop.select(shop.func.count()).select_from(shop.User).where(shop.User.deleted_at.is_(None)))).scalar_one())
    users_new=int((await db.execute(shop.select(shop.func.count()).select_from(shop.User).where(shop.User.created_at>=since,shop.User.deleted_at.is_(None)))).scalar_one())
    payments_total=int((await db.execute(shop.select(shop.func.count()).select_from(shop.Payment))).scalar_one())
    paid=int((await db.execute(shop.select(shop.func.count()).select_from(shop.Payment).where(shop.Payment.status.in_(["paid","succeeded"])))).scalar_one())
    revenue=(await db.execute(shop.select(shop.func.coalesce(shop.func.sum(shop.Payment.amount),0)).where(shop.Payment.status.in_(["paid","succeeded"])))).scalar_one()
    revenue30=(await db.execute(shop.select(shop.func.coalesce(shop.func.sum(shop.Payment.amount),0)).where(shop.Payment.status.in_(["paid","succeeded"]),shop.Payment.paid_at>=since))).scalar_one()
    refunds=int((await db.execute(shop.select(shop.func.count()).select_from(shop.RefundRequest).where(shop.RefundRequest.status=="refunded"))).scalar_one())
    avg=(shop.Decimal(str(revenue))/shop.Decimal(paid)).quantize(shop.Decimal("0.01")) if paid else shop.Decimal("0")
    return {"users":{"total":users_total,"new_30d":users_new},"payments":{"total":payments_total,"paid":paid,"conversion_percent":round(paid/payments_total*100,2) if payments_total else 0},"revenue":{"all_time":float(revenue),"last_30d":float(revenue30),"average_paid_check":float(avg),"currency":shop.settings.default_currency},"refunds":refunds}

@shop.app.get("/api/admin/v41/crm/users")
async def v41_crm_users(q:str="",page:int=1,page_size:int=50,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("users.read"))):
    from .models import AccountMergeAlias
    page=max(1,page); page_size=min(100,max(1,page_size)); stmt=shop.select(shop.User).where(shop.User.deleted_at.is_(None)).order_by(shop.User.id.desc())
    q=q.strip()
    if q:
        if q.isdigit():
            alias_ids=shop.select(AccountMergeAlias.target_user_id).where(AccountMergeAlias.telegram_id==int(q))
            stmt=stmt.where(shop.or_(shop.User.id==int(q),shop.User.telegram_id==int(q),shop.User.id.in_(alias_ids)))
        else:
            alias_ids=shop.select(AccountMergeAlias.target_user_id).where(shop.or_(AccountMergeAlias.email.ilike(f"%{q}%"),AccountMergeAlias.referral_code.ilike(f"%{q}%")))
            stmt=stmt.where(shop.or_(shop.User.username.ilike(f"%{q}%"),shop.User.email.ilike(f"%{q}%"),shop.User.referral_code.ilike(f"%{q}%"),shop.User.id.in_(alias_ids)))
    rows=(await db.execute(stmt.offset((page-1)*page_size).limit(page_size))).scalars().all()
    return [{"id":u.id,"telegram_id":u.telegram_id,"username":u.username,"email":u.email,"referral_code":u.referral_code,"auto_renew":u.auto_renew_enabled,"created_at":str(u.created_at)} for u in rows]

@shop.app.get("/api/admin/v41/providers")
async def v41_providers(db:AsyncSession=Depends(get_db),admin=Depends(require_permission("ops.providers"))):
    await shop._ensure_v41_defaults(db)
    rows=(await db.execute(shop.select(shop.PaymentProviderHealth).order_by(shop.PaymentProviderHealth.priority,shop.PaymentProviderHealth.provider))).scalars().all()
    from .payments_api import provider_configured
    configured=provider_configured(); now=shop.datetime.utcnow()
    return [{"provider":x.provider,"enabled":x.enabled,"priority":x.priority,"configured":configured.get(x.provider,False),
             "cooling":bool(x.circuit_open_until and x.circuit_open_until>now),
             "success_count":x.success_count,"failure_count":x.failure_count,"last_latency_ms":x.last_latency_ms,"last_error":"unavailable" if x.last_error else None,"circuit_open_until":str(x.circuit_open_until) if x.circuit_open_until else None} for x in rows if x.provider in shop.PAYMENT_AGENTS]

class ProviderHealthIn(BaseModel):
    enabled: bool
    priority: int = Field(ge=1,le=1000)

@shop.app.put("/api/admin/v41/providers/{provider}")
async def v41_provider_update(provider:str,payload:ProviderHealthIn,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("ops.providers"))):
    if provider not in shop.PAYMENT_AGENTS: raise shop.HTTPException(404,"Провайдер не найден")
    row=(await db.execute(shop.select(shop.PaymentProviderHealth).where(shop.PaymentProviderHealth.provider==provider))).scalar_one_or_none()
    if not row: row=shop.PaymentProviderHealth(provider=provider); db.add(row)
    row.enabled=payload.enabled; row.priority=payload.priority; row.updated_at=shop.datetime.utcnow()
    await shop.audit(db,"payment_provider.updated",admin.email,provider,payload.model_dump()); await db.commit(); return {"ok":True}

@shop.app.post("/api/admin/v41/providers/{provider}/reset")
async def v41_provider_reset(provider:str,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("ops.providers"))):
    """«Вернуть в работу»: the operator ends the cooldown after fixing the gateway; counters start again."""
    if provider not in shop.PAYMENT_AGENTS: raise shop.HTTPException(404,"Провайдер не найден")
    row=(await db.execute(shop.select(shop.PaymentProviderHealth).where(shop.PaymentProviderHealth.provider==provider).with_for_update())).scalar_one_or_none()
    if not row: raise shop.HTTPException(404,"Провайдер не найден")
    row.circuit_open_until=None; row.failure_count=0; row.last_error=None; row.updated_at=shop.datetime.utcnow()
    await shop.audit(db,"payment_provider.reset",admin.email,provider,None); await db.commit(); return {"ok":True}

@shop.app.get("/api/admin/v41/diagnostics")
async def v41_diagnostics(db:AsyncSession=Depends(get_db),admin=Depends(require_permission("ops.diagnostics"))):
    checks=[]
    start=shop.asyncio.get_running_loop().time()
    try: await db.execute(shop.sql_text("SELECT 1")); checks.append({"name":"PostgreSQL","status":"ok","latency_ms":round((shop.asyncio.get_running_loop().time()-start)*1000)})
    except Exception as exc:
        shop.logger.warning("Diagnostics PostgreSQL check failed: %s", exc)
        checks.append({"name":"PostgreSQL","status":"error","error":"unavailable"})
    start=shop.asyncio.get_running_loop().time()
    if shop.redis_client:
        try: await shop.redis_client.ping(); checks.append({"name":"Redis","status":"ok","latency_ms":round((shop.asyncio.get_running_loop().time()-start)*1000)})
        except Exception as exc:
            shop.logger.warning("Diagnostics Redis check failed: %s", exc)
            checks.append({"name":"Redis","status":"error","error":"unavailable"})
    else: checks.append({"name":"Redis","status":"error","error":"Не подключён"})
    try:
        rw=shop.RemnawaveClient(); await rw.list_nodes(start=0,size=1); checks.append({"name":"Remnawave","status":"ok"})
    except Exception as exc:
        shop.logger.warning("Diagnostics Remnawave check failed: %s", exc)
        checks.append({"name":"Remnawave","status":"error","error":"unavailable"})
    return {"status":"ok" if all(x["status"]=="ok" for x in checks) else "degraded","checks":checks,"checked_at":shop.datetime.utcnow().isoformat()}

class IncidentCreateIn(BaseModel):
    severity:str=Field(pattern="^(low|medium|high|critical)$")
    category:str=Field(min_length=1,max_length=64)
    title:str=Field(min_length=1,max_length=255)
    details:str=Field(default="",max_length=10000)

@shop.app.get("/api/admin/v41/incidents")
async def v41_incidents(db:AsyncSession=Depends(get_db),admin=Depends(require_permission("ops.incidents"))):
    rows=(await db.execute(shop.select(shop.SecurityIncidentEvent).order_by(shop.SecurityIncidentEvent.id.desc()).limit(100))).scalars().all()
    return [{"id":x.id,"severity":x.severity,"category":x.category,"title":x.title,"details":x.details,"status":x.status,"created_at":str(x.created_at),"resolved_at":str(x.resolved_at) if x.resolved_at else None} for x in rows]

@shop.app.post("/api/admin/v41/incidents")
async def v41_incident_create(payload:IncidentCreateIn,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("ops.incidents"))):
    x=shop.SecurityIncidentEvent(**payload.model_dump()); db.add(x); await shop.audit(db,"incident.created",admin.email,None,payload.model_dump()); await db.commit(); await db.refresh(x)
    notified=0
    if x.category=="service":  # v28.47: subscribers of the status page hear about service incidents
        from .status_page import notify
        try: notified=await notify(db,x,True)
        except Exception as exc: shop.logger.warning("Status news was not sent: %s", exc)
    return {"id":x.id,"status":x.status,"notified":notified}

@shop.app.post("/api/admin/v41/incidents/{incident_id}/resolve")
async def v41_incident_resolve(incident_id:int,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("ops.incidents"))):
    x=await db.get(shop.SecurityIncidentEvent,incident_id)
    if not x: raise shop.HTTPException(404,"Инцидент не найден")
    was_open=x.status!="resolved"
    x.status="resolved"; x.resolved_at=shop.datetime.utcnow(); await shop.audit(db,"incident.resolved",admin.email,str(incident_id)); await db.commit()
    if was_open and x.category=="service":
        from .status_page import notify
        try: await notify(db,x,False)
        except Exception as exc: shop.logger.warning("Status news was not sent: %s", exc)
    return {"ok":True}

@shop.app.get("/api/admin/v41/backups/verification")
async def v41_backup_verification_list(db:AsyncSession=Depends(get_db),admin=Depends(require_permission("ops.backups.verify"))):
    rows=(await db.execute(shop.select(shop.BackupVerification).order_by(shop.BackupVerification.id.desc()).limit(100))).scalars().all()
    return [{"id":x.id,"backup_id":x.backup_id,"status":x.status,"checksum_ok":x.checksum_ok,"archive_safe":x.archive_safe,"restore_tested":x.restore_tested,"error":"unavailable" if x.error else None,"created_at":str(x.created_at),"finished_at":str(x.finished_at) if x.finished_at else None} for x in rows]

@shop.app.post("/api/admin/v41/backups/{backup_id}/test-restore")
async def v41_backup_test_restore(backup_id:int,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("ops.backups.verify"))):
    # v28.29.0: the check lives in backup_verify (also run weekly by itself) and compares
    # the restored customers, subscriptions and payments with the live database.
    from .backup_verify import verify
    return await verify(db,backup_id,admin.email)

@shop.app.get("/api/admin/v41/referrals")
async def v41_referrals(db:AsyncSession=Depends(get_db),admin=Depends(require_permission("referrals.read"))):
    rows=(await db.execute(shop.select(shop.ReferralLedger.user_id,shop.func.sum(shop.ReferralLedger.amount)).group_by(shop.ReferralLedger.user_id).order_by(shop.desc(shop.func.sum(shop.ReferralLedger.amount))).limit(100))).all()
    return [{"user_id":uid,"lifetime_commission":float(amount or 0)} for uid,amount in rows]

@shop.app.get("/api/admin/v41/promotions")
async def v41_promotions(db:AsyncSession=Depends(get_db),admin=Depends(require_permission("marketing.read"))):
    rows=(await db.execute(shop.select(shop.Promotion).order_by(shop.Promotion.priority.desc(),shop.Promotion.id.desc()))).scalars().all()
    return [{"id":x.id,"name":x.name,"kind":x.kind,"value":float(x.value),"plan_ids":x.plan_ids,"enabled":x.enabled,"starts_at":str(x.starts_at) if x.starts_at else None,"ends_at":str(x.ends_at) if x.ends_at else None,"priority":x.priority,"exclusive":x.exclusive} for x in rows]

# Passkey inventory; cryptographic ceremonies live in passkeys.py.
@shop.app.get("/api/admin/v41/passkeys")
async def v41_passkeys(db:AsyncSession=Depends(get_db),admin=Depends(require_permission("security.passkeys"))):
    rows=(await db.execute(shop.select(shop.WebAuthnCredential).where(shop.WebAuthnCredential.admin_id==admin.id).order_by(shop.WebAuthnCredential.id.desc()))).scalars().all()
    return [{"id":x.id,"name":x.name,"created_at":str(x.created_at),"last_used_at":str(x.last_used_at) if x.last_used_at else None,"transports":x.transports,"sign_count":x.sign_count} for x in rows]

@shop.app.delete("/api/admin/v41/passkeys/{credential_id}")
async def v41_passkey_delete(credential_id:int,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("security.passkeys"))):
    x=await db.get(shop.WebAuthnCredential,credential_id)
    if not x or x.admin_id!=admin.id: raise shop.HTTPException(404,"Passkey не найден")
    await db.delete(x); await shop.audit(db,"passkey.deleted",admin.email,str(credential_id)); await db.commit(); return {"ok":True}


__all__ = ['FeatureFlagIn', 'IncidentCreateIn', 'ProviderHealthIn', 'V41_FEATURE_DEFAULTS', '_ensure_v41_defaults', 'enterprise_campaign_create', 'enterprise_campaign_update', 'enterprise_campaigns', 'enterprise_monitoring', 'enterprise_monitoring_create', 'enterprise_monitoring_delete', 'enterprise_rule_create', 'enterprise_rule_update', 'enterprise_rules', 'enterprise_summary', 'v41_analytics', 'v41_backup_test_restore', 'v41_backup_verification_list', 'v41_crm_users', 'v41_diagnostics', 'v41_feature_update', 'v41_features', 'v41_incident_create', 'v41_incident_resolve', 'v41_incidents', 'v41_passkey_delete', 'v41_passkeys', 'v41_promotions', 'v41_provider_reset', 'v41_provider_update', 'v41_providers', 'v41_referrals']
# Imported before main finished (``from app import enterprise_api`` first)? Then main's star
# import saw a half-loaded module; hand the names over now that they exist.
shop.__dict__.update({_n: globals()[_n] for _n in __all__})
