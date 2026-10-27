"""Staging E2E: admin and customer endpoints moved out of main.py (v28.28.0).

Names that belong to main are read through ``shop.<name>`` at call time, so tests and
operators that patch ``app.main`` keep affecting this code exactly as before."""
from .db import get_db
from .security import require_permission
from fastapi import Depends
from fastapi import Request
from pydantic import BaseModel
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession
import asyncio

from . import main as shop

# ---------- Staging E2E ----------
STAGING_E2E_CONFIG_KEY="staging_e2e.config"
STAGING_E2E_STATUS_KEY="staging_e2e.status"
STAGING_E2E_LOCK=asyncio.Lock()
# Real payments are open from the first start. "1" means an administrator closed them
# (emergency switch). The staging E2E v2 check is optional and never closes payments.
PRODUCTION_PAYMENTS_CLOSED_KEY="payments.real.closed"
PRODUCTION_GATE_MAX_AGE_HOURS=24

async def production_payments_allowed(db):
    """Real payments are allowed unless an administrator closed them."""
    return await shop.setting_value(db,shop.PRODUCTION_PAYMENTS_CLOSED_KEY,"0") != "1"

class StagingE2EConfigIn(BaseModel):
    public_base_url:str=Field(min_length=8,max_length=2048)
    remnawave_url:str=Field(min_length=8,max_length=2048)
    remnawave_token:str=Field(default="",max_length=4096)
    user_bearer_token:str=Field(default="",max_length=4096)
    plan_id:int=Field(gt=0)
    providers:list[str]=Field(default_factory=lambda:["yookassa","platega","rollypay"])
    yookassa_enabled:bool=True
    platega_enabled:bool=True
    rollypay_enabled:bool=True
    timeout_seconds:int=Field(default=1800,ge=60,le=7200)
    yookassa_api_url:str="https://api.yookassa.ru"
    yookassa_shop_id:str=""
    yookassa_secret_key:str=""
    platega_api_url:str="https://app.platega.io"
    platega_merchant_id:str=""
    platega_secret:str=""
    rollypay_api_url:str="https://rollypay.io"
    rollypay_api_key:str=""
    rollypay_signing_secret:str=""
    platega_refund_url:str=""
    platega_refund_status_url:str=""
    rollypay_refund_url:str=""
    rollypay_refund_status_url:str=""
    staging_confirmed:bool=False

async def _staging_config(db):
    raw=await shop.setting_value(db,shop.STAGING_E2E_CONFIG_KEY,"")
    if not raw: return None
    try: return shop.json.loads(shop.decrypt_secret(raw))
    except Exception as exc:
        shop.logger.warning("Unable to decrypt staging E2E config: %s", exc); return None

@shop.app.get("/api/admin/staging-e2e/config")
async def staging_e2e_config(db:AsyncSession=Depends(get_db),admin=Depends(require_permission("staging_e2e.manage"))):
    cfg=await shop._staging_config(db)
    status=await shop.setting_value(db,shop.STAGING_E2E_STATUS_KEY,"{}")
    try: status=shop.json.loads(status)
    except Exception: status={}
    if cfg:
        safe={"public_base_url":cfg.get("public_base_url"),"remnawave_url":cfg.get("remnawave_url"),"plan_id":cfg.get("plan_id"),"providers":cfg.get("providers",[]),"yookassa_enabled":cfg.get("yookassa_enabled",True),"platega_enabled":cfg.get("platega_enabled",True),"rollypay_enabled":cfg.get("rollypay_enabled",True),"timeout_seconds":cfg.get("timeout_seconds",1800),"staging_confirmed":bool(cfg.get("staging_confirmed")),"platega_refund_url":cfg.get("platega_refund_url") or "","platega_refund_status_url":cfg.get("platega_refund_status_url") or "","rollypay_refund_url":cfg.get("rollypay_refund_url") or "","rollypay_refund_status_url":cfg.get("rollypay_refund_status_url") or "","provider_credentials":{"yookassa":bool(cfg.get("yookassa_shop_id") and cfg.get("yookassa_secret_key")),"platega":bool(cfg.get("platega_merchant_id") and cfg.get("platega_secret")),"rollypay":bool(cfg.get("rollypay_api_key"))},"credentials_configured":True,"remnawave_token_configured":bool(cfg.get("remnawave_token")),"user_bearer_token_configured":bool(cfg.get("user_bearer_token"))}
    else: safe={"credentials_configured":False,"providers":["yookassa","platega","rollypay"],"timeout_seconds":1800}
    return {"config":safe,"status":status}

