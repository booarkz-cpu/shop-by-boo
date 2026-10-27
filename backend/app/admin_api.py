"""Admin API: admin and customer endpoints moved out of main.py (v28.28.0).

Names that belong to main are read through ``shop.<name>`` at call time, so tests and
operators that patch ``app.main`` keep affecting this code exactly as before."""
from .db import get_db
from .security import require_permission
from fastapi import Depends
from fastapi import Request
from fastapi import Response
from pydantic import BaseModel
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from . import main as shop

# ---------- Admin API ----------
@shop.app.get("/api/admin/customers/{user_id}/360")
async def customer_360(user_id:int,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("users.read"))):
    user=await db.get(shop.User,user_id)
    if not user: raise shop.HTTPException(404,"User not found")
    sub=await db.scalar(shop.select(shop.Subscription).where(shop.Subscription.user_id==user_id,shop.Subscription.is_primary.is_(True)))
    payments=(await db.execute(shop.select(shop.Payment).where(shop.Payment.user_id==user_id).order_by(shop.Payment.id.desc()).limit(100))).scalars().all()
    refunds=(await db.execute(shop.select(shop.RefundRequest).where(shop.RefundRequest.user_id==user_id).order_by(shop.RefundRequest.id.desc()).limit(50))).scalars().all()
    devices=(await db.execute(shop.select(shop.UserDevice).where(shop.UserDevice.user_id==user_id).order_by(shop.UserDevice.id.desc()))).scalars().all()
    referrals=(await db.execute(shop.select(shop.ReferralLedger).where(shop.ReferralLedger.user_id==user_id).order_by(shop.ReferralLedger.id.desc()).limit(50))).scalars().all()
    tickets=(await db.execute(shop.select(shop.SupportTicket).where(shop.SupportTicket.user_id==user_id).order_by(shop.SupportTicket.id.desc()).limit(50))).scalars().all()
    signals=(await db.execute(shop.select(shop.FraudSignal).where(shop.FraudSignal.user_id==user_id).order_by(shop.FraudSignal.id.desc()).limit(50))).scalars().all()
    subscriptions=(await db.execute(shop.select(shop.Subscription).where(shop.Subscription.user_id==user_id).order_by(shop.Subscription.id))).scalars().all()
    return {"subscriptions":[{"id":x.id,"name":x.name,"plan_id":x.plan_id,"is_primary":x.is_primary,"status":x.lifecycle_status,"expires_at":x.expires_at} for x in subscriptions],"user":{"id":user.id,"telegram_id":user.telegram_id,"yandex_id":user.yandex_id,"username":user.username,"created_at":user.created_at,"deleted_at":user.deleted_at},"subscription":None if not sub else {"id":sub.id,"plan_id":sub.plan_id,"status":sub.lifecycle_status,"expires_at":sub.expires_at,"grace_until":sub.grace_until,"scheduled_cancel_at":sub.scheduled_cancel_at},"payments":[{"id":p.id,"order_id":p.order_id,"amount":str(p.amount),"currency":p.currency,"status":p.status,"fulfillment_status":p.fulfillment_status,"created_at":p.created_at} for p in payments],"refunds":[{"id":r.id,"payment_id":r.payment_id,"status":r.status,"amount":str(r.amount),"reason":shop._public_refund_reason(r.reason)} for r in refunds],"devices":[{"id":d.id,"name":d.name,"status":d.status,"last_ip":d.last_ip,"last_seen_at":d.last_seen_at} for d in devices],"referrals":[{"id":x.id,"amount":str(x.amount),"kind":x.kind,"payment_id":x.payment_id} for x in referrals],"tickets":[{"id":t.id,"subject":t.subject,"status":t.status,"created_at":t.created_at} for t in tickets],"fraud":[{"id":x.id,"kind":x.kind,"score":x.score,"status":x.status,"details":x.details} for x in signals]}

