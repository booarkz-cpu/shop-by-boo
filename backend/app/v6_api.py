from __future__ import annotations
import json, uuid
from datetime import datetime, timedelta
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession
from .db import get_db
from .models import (AppSetting, AuditLog, User, Subscription, Payment, UserDevice, NodeAgent,
                     AgentAction, SecurityIncident, FraudSignal, FeatureFlag, OutboundWebhook,
                     ShopApiKey, AutomationRule, Campaign, StatusComponent, PromoCode, ReferralLedger)
from .security import require_permission

router=APIRouter()

def _loads(v, default):
    try: return json.loads(v) if v else default
    except Exception: return default
async def setting(db,key,default):
    r=await db.get(AppSetting,key); return _loads(r.value,default) if r else default
async def save_setting(db,key,value):
    r=await db.get(AppSetting,key); raw=json.dumps(value,ensure_ascii=False,default=str)
    if r:r.value=raw
    else:db.add(AppSetting(key=key,value=raw))
async def event(db,kind,actor='system',target=None,payload=None):
    db.add(AuditLog(action=f'event:{kind}',actor=actor,target=target,details=json.dumps(payload or {},ensure_ascii=False,default=str),request_id=str(uuid.uuid4())))

DEFAULTS={
 'orchestrator':{'auto_heal':False,'drain_threshold':90,'recover_threshold':70,'stale_seconds':180,'approval_required':True},
 'capacity':{'warning_percent':75,'critical_percent':90,'forecast_days':14},
 'tenancy':{'enabled':False,'mode':'single-tenant','workspaces':[{'id':'default','name':'VPN Shop by Corgi Lusi','domain':'','currency':'EUR'}]},
 'retention':{'enabled':True,'expiry_days':[7,3,1],'winback_days':[1,7,30]},
 'status_page':{'enabled':True,'title':'VPN Shop by Corgi Lusi Status','history_days':90},
 'approval':{'refund_threshold':500,'node_delete':True,'provider_change':True,'data_export':True},
 'localization':{'languages':['ru','en','de','uk'],'currencies':['EUR','USD','GBP','CHF'],'default_currency':'EUR'},
}

def checked_config(section, incoming):
    defaults = DEFAULTS[section]
    value = {**defaults, **incoming}
    for key, default in defaults.items():
        candidate = value[key]
        if type(candidate) is not type(default):
            raise HTTPException(422, f'{section}.{key}: invalid type')
        if isinstance(candidate, str) and len(candidate) > 255:
            raise HTTPException(422, f'{section}.{key}: too long')
        if isinstance(candidate, list) and len(candidate) > 100:
            raise HTTPException(422, f'{section}.{key}: too many items')
    bounds = {'stale_seconds': (15,86400), 'forecast_days': (1,365), 'history_days': (1,365),
              'drain_threshold': (1,100), 'recover_threshold': (0,99),
              'warning_percent': (0,99), 'critical_percent': (1,100), 'refund_threshold': (0,1000000)}
    for key, (low, high) in bounds.items():
        if key in defaults and not low <= value[key] <= high:
            raise HTTPException(422, f'{section}.{key}: out of range')
    for low, high in [('warning_percent','critical_percent'), ('recover_threshold','drain_threshold')]:
        if low in defaults and value[low] >= value[high]:
            raise HTTPException(422, f'{low} must be less than {high}')
    if section == 'retention':
        for key in ('expiry_days','winback_days'):
            if any(type(day) is not int or not 1 <= day <= 365 for day in value[key]):
                raise HTTPException(422, f'{key}: invalid days')
    return value

class ConfigIn(BaseModel): value: dict
class ProvisionIn(BaseModel): provider:str='custom'; region:str; template:str='standard'; name:str; dry_run:bool=True
class IncidentIn(BaseModel): title:str; severity:str=Field('medium',pattern='^(low|medium|high|critical)$'); details:str=''
class TenantIn(BaseModel): name:str; domain:str=''; currency:str='EUR'; branding:dict={}