@shop.app.put("/api/admin/staging-e2e/config")
async def update_staging_e2e_config(payload:StagingE2EConfigIn,db:AsyncSession=Depends(get_db),admin=Depends(require_permission("staging_e2e.manage"))):
    await shop._advisory_lock(db, 1300000013)
    # Staging endpoints are administrator-supplied and later contacted by the server/runner.
    # Require globally routable HTTPS targets to prevent SSRF and DNS-rebinding to internal services.
    shop.validate_public_url(payload.public_base_url, allow_empty=False)
    shop.validate_public_url(payload.remnawave_url, allow_empty=False)
    for provider_url in (payload.yookassa_api_url, payload.platega_api_url, payload.rollypay_api_url):
        shop.validate_public_url(provider_url, allow_empty=False)
    if not payload.staging_confirmed:
        raise shop.HTTPException(400,"Подтвердите, что используются sandbox/staging-учётные данные; production-ключи запрещены")
    previous=await shop._staging_config(db) or {}
    data=payload.model_dump()
    for key in ("remnawave_token","user_bearer_token","yookassa_shop_id","yookassa_secret_key","platega_merchant_id","platega_secret","rollypay_api_key","rollypay_signing_secret"):
        if not str(data.get(key) or "").strip() and str(previous.get(key) or "").strip():
            data[key]=previous[key]
    for key in ("platega_refund_url","platega_refund_status_url","rollypay_refund_url","rollypay_refund_status_url"):
        if not str(data.get(key) or "").strip() and str(previous.get(key) or "").strip():
            data[key]=previous[key]
    for refund_url in (data.get("platega_refund_url"),data.get("platega_refund_status_url"),data.get("rollypay_refund_url"),data.get("rollypay_refund_status_url")):
        if str(refund_url or "").strip():
            shop.validate_public_url(str(refund_url), allow_empty=False)
    if not str(data.get("remnawave_token") or "").strip():
        raise shop.HTTPException(400,"Укажите токен Remnawave для staging")
    prod_pairs=[(data.get("yookassa_shop_id"),data.get("yookassa_secret_key"),(shop.settings.yookassa_shop_id,shop.settings.yookassa_secret_key)),(data.get("platega_merchant_id"),data.get("platega_secret"),(shop.settings.platega_merchant_id,shop.settings.platega_secret)),(data.get("rollypay_api_key"),data.get("rollypay_signing_secret"),(shop.settings.rollypay_api_key,shop.settings.rollypay_signing_secret))]
    for a,b,(pa,pb) in prod_pairs:
        if (a and pa and a==pa) or (b and pb and b==pb):
            raise shop.HTTPException(400,"Staging E2E не может использовать production-платёжные credentials")
    providers=[p for p in payload.providers if p in {"yookassa","platega","rollypay"}]
    enabled=[p for p,flag in (("yookassa",payload.yookassa_enabled),("platega",payload.platega_enabled),("rollypay",payload.rollypay_enabled)) if flag]
    providers=[p for p in providers if p in enabled] or enabled
    if "platega" in providers and (not str(data.get("platega_refund_url") or "").strip() or not str(data.get("platega_refund_status_url") or "").strip()):
        raise shop.HTTPException(400,"Укажите публичные HTTPS URL возврата и статуса возврата Platega")
    if "rollypay" in providers and (not str(data.get("rollypay_refund_url") or "").strip() or not str(data.get("rollypay_refund_status_url") or "").strip()):
        raise shop.HTTPException(400,"Укажите публичные HTTPS URL возврата и статуса возврата RollyPay")
    data["providers"]=providers; data["runner_token"]=shop.secrets.token_urlsafe(32)
    data["revision"]=shop.secrets.token_hex(16)
    await shop.set_setting(db,shop.STAGING_E2E_CONFIG_KEY,shop.encrypt_secret(shop.json.dumps(data,ensure_ascii=False)))
    await shop.set_setting(db,shop.STAGING_E2E_STATUS_KEY,shop.json.dumps({"status":"never","full_e2e":False,"config_revision":data["revision"]}))
    await shop.audit(db,"staging_e2e.config.updated",admin.email,None,{"providers":providers,"public_base_url":payload.public_base_url,"remnawave_url":payload.remnawave_url,"plan_id":payload.plan_id})
    await db.commit()
    return {"ok":True,"providers":providers}