@shop.app.get("/api/admin/refunds/{refund_id}/dry-run")
async def refund_dry_run(refund_id:int,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("payments.refund"))):
    r=await db.get(shop.RefundRequest,refund_id)
    if not r: raise shop.HTTPException(404,"Refund not found")
    p=await db.get(shop.Payment,r.payment_id)
    if not p: raise shop.HTTPException(404,"Payment not found")
    later_paid=int(await db.scalar(shop.select(shop.func.count()).select_from(shop.Payment).where(shop.Payment.user_id==p.user_id,shop.Payment.subscription_id==p.subscription_id,shop.Payment.id>p.id,shop.Payment.status.in_({"paid","fulfilled"}),shop.Payment.fulfillment_status=="completed")) or 0)
    reward=await db.scalar(shop.select(shop.ReferralReward).where(shop.ReferralReward.payment_id==p.id,shop.ReferralReward.status=="credited"))
    from .models import ReferralLevelReward
    extra=await db.scalar(shop.select(shop.func.coalesce(shop.func.sum(ReferralLevelReward.amount),0)).where(ReferralLevelReward.payment_id==p.id,ReferralLevelReward.status=="credited")) or shop.Decimal("0")
    referral_total=(reward.amount if reward else shop.Decimal("0"))+extra
    from .models import PartnerCommission
    partner_commission=await db.scalar(shop.select(PartnerCommission).where(PartnerCommission.payment_id==p.id,PartnerCommission.status=="credited"))
    sub=await shop.payment_target(db,p)
    actions=["refund_provider"]
    if sub and later_paid==0: actions.append("revoke_subscription")
    if referral_total > 0: actions.append("reverse_referral_reward")
    if partner_commission: actions.append("reverse_partner_commission")
    return {"safe_to_execute":p.status in {"paid","fulfilled"} and r.status in {"requested","approved","review"},"payment_id":p.id,"amount":str(p.amount),"currency":p.currency,"subscription":{"id":sub.id,"current_expires_at":sub.expires_at} if sub else None,"later_fulfilled_payments":later_paid,"referral_reward":str(referral_total) if referral_total > 0 else None,"partner_commission":str(partner_commission.amount) if partner_commission else None,"planned_actions":actions}

@shop.app.get("/api/admin/security/risk-summary")
async def risk_summary(db:AsyncSession=Depends(get_db),admin=Depends(require_permission("security.manage"))):
    open_signals=int(await db.scalar(shop.select(shop.func.count()).select_from(shop.FraudSignal).where(shop.FraudSignal.status=="open")) or 0)
    critical=int(await db.scalar(shop.select(shop.func.count()).select_from(shop.FraudSignal).where(shop.FraudSignal.status=="open",shop.FraudSignal.score>=80)) or 0)
    recent=(await db.execute(shop.select(shop.FraudSignal).where(shop.FraudSignal.status=="open").order_by(shop.FraudSignal.score.desc(),shop.FraudSignal.id.desc()).limit(20))).scalars().all()
    return {"open":open_signals,"critical":critical,"signals":[{"id":x.id,"user_id":x.user_id,"kind":x.kind,"score":x.score,"ip":x.ip,"created_at":x.created_at} for x in recent]}

@shop.app.get("/api/admin/health/summary")
async def health_summary(db:AsyncSession=Depends(get_db),admin=Depends(require_permission("ops.diagnostics"))):
    checks=[]
    try:
        await db.execute(shop.sql_text("SELECT 1")); checks.append({"name":"PostgreSQL","status":"ok"})
    except Exception as exc:
        shop.logger.warning("Health summary PostgreSQL check failed: %s", exc)
        checks.append({"name":"PostgreSQL","status":"error","error":"unavailable"})
    if shop.redis_client:
        try:
            start=shop.asyncio.get_running_loop().time(); await shop.redis_client.ping(); checks.append({"name":"Redis","status":"ok","latency_ms":round((shop.asyncio.get_running_loop().time()-start)*1000,1)})
        except Exception as exc:
            shop.logger.warning("Health summary Redis check failed: %s", exc)
            checks.append({"name":"Redis","status":"error","error":"unavailable"})
    try:
        start=shop.asyncio.get_running_loop().time(); await shop.RemnawaveClient().list_nodes(start=0,size=1); checks.append({"name":"Remnawave","status":"ok","latency_ms":round((shop.asyncio.get_running_loop().time()-start)*1000,1)})
    except Exception: checks.append({"name":"Remnawave","status":"error","error":"unavailable"})
    return {"status":"ok" if all(x["status"]=="ok" for x in checks) else "degraded","checks":checks,"incident_mode":(await shop.setting_value(db,"incident_mode","0"))=="1","payments_paused":not await shop.production_payments_allowed(db)}