@router.get('/api/admin/v6/command-center')
async def command_center(db:AsyncSession=Depends(get_db),admin=Depends(require_permission('read'))):
    now=datetime.utcnow(); day=now-timedelta(days=1); month=now-timedelta(days=30)
    users=int(await db.scalar(select(func.count()).select_from(User)) or 0)
    active=int(await db.scalar(select(func.count()).select_from(Subscription).where(Subscription.expires_at>now)) or 0)
    revenue=await db.scalar(select(func.coalesce(func.sum(Payment.amount),0)).where(Payment.status.in_(['paid','fulfilled']),Payment.created_at>=month))
    failed=int(await db.scalar(select(func.count()).select_from(Payment).where(Payment.status=='failed',Payment.created_at>=day)) or 0)
    incidents=int(await db.scalar(select(func.count()).select_from(SecurityIncident).where(SecurityIncident.status.in_(['open','investigating']))) or 0)
    fraud=int(await db.scalar(select(func.count()).select_from(FraudSignal).where(FraudSignal.status.in_(['new','open']))) or 0)
    agents=(await db.execute(select(NodeAgent).order_by(NodeAgent.name))).scalars().all()
    stale=DEFAULTS['orchestrator']['stale_seconds']; cfg=await setting(db,'v6.orchestrator',DEFAULTS['orchestrator']); stale=int(cfg.get('stale_seconds',stale))
    nodes=[]
    for a in agents:
        age=(now-a.last_seen_at).total_seconds() if a.last_seen_at else 10**9
        nodes.append({'id':a.id,'name':a.name,'online':a.enabled and age<=stale,'cpu':a.cpu,'mem':a.mem,'disk':a.disk,'xray_ok':a.xray_ok,'last_seen_at':a.last_seen_at})
    attention=[]
    if failed: attention.append({'severity':'high','kind':'billing','text':f'{failed} failed payments in 24h'})
    if incidents: attention.append({'severity':'critical','kind':'security','text':f'{incidents} open security incidents'})
    if fraud: attention.append({'severity':'high','kind':'fraud','text':f'{fraud} fraud signals require review'})
    offline=sum(1 for n in nodes if not n['online'])
    if offline: attention.append({'severity':'critical','kind':'nodes','text':f'{offline} node agents offline/stale'})
    return {'kpis':{'users':users,'active_subscriptions':active,'revenue_30d':str(revenue or Decimal('0')),'failed_payments_24h':failed,'open_incidents':incidents,'fraud_signals':fraud},'nodes':nodes,'attention':attention,'checked_at':now}

@router.get('/api/admin/v6/config/{section}')
async def get_config(section:str,db:AsyncSession=Depends(get_db),admin=Depends(require_permission('read'))):
    if section not in DEFAULTS: raise HTTPException(404,'Unknown section')
    return await setting(db,f'v6.{section}',DEFAULTS[section])

@router.put('/api/admin/v6/config/{section}')
async def put_config(section:str,p:ConfigIn,db:AsyncSession=Depends(get_db),admin=Depends(require_permission('security.manage'))):
    if section not in DEFAULTS: raise HTTPException(404,'Unknown section')
    value=checked_config(section,p.value); await save_setting(db,f'v6.{section}',value); await event(db,'config.changed',str(admin.id),section,value); await db.commit(); return value

@router.get('/api/admin/v6/capacity')
async def capacity(db:AsyncSession=Depends(get_db),admin=Depends(require_permission('read'))):
    cfg=await setting(db,'v6.capacity',DEFAULTS['capacity']); agents=(await db.execute(select(NodeAgent))).scalars().all(); out=[]
    for a in agents:
        def pct(x):
            try:return float(str(x or '0').replace('%','').split()[0])
            except:return 0.0
        load=max(pct(a.cpu),pct(a.mem),pct(a.disk)); state='critical' if load>=cfg['critical_percent'] else 'warning' if load>=cfg['warning_percent'] else 'healthy'
        out.append({'id':a.id,'name':a.name,'load':load,'state':state,'forecast_days':0 if load>=cfg['critical_percent'] else max(1,int((cfg['critical_percent']-load)/max(load*.03,1)))})
    return {'config':cfg,'nodes':out,'recommendation':{'add_nodes':sum(1 for x in out if x['state']=='critical'),'note':'Прогноз строится по текущей телеметрии агентов; для прогноза по времени подключите исторические метрики.'}}

@router.post('/api/admin/v6/orchestrator/evaluate')
async def orchestrate(db:AsyncSession=Depends(get_db),admin=Depends(require_permission('provision_nodes'))):
    cfg=await setting(db,'v6.orchestrator',DEFAULTS['orchestrator']); now=datetime.utcnow(); agents=(await db.execute(select(NodeAgent))).scalars().all(); actions=[]
    for a in agents:
        stale=not a.last_seen_at or (now-a.last_seen_at).total_seconds()>cfg['stale_seconds'] or a.xray_ok is False
        if stale:
            kind='drain'; status='pending_approval' if cfg.get('approval_required',True) or not cfg.get('auto_heal') else 'queued'
            if not (await db.scalar(select(func.count()).select_from(AgentAction).where(AgentAction.agent_id==a.id,AgentAction.kind==kind,AgentAction.status.in_(['queued','pending_approval'])))):
                ac=AgentAction(agent_id=a.id,kind=kind,payload={'reason':'health_check_failed','auto_heal':cfg.get('auto_heal',False)},status=status);db.add(ac);actions.append({'agent':a.name,'action':kind,'status':status})
    await event(db,'orchestrator.evaluated',str(admin.id),payload={'actions':actions});await db.commit();return {'actions':actions,'config':cfg}

