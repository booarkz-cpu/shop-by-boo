"""Behavioral regression tests for the consolidated security audit."""
import importlib
import json
import time
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock
import pytest
from fastapi import HTTPException
from starlette.requests import Request

@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'services' / 'backend'))
    return NS(**{name: importlib.import_module('app.' + name) for name in
                 ('config','runtime_security','mobile_auth','payments','restore_approval','main')})

def native(headers=None):
    return Request({'type':'http','method':'POST','scheme':'https','path':'/api/auth/login',
                    'server':('api.example.com',443), 'headers':[(k.lower().encode(),v.encode()) for k,v in
                    {'host':'api.example.com','x-shop-client':'android-user',**(headers or {})}.items()]})

@pytest.mark.parametrize('changes,match', [
    ({'mobile_client_key':'b7e1c4a09f6d42e8a1c35b77d0e94f12'},'public default'),
    ({'mobile_require_proof':True,'mobile_client_key':'x'*40},'Legacy'),
    ({'redis_password':''},'Redis requires'),
    ({'support_pro_url':'https://support.example.com','support_pro_sso_secret':'change-me-support-sso'},'Support Pro'),
    ({'rollypay_api_key':'key','rollypay_signing_secret':''},'RollyPay'),
    ({'platega_merchant_id':'merchant','platega_secret':''},'Platega'),
    ({'stripe_secret_key':'key','stripe_webhook_secret':''},'Stripe'),
    ({'paypal_client_id':'id','paypal_client_secret':'secret','paypal_webhook_id':''},'PayPal'),
    ({'yookassa_shop_id':'shop','yookassa_secret_key':'secret','yookassa_webhook_ip_allowlist':''},'YooKassa'),
    ({'admin_cors_origins':'https://*.example.com'},'exact'),
    ({'admin_cors_origins':'https://evil.example.com'},'configured frontend'),
    ({'trusted_proxy_cidrs':'0.0.0.0/0'},'every address'),
])
def test_production_configuration_rejects_unsafe_values(modules, changes, match):
    settings = modules.config.settings.model_copy(update={'app_env':'production','redis_password':'a'*64,
        'redis_url':'redis://redis:6379/0','mobile_require_proof':False,'mobile_client_key':'',
        'admin_cors_origins':'','cabinet_cors_origins':'','trusted_proxy_cidrs':'172.30.84.2/32',**changes})
    with pytest.raises(ValueError, match=match):
        settings.validate_security()


def test_redis_credentials_and_explicit_proxy(modules):
    security = modules.runtime_security
    assert security.redis_connection_kwargs('redis://redis/0','a@b:') == {'password':'a@b:'}
    assert security.redis_connection_kwargs('redis://:a%40b%3A@redis/0','a@b:') == {}
    with pytest.raises(ValueError): security.redis_connection_kwargs('redis://:wrong@redis/0','correct')
    assert security.trusted_proxy('172.30.84.2','172.30.84.2/32')
    for peer in ('172.30.84.4','10.0.0.2','127.0.0.1','::1','fd00::1'):
        assert not security.trusted_proxy(peer,'172.30.84.2/32')

@pytest.mark.asyncio
async def test_redis_outage_uses_bounded_local_limits(modules):
    sec = modules.runtime_security
    sec._LOCAL.clear()
    redis = NS(eval=AsyncMock(side_effect=ConnectionError))
    assert [await sec.rate_allowed(redis,'user1',2,60) for _ in range(3)] == [True,True,False]
    assert await sec.rate_allowed(redis,'user2',2,60)
    sec._LOCAL.clear()

@pytest.mark.asyncio
async def test_pkce_code_is_bound_one_use_and_browser_inaccessible(modules, monkeypatch):
    auth = modules.mobile_auth
    monkeypatch.setattr(modules.config.settings,'app_env','test')
    verifier = 'a'*43
    request = native({'x-shop-code-challenge':auth.pkce_challenge(verifier)})
    body = auth.session_body(request,'real-session',{'id':7})
    assert 'access_token' not in body
    redis = NS(set=AsyncMock(side_effect=[True,False]))
    with pytest.raises(HTTPException) as exc: await auth.exchange_mobile_code(request,body['authorization_code'],'b'*43,redis)
    assert exc.value.status_code == 401
    redis.set.assert_not_awaited()
    assert (await auth.exchange_mobile_code(request,body['authorization_code'],verifier,redis))['access_token'] == 'real-session'
    with pytest.raises(HTTPException,match='already used'): await auth.exchange_mobile_code(request,body['authorization_code'],verifier,redis)
    for headers in ({'origin':'https://admin.example.com'},{'sec-fetch-site':'none'}):
        with pytest.raises(HTTPException) as exc: auth.session_body(native(headers),'secret',{})
        assert exc.value.status_code == 403
    monkeypatch.setattr(auth.time,'time',lambda: 99999999999)
    with pytest.raises(HTTPException,match='expired'): await auth.exchange_mobile_code(request,body['authorization_code'],verifier,redis)