@shop.app.get("/api/admin/gifts")
async def admin_gifts(db:AsyncSession=Depends(get_db),admin=Depends(require_permission("marketing.read"))):
    rows=(await db.execute(shop.select(shop.GiftCode).order_by(shop.GiftCode.id.desc()).limit(200))).scalars().all()
    return [{"id":x.id,"code":x.code,"plan_id":x.plan_id,"duration_days":x.duration_days,"max_uses":x.max_uses,"used_count":x.used_count,"expires_at":x.expires_at,"enabled":x.enabled,"purchaser_user_id":x.purchaser_user_id} for x in rows]

@shop.app.post("/api/admin/gifts")
async def admin_gift_create(payload:shop.GiftCreateIn,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("manage_marketing"))):
    plan=await db.get(shop.Plan,payload.plan_id)
    if not plan or not plan.enabled: raise shop.HTTPException(400,"Plan not found or disabled")
    code=payload.code.strip().upper()
    if await db.scalar(shop.select(shop.GiftCode.id).where(shop.GiftCode.code==code)): raise shop.HTTPException(409,"Gift code already exists")
    if payload.purchaser_user_id and not await db.get(shop.User,payload.purchaser_user_id): raise shop.HTTPException(400,"Purchaser not found")
    x=shop.GiftCode(code=code,plan_id=plan.id,duration_days=payload.duration_days,max_uses=payload.max_uses,expires_at=payload.expires_at,purchaser_user_id=payload.purchaser_user_id)
    db.add(x); await shop.audit(db,"gift.created",admin.email,code,{"plan_id":plan.id,"max_uses":payload.max_uses}); await db.commit(); await db.refresh(x)
    return {"id":x.id,"code":x.code}

def _remnawave_total(payload):
    if not isinstance(payload, dict):
        return None
    response = payload.get("response") if isinstance(payload.get("response"), dict) else payload
    try:
        return int(response.get("total"))
    except (TypeError, ValueError, AttributeError):
        return None

def _remote_user_id(value: str) -> str:
    if not value or len(value) > 80 or any(not (ch.isalnum() or ch in "-_") for ch in value):
        raise shop.HTTPException(400, "Некорректный идентификатор пользователя Remnawave")
    return value

@shop.app.get("/api/admin/overview")
async def admin_overview(db:AsyncSession=Depends(get_db),admin=Depends(require_permission("read"))):
    plan_count=int((await db.execute(shop.select(shop.func.count()).select_from(shop.Plan))).scalar() or 0)
    payment_count=int((await db.execute(shop.select(shop.func.count()).select_from(shop.Payment))).scalar() or 0)
    try:
        raw_users=await shop.RemnawaveClient().list_users(start=0,size=1)
        total=shop._remnawave_total(raw_users)
        users={"response":{"total":total}} if total is not None else {"error":"unavailable"}
        raw_nodes=await shop.RemnawaveClient().list_nodes(start=0,size=100)
        from .tariff_api import _iter_nodes, public_node
        safe_nodes=[public_node(n) for n in _iter_nodes(raw_nodes)]
        nodes={"total":len(safe_nodes),"nodes":safe_nodes}
    except Exception: users={"error":"unavailable"}; nodes={"error":"unavailable"}
    return {"plans":plan_count,"payments":payment_count,"remnawave_users":users,"nodes":nodes,"role":admin.role}

@shop.app.get("/api/admin/plans")
async def admin_list_plans(db:AsyncSession=Depends(get_db),admin=Depends(require_permission("read"))):
    rows=(await db.execute(shop.select(shop.Plan).order_by(shop.Plan.id))).scalars().all()
    return [{"id":p.id,"name":p.name,"price":float(p.price),"duration_days":p.duration_days,"traffic_limit_gb":p.traffic_limit_gb,"device_limit":p.device_limit,"remnawave_profile_id":p.remnawave_profile_id,"enabled":p.enabled,"family_seats":int(p.family_seats or 0)} for p in rows]

@shop.app.post("/api/admin/plans")
async def create_plan(payload:shop.PlanIn,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("manage_plans"))):
    p=shop.Plan(**payload.model_dump()); db.add(p); await shop.audit(db,"plan.created",admin.email,str(p.id),payload.model_dump()); await db.commit(); await db.refresh(p); return {"id":p.id}

class PlanEnabledIn(BaseModel):
    enabled: bool