@router.post('/api/admin/v6/provision')
async def provision(p:ProvisionIn,db:AsyncSession=Depends(get_db),admin=Depends(require_permission('provision_nodes'))):
    intent={'id':str(uuid.uuid4()),**p.model_dump(),'status':'planned' if p.dry_run else 'pending_provider_credentials','created_at':datetime.utcnow().isoformat()}
    intents=await setting(db,'v6.provision_intents',[]);intents=[intent,*intents][:200];await save_setting(db,'v6.provision_intents',intents);await event(db,'node.provision.requested',str(admin.id),p.name,intent);await db.commit();return intent

@router.get('/api/admin/v6/commercial')
async def commercial(db:AsyncSession=Depends(get_db),admin=Depends(require_permission('read'))):
    now=datetime.utcnow();m=now-timedelta(days=30);paid=(await db.execute(select(Payment).where(Payment.status.in_(['paid','fulfilled']),Payment.created_at>=m))).scalars().all(); revenue=sum((Decimal(str(x.amount)) for x in paid),Decimal('0')); users=int(await db.scalar(select(func.count()).select_from(User) ) or 0); active=int(await db.scalar(select(func.count()).select_from(Subscription).where(Subscription.expires_at>now)) or 0); refs=await db.scalar(select(func.coalesce(func.sum(ReferralLedger.amount),0)))
    return {'mrr_proxy':str(revenue),'arpu_30d':str((revenue/active).quantize(Decimal('.01')) if active else 0),'users':users,'active':active,'referral_ledger':str(refs or 0),'paid_transactions':len(paid),'coupons':int(await db.scalar(select(func.count()).select_from(PromoCode)) or 0),'campaigns':int(await db.scalar(select(func.count()).select_from(Campaign)) or 0)}

@router.get('/api/admin/v6/integrations')
async def integrations(db:AsyncSession=Depends(get_db),admin=Depends(require_permission('read'))):
    keys=(await db.execute(select(ShopApiKey).order_by(desc(ShopApiKey.id)).limit(100))).scalars().all(); hooks=(await db.execute(select(OutboundWebhook).order_by(desc(OutboundWebhook.id)).limit(100))).scalars().all()
    return {'api_keys':[{'id':x.id,'name':x.name,'prefix':x.prefix,'scopes':x.scopes,'enabled':x.enabled,'last_used_at':x.last_used_at} for x in keys],'webhooks':[{'id':x.id,'url':x.url,'events':x.events,'enabled':x.enabled,'last_status':x.last_status,'last_error':x.last_error} for x in hooks]}

@router.get('/api/admin/v6/events')
async def events(db:AsyncSession=Depends(get_db),admin=Depends(require_permission('read'))):
    rows=(await db.execute(select(AuditLog).where(AuditLog.action.like('event:%')).order_by(desc(AuditLog.id)).limit(200))).scalars().all();return [{'id':x.id,'event':x.action[6:],'actor':x.actor,'target':x.target,'payload':_loads(x.details,{}),'created_at':x.created_at,'request_id':x.request_id} for x in rows]

@router.get('/api/admin/v6/security-center')
async def security_center(db:AsyncSession=Depends(get_db),admin=Depends(require_permission('read'))):
    incidents=(await db.execute(select(SecurityIncident).order_by(desc(SecurityIncident.id)).limit(50))).scalars().all(); fraud=(await db.execute(select(FraudSignal).order_by(desc(FraudSignal.id)).limit(50))).scalars().all();return {'incidents':[{'id':x.id,'kind':x.kind,'severity':x.severity,'status':x.status,'created_at':x.created_at} for x in incidents],'fraud':[{'id':x.id,'kind':x.kind,'score':x.score,'status':x.status,'user_id':x.user_id,'ip':x.ip} for x in fraud],'approval':await setting(db,'v6.approval',DEFAULTS['approval'])}

@router.get('/api/public/v6/status')
async def public_status(db:AsyncSession=Depends(get_db)):
    cfg=await setting(db,'v6.status_page',DEFAULTS['status_page']); comps=(await db.execute(select(StatusComponent))).scalars().all(); return {'title':cfg['title'],'status':'operational' if all(getattr(x,'status','operational') in ['operational','healthy'] for x in comps) else 'degraded','components':[{'name':x.name,'status':x.status,'message':getattr(x,'message',None)} for x in comps],'updated_at':datetime.utcnow()}

@router.get('/api/admin/v6/intelligence')
async def intelligence(db:AsyncSession=Depends(get_db),admin=Depends(require_permission('read'))):
    cc=await command_center(db,admin); cap=await capacity(db,admin); rec=[]
    for a in cc['attention']: rec.append({'priority':a['severity'],'title':a['text'],'action':'investigate','source':a['kind']})
    for n in cap['nodes']:
        if n['state']!='healthy':rec.append({'priority':'high' if n['state']=='critical' else 'medium','title':f"{n['name']}: capacity {n['load']}%",'action':'capacity_plan','source':'capacity'})
    return {'recommendations':rec[:30],'generated_at':datetime.utcnow(),'mode':'deterministic-evidence-based'}