def _redact_staging_output(text: str, config: dict) -> str:
    redacted = text or ""
    for key in ("remnawave_token", "user_bearer_token", "runner_token", "yookassa_secret_key", "platega_secret", "rollypay_api_key", "rollypay_signing_secret"):
        value = str((config or {}).get(key) or "")
        if len(value) >= 8:
            redacted = redacted.replace(value, "[скрыто]")
    return redacted

async def _publish_staging_running(config, started, chunks):
    text=shop._redact_staging_output("".join(chunks)[-30000:], config)
    try:
        async with shop.AsyncSession(shop.engine,expire_on_commit=False) as db:
            await shop._advisory_lock(db, 1300000013)
            if await shop._staging_config_is_current(db, config):
                await shop.set_setting(db,shop.STAGING_E2E_STATUS_KEY,shop.json.dumps({"status":"running","started_at":started,"full_e2e":False,"config_revision":config["revision"],"output":text},ensure_ascii=False))
                await db.commit()
    except Exception as exc:
        shop.logger.warning("Staging E2E status update failed: %s", exc)

async def _run_staging_e2e(config, admin_email):
    started=shop.datetime.utcnow().isoformat()
    async with shop.AsyncSession(shop.engine,expire_on_commit=False) as db:
        await shop._advisory_lock(db, 1300000013)
        if not await shop._staging_config_is_current(db, config): return
        await shop.set_setting(db,shop.STAGING_E2E_STATUS_KEY,shop.json.dumps({"status":"running","started_at":started,"provider_results":[],"full_e2e":False,"config_revision":config["revision"],"output":""},ensure_ascii=False)); await db.commit()
    env=shop.os.environ.copy()
    env.update({"STAGING_PUBLIC_BASE_URL":config["public_base_url"],"STAGING_REMNAWAVE_URL":config["remnawave_url"],"STAGING_REMNAWAVE_TOKEN":config["remnawave_token"],"STAGING_USER_BEARER_TOKEN":config["user_bearer_token"],"STAGING_PLAN_ID":str(config["plan_id"]),"STAGING_TIMEOUT_SECONDS":str(config.get("timeout_seconds",1800)),"STAGING_PROVIDERS":",".join(config.get("providers",[])),"STAGING_RUNNER_TOKEN":config["runner_token"]})
    script="/app/staging-e2e.sh"
    chunks=[]
    try:
        proc=await shop.asyncio.create_subprocess_exec("bash",script,env=env,stdout=shop.asyncio.subprocess.PIPE,stderr=shop.asyncio.subprocess.STDOUT)
        async def _pump():
            while True:
                line=await proc.stdout.readline()
                if not line: return
                chunks.append(line.decode("utf-8","replace"))
                await shop._publish_staging_running(config, started, chunks)
        try:
            await shop.asyncio.wait_for(_pump(), timeout=int(config.get("timeout_seconds",1800))+30)
            if proc.returncode is None: await proc.wait()
        except shop.asyncio.TimeoutError:
            proc.kill(); await proc.wait(); raise RuntimeError("Превышен таймаут staging E2E")
        text=shop._redact_staging_output("".join(chunks)[-30000:], config)
        # Exit code 0 only means the runner completed its configured checks. A production gate
        # requires an explicit FULL_E2E_PASS marker emitted after checkout/webhook/fulfillment/refund
        # verification. A mention inside a help sentence does not count: the marker must be its own line.
        # This prevents the old false-positive where payment creation alone unlocked production.
        # The current runner has no evidence of webhook delivery or fulfillment.
        # Keep the gate closed until a v2 runner verifies those events end to end.
        full_pass = False
        status="passed" if full_pass else ("awaiting_checkout" if proc.returncode==0 else "failed")
        result={"status":status,"full_e2e":full_pass,"contract_version":1,"config_revision":config["revision"],"exit_code":proc.returncode,"finished_at":shop.datetime.utcnow().isoformat(),"output":text,"admin":admin_email}
    except Exception as exc:
        partial=shop._redact_staging_output("".join(chunks)[-30000:], config)
        result={"status":"failed","full_e2e":False,"config_revision":config["revision"],"exit_code":-1,"finished_at":shop.datetime.utcnow().isoformat(),"output":shop._redact_staging_output((partial+"\n"+str(exc)).strip(), config),"admin":admin_email}
    async with shop.AsyncSession(shop.engine,expire_on_commit=False) as db:
        await shop._advisory_lock(db, 1300000013)
        if not await shop._staging_config_is_current(db, config):
            await shop.audit(db,"staging_e2e.discarded",admin_email,None,{"reason":"configuration_changed"}); await db.commit(); return
        await shop.set_setting(db,shop.STAGING_E2E_STATUS_KEY,shop.json.dumps(result,ensure_ascii=False)); await shop.audit(db,"staging_e2e.completed",admin_email,None,{"status":result["status"],"exit_code":result["exit_code"]}); await db.commit()