@shop.app.post("/api/admin/plans/{plan_id}/enabled")
async def admin_set_plan_enabled(plan_id:int,payload:PlanEnabledIn,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("manage_plans"))):
    p=await db.get(shop.Plan,plan_id)
    if not p: raise shop.HTTPException(404,"Plan not found")
    p.enabled=payload.enabled
    await shop.audit(db,"plan.enabled",admin.email,str(plan_id),{"enabled":payload.enabled})
    await db.commit()
    return {"ok":True,"id":plan_id,"enabled":p.enabled}

@shop.app.put("/api/admin/plans/{plan_id}")
async def admin_update_plan(plan_id:int,payload:shop.PlanIn,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("manage_plans"))):
    p=await db.get(shop.Plan,plan_id)
    if not p: raise shop.HTTPException(404,"Plan not found")
    for k,v in payload.model_dump().items(): setattr(p,k,v)
    await shop.audit(db,"plan.updated",admin.email,str(plan_id),payload.model_dump()); await db.commit(); return {"ok":True,"id":plan_id}

@shop.app.delete("/api/admin/plans/{plan_id}")
async def admin_delete_plan(plan_id:int,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("manage_plans"))):
    p=await db.get(shop.Plan,plan_id)
    if not p: raise shop.HTTPException(404,"Plan not found")
    refs=(await db.execute(shop.select(shop.func.count()).select_from(shop.Payment).where(shop.Payment.plan_id==plan_id))).scalar() or 0
    subs=(await db.execute(shop.select(shop.func.count()).select_from(shop.Subscription).where(shop.Subscription.plan_id==plan_id))).scalar() or 0
    trials=(await db.execute(shop.select(shop.func.count()).select_from(shop.TrialGrant).where(shop.TrialGrant.plan_id==plan_id))).scalar() or 0
    if refs or subs or trials:
        raise shop.HTTPException(409,"Тариф уже используется платежами, подписками или пробными периодами; отключите его вместо удаления")
    await db.delete(p); await shop.audit(db,"plan.deleted",admin.email,str(plan_id)); await db.commit(); return {"ok":True}

@shop.app.get("/api/admin/payments/{payment_id}")
async def admin_payment_detail(payment_id:int,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("read"))):
    row=await db.get(shop.Payment,payment_id)
    if not row: raise shop.HTTPException(404,"Payment not found")
    return {"id":row.id,"user_id":row.user_id,"plan_id":row.plan_id,"provider":row.provider,"purpose":row.purpose or "subscription","order_id":row.order_id,"amount":float(row.amount),"currency":row.currency,"status":row.status,"fulfillment_status":row.fulfillment_status,"created_at":str(row.created_at),"paid_at":str(row.paid_at) if row.paid_at else None}

@shop.app.get("/api/admin/github-update")
async def admin_github_update(admin=Depends(require_permission("ops.releases"))):
    from .github_update import fetch_latest_release, release_status
    from .release_identity import DISTRIBUTION_TAG
    return release_status(shop.APP_VERSION, await fetch_latest_release(), current_distribution=DISTRIBUTION_TAG)

@shop.app.get("/api/admin/payments")
async def admin_payments(page:int=1,page_size:int=50,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("read"))):
    page=max(1,page); page_size=max(1,min(page_size,100)); offset=(page-1)*page_size
    rows=(await db.execute(shop.select(shop.Payment).order_by(shop.Payment.id.desc()).offset(offset).limit(page_size))).scalars().all()
    return [{"id":x.id,"provider":x.provider,"status":x.status,"fulfillment_status":x.fulfillment_status,"fulfillment_attempts":x.fulfillment_attempts,"amount":float(x.amount),"currency":x.currency,"created_at":str(x.created_at),"paid_at":str(x.paid_at) if x.paid_at else None} for x in rows]

_AUDIT_SECRET_KEYS = {"error", "token", "secret", "password", "authorization"}
_REFUND_EXCEPTION_TAILS = (
    "\nRevoke pending: ",
    "\nRefund reconciliation pending: ",
    "\nRevoke retry pending: ",
    "\nProvider refund outcome uncertain/failed: ",
)

def _redact_audit_value(value):
    if isinstance(value, dict):
        clean = {}
        for key, item in value.items():
            if str(key).lower() in shop._AUDIT_SECRET_KEYS:
                clean[key] = "unavailable"
            else:
                clean[key] = shop._redact_audit_value(item)
        return clean
    if isinstance(value, list):
        return [shop._redact_audit_value(item) for item in value]
    return value