def test_gateway_auth_fails_closed_and_platega_uses_documented_protocol(modules, monkeypatch):
    pay = modules.payments
    monkeypatch.setattr(pay.settings,'rollypay_signing_secret','')
    with pytest.raises(pay.SignatureVerificationError):
        pay.RollyPayProvider().verify_webhook({'X-Timestamp':str(int(time.time())),'X-Signature':'forged'},b'{}')
    monkeypatch.setattr(pay.settings,'platega_merchant_id','merchant')
    monkeypatch.setattr(pay.settings,'platega_secret','secret')
    assert pay.PlategaProvider().verify_webhook({'X-MerchantId':'merchant','X-Secret':'secret'},b'{"id":"event"}')['id']=='event'
    monkeypatch.setattr(pay.settings,'platega_secret','')
    with pytest.raises(pay.SignatureVerificationError):
        pay.PlategaProvider().verify_webhook({'x-merchantid':'merchant','x-secret':''},b'{}')

@pytest.mark.asyncio
@pytest.mark.parametrize('provider',['stripe','paypal'])
async def test_duplicate_events_never_enter_payment_processing(modules, monkeypatch, provider):
    shop=modules.main
    event={'id':'event-1'}
    if provider=='stripe': monkeypatch.setattr(shop.StripePlatform,'verify_webhook',lambda *args:event)
    else: monkeypatch.setattr(shop.PayPalPlatform,'verify_webhook',AsyncMock(return_value=event))
    claim=AsyncMock(return_value=False)
    monkeypatch.setattr(shop,'register_provider_event',claim)
    db=NS(rollback=AsyncMock(),execute=AsyncMock())
    result=await getattr(shop,provider+'_webhook')(NS(body=AsyncMock(return_value=b'{}'),headers={}),db)
    assert result['duplicate']
    claim.assert_awaited_once_with(db,provider,'event-1',None)
    db.execute.assert_not_awaited()

@pytest.mark.asyncio
async def test_restore_requires_independent_mfa_approval_and_consumes_once(modules, monkeypatch, tmp_path):
    restore=modules.restore_approval
    monkeypatch.setattr(restore.settings,'backups_dir',str(tmp_path))
    monkeypatch.setattr(restore,'verify_totp',lambda admin,otp:otp=='123456')
    admin=NS(id=1,role='admin',disabled=False,mfa_enabled=True,email='a@example.com')
    second=NS(id=2,role='admin',disabled=False,mfa_enabled=True,email='b@example.com')
    job=NS(id=3,filename='backup.tgz',sha256='checksum')
    rows=[]
    db=NS(add=lambda row:rows.append(row),commit=AsyncMock())
    result=await restore.request_approval(db,job,admin,'123456')
    row=rows[0]
    db.execute=AsyncMock(return_value=Mock(scalar_one_or_none=lambda:row))
    db.get=AsyncMock(side_effect=lambda model,pk:admin if pk==1 else second)
    async def use(actor,approve=False):
        return await restore.use_approval(db,job,actor,'123456',result['approval_id'],approve=approve)
    with pytest.raises(HTTPException): await use(admin,True)
    with pytest.raises(HTTPException): await use(admin)
    await use(second,True)
    await use(admin)
    with pytest.raises(HTTPException): await use(admin)
    assert json.loads(row.value)['consumed']
    assert len((tmp_path/'restore-audit.jsonl').read_text().splitlines())==3
    admin.mfa_enabled=False
    with pytest.raises(HTTPException): restore.require_restore_admin(admin,'123456')

@pytest.mark.asyncio
async def test_cors_is_split_and_token_exchange_has_no_cors(modules):
    import httpx
    from fastapi import FastAPI
    app=FastAPI()
    @app.get('/{path:path}')
    async def ok(path): return {'ok':True}
    config=modules.config.settings.model_copy(update={'app_env':'test','admin_cors_origins':'https://admin.example.com','cabinet_cors_origins':'https://cabinet.example.com'})
    wrapped=modules.runtime_security.ScopedCORSMiddleware(app,config)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=wrapped),base_url='https://api.example.com') as client:
        for path,origin,allowed in [('/api/admin/users','https://admin.example.com',True),('/api/admin/users','https://cabinet.example.com',False),('/api/auth/mobile/token','https://admin.example.com',False)]:
            response=await client.get(path,headers={'Origin':origin})
            assert ('access-control-allow-origin' in response.headers)==allowed


def test_example_optional_telegram_id_does_not_block_startup(modules):
    config = modules.config.Settings(_env_file=None, APP_ENV="test", ADMIN_TELEGRAM_ID="")
    assert config.admin_telegram_id == 0