async def _staging_config_is_current(db, config):
    current=await shop._staging_config(db)
    return bool(config.get("revision") and current and current.get("revision")==config["revision"])

async def _require_staging_runner(request:Request, db):
    client_host=request.client.host if request.client else ""
    if client_host not in {"127.0.0.1","::1"}: raise shop.HTTPException(403,"Staging endpoint доступен только локальному runner")
    cfg=await shop._staging_config(db)
    if not cfg or request.headers.get("X-Staging-Runner-Token") != cfg.get("runner_token"):
        raise shop.HTTPException(403,"Недействительный staging runner token")
    if not cfg.get("staging_confirmed"): raise shop.HTTPException(409,"Staging E2E не настроен безопасно")
    return cfg

def _staging_provider_creds(cfg, provider):
    return {"yookassa":{"api_url":cfg.get("yookassa_api_url"),"shop_id":cfg.get("yookassa_shop_id"),"secret_key":cfg.get("yookassa_secret_key")},"platega":{"api_url":cfg.get("platega_api_url"),"merchant_id":cfg.get("platega_merchant_id"),"secret":cfg.get("platega_secret"),"refund_url":cfg.get("platega_refund_url"),"refund_status_url":cfg.get("platega_refund_status_url")},"rollypay":{"api_url":cfg.get("rollypay_api_url"),"api_key":cfg.get("rollypay_api_key"),"signing_secret":cfg.get("rollypay_signing_secret"),"refund_url":cfg.get("rollypay_refund_url"),"refund_status_url":cfg.get("rollypay_refund_status_url")}}.get(provider)

@shop.app.post("/api/internal/staging-e2e/payment")
async def internal_staging_payment(payload:dict,request:Request,db:AsyncSession=Depends(get_db)):
    cfg=await shop._require_staging_runner(request, db)
    provider=str(payload.get("provider")); plan=await db.get(shop.Plan,int(payload.get("plan_id",0)))
    if not plan or not plan.enabled: raise shop.HTTPException(404,"Тестовый тариф не найден")
    creds=shop._staging_provider_creds(cfg, provider)
    if not creds: raise shop.HTTPException(400,"Неизвестный staging-провайдер")
    oid=f"STAGING-{provider.upper()}-{shop.secrets.token_hex(8)}"
    result=await shop.staging_create_payment(provider,creds,shop.Decimal(str(plan.price)),oid,"Staging E2E",cfg["public_base_url"].rstrip("/")+"/staging-e2e")
    return {"provider":provider,"order_id":oid,"amount":float(plan.price),**result}

@shop.app.post("/api/internal/staging-e2e/verify")
async def internal_staging_verify(payload:dict,request:Request,db:AsyncSession=Depends(get_db)):
    cfg=await shop._require_staging_runner(request, db)
    provider=str(payload.get("provider") or "")
    creds=shop._staging_provider_creds(cfg, provider)
    if not creds: raise shop.HTTPException(400,"Неизвестный staging-провайдер")
    try: amount=shop.Decimal(str(payload.get("amount")))
    except Exception: raise shop.HTTPException(400,"Некорректная сумма")
    try:
        return await shop.staging_read_payment(provider, creds, str(payload.get("payment_id") or ""), amount, str(payload.get("order_id") or ""))
    except Exception as exc:
        shop.logger.warning("Staging verify is still pending: %s", type(exc).__name__)
        return {"paid": False, "status": "unread"}

@shop.app.post("/api/internal/staging-e2e/refund")
async def internal_staging_refund(payload:dict,request:Request,db:AsyncSession=Depends(get_db)):
    cfg=await shop._require_staging_runner(request, db)
    provider=str(payload.get("provider") or "")
    creds=shop._staging_provider_creds(cfg, provider)
    if not creds: raise shop.HTTPException(400,"Неизвестный staging-провайдер")
    try: amount=shop.Decimal(str(payload.get("amount")))
    except Exception: raise shop.HTTPException(400,"Некорректная сумма")
    return await shop.staging_refund_payment(provider, creds, str(payload.get("payment_id") or ""), amount)