def _public_audit_details(details):
    if not isinstance(details, str) or not details:
        return details
    try:
        parsed = shop.json.loads(details)
    except (TypeError, ValueError):
        return details
    if not isinstance(parsed, (dict, list)):
        return details
    return shop.json.dumps(shop._redact_audit_value(parsed), ensure_ascii=False)

def _public_refund_reason(reason):
    if not isinstance(reason, str) or not reason:
        return reason
    cut = len(reason)
    for marker in shop._REFUND_EXCEPTION_TAILS:
        idx = reason.find(marker)
        if idx != -1:
            cut = min(cut, idx)
    return reason[:cut]

@shop.app.get("/api/admin/audit")
async def admin_audit(page:int=1,page_size:int=50,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("read"))):
    page=max(1,page); page_size=max(1,min(page_size,100)); offset=(page-1)*page_size
    rows=(await db.execute(shop.select(shop.AuditLog).order_by(shop.AuditLog.id.desc()).offset(offset).limit(page_size))).scalars().all()
    return [{"id":x.id,"action":x.action,"actor":x.actor,"target":x.target,"details":shop._public_audit_details(x.details),"created_at":str(x.created_at)} for x in rows]

@shop.app.get("/api/admin/remnawave/users")
async def rw_users(start:int=0,size:int=25,admin=Depends(require_permission("read"))): return shop.redact_remote(await shop.RemnawaveClient().list_users(start,max(1,min(size,1000))))
@shop.app.get("/api/admin/remnawave/users/stream")
async def rw_user_stream(telegram_id:int|None=None,cursor:int|None=None,size:int=250,status:str|None=None,admin=Depends(require_permission("read"))): return shop.redact_remote(await shop.RemnawaveClient().stream_users(telegram_id,cursor,size,status))
@shop.app.get("/api/admin/remnawave/nodes")
async def rw_nodes(start:int=0,size:int=25,admin=Depends(require_permission("read"))):
    from .tariff_api import remnawave_server_status
    return await remnawave_server_status("admin")
@shop.app.get("/api/admin/remnawave/users/{user_id}")
async def rw_user(user_id:str,admin=Depends(require_permission("read"))): return shop.redact_remote(await shop.RemnawaveClient().get_user(shop._remote_user_id(user_id)))
@shop.app.post("/api/admin/remnawave/users/{user_id}/extend")
async def rw_extend(user_id:str,payload:dict,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("manage_users"))):
    user_id=shop._remote_user_id(user_id)
    # All manual extensions use the same remote-first verification algorithm as payment provisioning.
    days=int(payload.get("days",0))
    if not 1<=days<=3650: raise shop.HTTPException(400,"days must be 1..3650")
    rw=shop.RemnawaveClient(); remote=await rw.get_user(user_id)
    raw=remote.get("expireAt") or remote.get("expire_at") or remote.get("expiresAt") or remote.get("expires_at")
    if not raw: raise shop.HTTPException(409,"Remote user has no readable expiration date")
    try: before=shop.datetime.fromisoformat(str(raw).replace("Z","+00:00")).replace(tzinfo=None)
    except ValueError: raise shop.HTTPException(409,"Remote expiration date is invalid")
    after=before+shop.timedelta(days=days)
    result=await rw.extend_idempotent(user_id,days,before,after)
    await shop.audit(db,"remnawave.user.extend",admin.email,str(user_id),{"days":days,"verified_expires_at":str(result.get("expires_at"))}); await db.commit(); return {"ok":True,"already_applied":result.get("already_applied",False),"expires_at":result.get("expires_at")}
@shop.app.get("/api/admin/remnawave/users/{user_id}/subscription")
async def rw_subscription(user_id:str,admin=Depends(require_permission("users.keys"))): return await shop.RemnawaveClient().get_subscription(shop._remote_user_id(user_id))
@shop.app.get("/api/admin/remnawave/users/{user_id}/keys")
# Historical compatibility marker: async def rw_keys(user_id:int,admin=Depends(require_permission("manage_users")))
async def rw_keys(user_id:str,admin=Depends(require_permission("users.keys"))): return await shop.RemnawaveClient().get_connection_keys(shop._remote_user_id(user_id))

@shop.app.get("/api/admin/remnawave/health")
async def remnawave_health(admin=Depends(require_permission("read"))):
    from .tariff_api import remnawave_server_status
    return await remnawave_server_status("admin")

@shop.app.post("/api/admin/provision-node")
async def provision_node(payload:dict,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("provision_nodes"))):
    required=["host","ssh_username","compose_yaml"]
    if any(not payload.get(k) for k in required): raise shop.HTTPException(400,"host, ssh_username and compose_yaml are required")
    try:
        result=shop.run_ssh(host=payload["host"],port=int(payload.get("ssh_port",22)),username=payload["ssh_username"],password=payload.get("ssh_password"),private_key=payload.get("ssh_private_key"),compose_yaml=payload["compose_yaml"],panel_ip=payload.get("panel_ip",""),node_port=int(payload.get("node_port",2222)),host_key_fingerprint=payload.get("ssh_host_key"))
        await shop.audit(db,"node.provisioned",admin.email,payload["host"]); await db.commit(); return result
    except shop.ProvisionError as e: raise shop.HTTPException(400,str(e))
    except Exception as e: raise shop.HTTPException(502,"SSH provisioning failed") from e

class AdminUserIn(BaseModel):
    email:str=Field(min_length=5,max_length=320)
    password:str|None=Field(default=None,min_length=12,max_length=256)
    role:str="viewer"
    disabled:bool=False
    telegram_id:int|None=Field(default=None,ge=1)

@shop.app.get("/api/admin/admins")
async def list_admins(db:AsyncSession=Depends(get_db),admin=Depends(require_permission("manage_admins"))):
    rows=(await db.execute(shop.select(shop.AdminUser).order_by(shop.AdminUser.id))).scalars().all()
    return [{"id":x.id,"email":x.email,"telegram_id":x.telegram_id,"role":x.role,"disabled":x.disabled,"mfa_enabled":x.mfa_enabled,"created_at":x.created_at,"last_login_at":x.last_login_at} for x in rows]

@shop.app.post("/api/admin/admins")
async def create_admin(payload:AdminUserIn,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("manage_admins"))):
    if payload.role not in {"viewer","operator","admin"} or not payload.password: raise shop.HTTPException(400,"Valid role and password are required")
    x=shop.AdminUser(email=payload.email.strip().lower(),telegram_id=payload.telegram_id,password_hash=shop.hash_password(payload.password),role=payload.role,disabled=payload.disabled); db.add(x)
    try: await db.commit()
    except shop.IntegrityError: await db.rollback(); raise shop.HTTPException(409,"Администратор с таким email или Telegram ID уже существует")
    await shop.audit(db,"admin.created",admin.email,x.email,{"role":x.role}); await db.commit(); return {"id":x.id}

@shop.app.put("/api/admin/admins/{admin_id}")
async def update_admin(admin_id:int,payload:AdminUserIn,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("manage_admins"))):
    x=await db.get(shop.AdminUser,admin_id)
    if not x: raise shop.HTTPException(404,"Admin not found")
    if admin.id==x.id and payload.disabled: raise shop.HTTPException(400,"You cannot disable yourself")
    if payload.role not in {"viewer","operator","admin"}: raise shop.HTTPException(400,"Invalid role")
    old_role=x.role; old_disabled=x.disabled; old_email=x.email; old_telegram_id=x.telegram_id
    x.email=payload.email.strip().lower(); x.telegram_id=payload.telegram_id; x.role=payload.role; x.disabled=payload.disabled
    if payload.password: x.password_hash=shop.hash_password(payload.password)
    if old_role != x.role or old_disabled != x.disabled or payload.password or old_email != x.email or old_telegram_id != x.telegram_id: await db.execute(__import__("sqlalchemy").update(shop.AdminSession).where(shop.AdminSession.admin_id==x.id,shop.AdminSession.revoked_at.is_(None)).values(revoked_at=shop.datetime.utcnow()))
    await shop.audit(db,"admin.updated",admin.email,x.email,{"role":x.role,"disabled":x.disabled}); await db.commit(); return {"ok":True}

@shop.app.delete("/api/admin/admins/{admin_id}")
async def delete_admin(admin_id:int,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("manage_admins"))):
    x=await db.get(shop.AdminUser,admin_id)
    if not x: raise shop.HTTPException(404,"Admin not found")
    if x.id==admin.id: raise shop.HTTPException(400,"You cannot delete yourself")
    await db.delete(x); await shop.audit(db,"admin.deleted",admin.email,x.email); await db.commit(); return {"ok":True}