@shop.app.post("/api/internal/staging-e2e/refund-status")
async def internal_staging_refund_status(payload:dict,request:Request,db:AsyncSession=Depends(get_db)):
    cfg=await shop._require_staging_runner(request, db)
    provider=str(payload.get("provider") or "")
    creds=shop._staging_provider_creds(cfg, provider)
    if not creds: raise shop.HTTPException(400,"Неизвестный staging-провайдер")
    try:
        return await shop.staging_refund_read(provider, creds, str(payload.get("refund_id") or ""))
    except Exception as exc:
        shop.logger.warning("Staging refund status is still pending: %s", type(exc).__name__)
        return {"status": "unread", "done": False}

@shop.app.post("/api/internal/staging-e2e/remnawave")
async def internal_staging_remnawave(request:Request,db:AsyncSession=Depends(get_db)):
    cfg=await shop._require_staging_runner(request, db)
    url=shop.validate_public_url(cfg.get("remnawave_url"), allow_empty=False)
    token=str(cfg.get("remnawave_token") or "")
    async with shop._pinned_public_http_client(20) as client:
        response=await client.get(f"{str(url).rstrip('/')}/api/users?start=0&size=1", headers={"Authorization": f"Bearer {token}"})
    if response.status_code >= 400:
        raise shop.HTTPException(502,"Staging Remnawave не подтвердил токен")
    return {"ok": True}

@shop.app.post("/api/admin/staging-e2e/run")
async def run_staging_e2e(db:AsyncSession=Depends(get_db),admin=Depends(require_permission("staging_e2e.manage"))):
    if shop.STAGING_E2E_LOCK.locked(): raise shop.HTTPException(409,"Staging E2E уже выполняется")
    await shop._advisory_lock(db, 1300000013)
    cfg=await shop._staging_config(db)
    if not cfg: raise shop.HTTPException(400,"Сначала сохраните конфигурацию staging E2E")
    if not cfg.get("revision"): raise shop.HTTPException(409,"Сохраните конфигурацию staging E2E заново перед запуском")
    status_raw=await shop.setting_value(db,shop.STAGING_E2E_STATUS_KEY,"{}")
    try: status=shop.json.loads(status_raw)
    except Exception: status={}
    if status.get("status") in {"queued","running"}: raise shop.HTTPException(409,"Staging E2E уже выполняется")
    async def guarded():
        async with shop.STAGING_E2E_LOCK: await shop._run_staging_e2e(cfg,admin.email)
    await shop.set_setting(db,shop.STAGING_E2E_STATUS_KEY,shop.json.dumps({"status":"queued","full_e2e":False,"config_revision":cfg["revision"]}))
    await shop.audit(db,"staging_e2e.started",admin.email,None,{"providers":cfg.get("providers",[])})
    await db.commit()
    shop.asyncio.create_task(guarded())
    return {"started":True}

@shop.app.get("/api/admin/staging-e2e/status")
async def staging_e2e_status(db:AsyncSession=Depends(get_db),admin=Depends(require_permission("staging_e2e.manage"))):
    raw=await shop.setting_value(db,shop.STAGING_E2E_STATUS_KEY,"{}")
    try: return shop.json.loads(raw)
    except Exception: return {"status":"never"}


__all__ = ['PRODUCTION_GATE_MAX_AGE_HOURS', 'PRODUCTION_PAYMENTS_CLOSED_KEY', 'STAGING_E2E_CONFIG_KEY', 'STAGING_E2E_LOCK', 'STAGING_E2E_STATUS_KEY', 'StagingE2EConfigIn', '_publish_staging_running', '_redact_staging_output', '_require_staging_runner', '_run_staging_e2e', '_staging_config', '_staging_config_is_current', '_staging_provider_creds', 'internal_staging_payment', 'internal_staging_refund', 'internal_staging_refund_status', 'internal_staging_remnawave', 'internal_staging_verify', 'production_payments_allowed', 'run_staging_e2e', 'staging_e2e_config', 'staging_e2e_status', 'update_staging_e2e_config']
# Imported before main finished (``from app import staging_e2e_api`` first)? Then main's star
# import saw a half-loaded module; hand the names over now that they exist.
shop.__dict__.update({_n: globals()[_n] for _n in __all__})