@shop.app.post("/api/admin/auth/logout")
async def admin_logout(request:Request,response:Response,db:AsyncSession=Depends(get_db)):
    authorization=request.headers.get("Authorization", "")
    token=authorization[7:] if authorization.startswith("Bearer ") else request.cookies.get("rw_admin")
    if token:
        try:
            claims=shop.decode_token(token)
        except shop.HTTPException as exc:
            if exc.status_code != 401: raise
            claims={}
        try:
            jti=claims.get("jti")
            if claims.get("type") == "admin" and jti:
                row=(await db.execute(shop.select(shop.AdminSession).where(shop.AdminSession.jti_hash==shop.hashlib.sha256(jti.encode()).hexdigest()))).scalar_one_or_none()
                if row: row.revoked_at=shop.datetime.utcnow(); await db.commit()
        except Exception as exc:
            await db.rollback()
            raise shop.HTTPException(503, "Could not revoke admin session") from exc
    response.delete_cookie("rw_admin"); response.delete_cookie("rw_csrf"); return {"ok":True}

@shop.app.get("/api/admin/security")
async def admin_security(db:AsyncSession=Depends(get_db),admin=Depends(require_permission("read"))):
    active_sessions=int((await db.execute(shop.select(shop.func.count()).select_from(shop.AdminSession).where(shop.AdminSession.revoked_at.is_(None),shop.AdminSession.expires_at>shop.datetime.utcnow()))).scalar() or 0)
    failed_24h=int((await db.execute(shop.select(shop.func.count()).select_from(shop.Payment).where(shop.Payment.fulfillment_status=="failed",shop.Payment.created_at>=shop.datetime.utcnow()-shop.timedelta(hours=24)))).scalar() or 0)
    last_backup=(await db.execute(shop.select(shop.BackupJob).where(shop.BackupJob.status=="completed").order_by(shop.BackupJob.created_at.desc()).limit(1))).scalar_one_or_none()
    return {"admin_auth":"password + optional TOTP; verified WebAuthn passkeys","mfa_enabled":bool(admin.mfa_enabled),"production_payments_enabled":await shop.production_payments_allowed(db),"rbac_roles":["viewer","operator","admin"],"version":shop.APP_VERSION,"active_sessions":active_sessions,"fulfillment_failures_24h":failed_24h,"backup":{"last_success":last_backup.created_at if last_backup else None,"healthy":bool(last_backup and last_backup.created_at>=shop.datetime.utcnow()-shop.timedelta(hours=25))},"ssh_credentials_persisted":False,"node_compose_source":"official Remnawave Panel"}


class ProductionGateIn(BaseModel):
    enabled: bool

@shop.app.post("/api/admin/payments/production-gate")
async def production_payment_gate(payload:ProductionGateIn, db:AsyncSession=Depends(get_db), admin=Depends(require_permission("security.manage"))):
    """Emergency switch: real payments are open by default; an administrator may close and reopen them."""
    await shop._advisory_lock(db, 1300000013)
    await shop.set_setting(db,shop.PRODUCTION_PAYMENTS_CLOSED_KEY,"0" if payload.enabled else "1")
    await shop.audit(db,"payments.real.opened" if payload.enabled else "payments.real.closed",admin.email,None)
    await db.commit()
    return {"enabled":payload.enabled}


__all__ = ['AdminUserIn', 'PlanEnabledIn', 'ProductionGateIn', '_AUDIT_SECRET_KEYS', '_REFUND_EXCEPTION_TAILS', '_public_audit_details', '_public_refund_reason', '_redact_audit_value', '_remnawave_total', '_remote_user_id', 'admin_audit', 'admin_delete_plan', 'admin_gift_create', 'admin_gifts', 'admin_github_update', 'admin_list_plans', 'admin_logout', 'admin_overview', 'admin_payment_detail', 'admin_payments', 'admin_security', 'admin_set_plan_enabled', 'admin_update_plan', 'create_admin', 'create_plan', 'customer_360', 'delete_admin', 'health_summary', 'list_admins', 'production_payment_gate', 'provision_node', 'refund_dry_run', 'remnawave_health', 'risk_summary', 'rw_extend', 'rw_keys', 'rw_nodes', 'rw_subscription', 'rw_user', 'rw_user_stream', 'rw_users', 'update_admin']
# Imported before main finished (``from app import admin_api`` first)? Then main's star
# import saw a half-loaded module; hand the names over now that they exist.
shop.__dict__.update({_n: globals()[_n] for _n in __all__})
