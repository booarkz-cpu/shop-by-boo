"""Real COSE keys/attestations/assertions: signatures, UV, origin and replay."""
import hashlib
import json
import secrets
from datetime import datetime, timedelta

import cbor2
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException, Response
from sqlalchemy import func, select
from starlette.requests import Request
from webauthn.helpers import bytes_to_base64url
from webauthn import base64url_to_bytes

from app import passkeys as keys
from app.models import AdminSession, AdminUser, FeatureFlag, WebAuthnChallenge, WebAuthnCredential
from app.security import decode_token, hash_password
from test_subscription_commerce import database

ORIGIN='https://admin.example.test'
PASSWORD='test-passkey-password'


def request(binding='', origin=ORIGIN):
    return Request({'type':'http','method':'POST','scheme':'https','path':'/api/admin/auth/passkeys/login/verify',
        'headers':[(b'origin',origin.encode()),(b'cookie',f'rw_passkey={binding}'.encode())],
        'client':('127.0.0.1',123)})


def binding(response):
    from http.cookies import SimpleCookie
    cookie=SimpleCookie();cookie.load(response.headers['set-cookie'])
    return cookie['rw_passkey'].value


async def admin(db,monkeypatch):
    monkeypatch.setattr(keys.settings,'webauthn_origin',ORIGIN)
    row=AdminUser(email='admin@example.test',role='admin',password_hash=hash_password(PASSWORD))
    db.add(row);db.add(FeatureFlag(key='passkeys',enabled=True));await db.commit();return row


def attestation(options, private, credential_id, origin=ORIGIN, flags=0x45):
    public=private.public_key().public_numbers()
    cose=cbor2.dumps({1:2,3:-7,-1:1,-2:public.x.to_bytes(32,'big'),-3:public.y.to_bytes(32,'big')})
    auth_data=hashlib.sha256(options['rp']['id'].encode()).digest()+bytes([flags])+bytes(4)+bytes(16)+len(credential_id).to_bytes(2,'big')+credential_id+cose
    client=json.dumps({'type':'webauthn.create','challenge':options['challenge'],'origin':origin,'crossOrigin':False}).encode()
    return {'id':bytes_to_base64url(credential_id),'rawId':bytes_to_base64url(credential_id),'type':'public-key',
        'response':{'attestationObject':bytes_to_base64url(cbor2.dumps({'fmt':'none','attStmt':{},'authData':auth_data})),
            'clientDataJSON':bytes_to_base64url(client)}}


def assertion(options, private, credential_id, handle, origin=ORIGIN, flags=5, count=1):
    client=json.dumps({'type':'webauthn.get','challenge':options['challenge'],'origin':origin,'crossOrigin':False}).encode()
    data=hashlib.sha256(options['rpId'].encode()).digest()+bytes([flags])+count.to_bytes(4,'big')
    signature=private.sign(data+hashlib.sha256(client).digest(),ec.ECDSA(hashes.SHA256()))
    return {'id':bytes_to_base64url(credential_id),'rawId':bytes_to_base64url(credential_id),'type':'public-key',
        'response':{'clientDataJSON':bytes_to_base64url(client),'authenticatorData':bytes_to_base64url(data),
            'signature':bytes_to_base64url(signature),'userHandle':handle}}


async def registered(db,monkeypatch):
    owner=await admin(db,monkeypatch);private=ec.generate_private_key(ec.SECP256R1());identifier=secrets.token_bytes(32)
    response=Response()
    result=await keys.registration_options(keys.RegisterIn(password=PASSWORD,name='Hardware'),request(),response,db,owner)
    payload=keys.VerifyIn(ticket=result['ticket'],credential=attestation(result['options'],private,identifier))
    await keys.registration_verify(payload,request(binding(response)),Response(),db,owner)
    return owner,private,identifier


@pytest.mark.asyncio
async def test_real_registration_and_login_issue_registered_mfa_session(database,monkeypatch):
    owner,private,identifier=await registered(database,monkeypatch)
    options_response=Response();options=await keys.login_options(request(),options_response,database)
    payload=keys.VerifyIn(ticket=options['ticket'],credential=assertion(options['options'],private,identifier,owner.passkey_user_handle))
    response=Response();result=await keys.login_verify(payload,request(binding(options_response)),response,database)
    assert result['auth_method']=='passkey' and result['email']==owner.email
    assert await database.scalar(select(func.count()).select_from(AdminSession))==1
    credential=await database.scalar(select(WebAuthnCredential))
    assert credential.sign_count==1 and credential.last_used_at
    token=next(x for x in response.headers.getlist('set-cookie') if x.startswith('rw_admin='))
    claims=decode_token(token.split(';')[0].split('=',1)[1]);assert claims['mfa'] is True and claims['jti']
    with pytest.raises(HTTPException) as error:await keys.login_verify(payload,request(binding(options_response)),Response(),database)
    assert error.value.status_code==401
    assert await database.scalar(select(func.count()).select_from(AdminSession))==1


@pytest.mark.asyncio
@pytest.mark.parametrize('failure',['origin','uv','signature','handle','disabled','cookie','expired','counter','challenge','unknown'])
async def test_assertion_attacks_create_no_session(database,monkeypatch,failure):
    owner,private,identifier=await registered(database,monkeypatch)
    response=Response();result=await keys.login_options(request(),response,database)
    data=assertion(result['options'],private,identifier,owner.passkey_user_handle,
        origin='https://evil.test' if failure=='origin' else ORIGIN,flags=1 if failure=='uv' else 5)
    if failure=='signature':data['response']['signature']=bytes_to_base64url(b'bad signature')
    if failure=='handle':data['response']['userHandle']=bytes_to_base64url(secrets.token_bytes(32))
    if failure=='disabled':owner.disabled=True
    if failure=='unknown':data['id']=bytes_to_base64url(secrets.token_bytes(32))
    if failure=='counter':(await database.scalar(select(WebAuthnCredential))).sign_count=1
    if failure=='expired':(await database.scalar(select(WebAuthnChallenge))).expires_at=datetime.utcnow()-timedelta(seconds=1)
    if failure=='challenge':data=assertion(result['options']|{'challenge':bytes_to_base64url(secrets.token_bytes(32))},private,identifier,owner.passkey_user_handle)
    await database.commit()
    with pytest.raises(HTTPException) as error:
        await keys.login_verify(keys.VerifyIn(ticket=result['ticket'],credential=data),
            request('wrong' if failure=='cookie' else binding(response)),Response(),database)
    assert error.value.status_code==401
    assert await database.scalar(select(func.count()).select_from(AdminSession))==0


@pytest.mark.asyncio
@pytest.mark.parametrize('failure',['password','otp','origin','uv','changed','duplicate'])
async def test_registration_rejects_untrusted_credentials(database,monkeypatch,failure):
    owner=await admin(database,monkeypatch)
    if failure=='otp':owner.mfa_enabled=True;await database.commit()
    if failure in {'password','otp'}:
        with pytest.raises(HTTPException):
            await keys.registration_options(keys.RegisterIn(password='wrong' if failure=='password' else PASSWORD),request(),Response(),database,owner)
        return
    private=ec.generate_private_key(ec.SECP256R1());identifier=secrets.token_bytes(32)
    for attempt in range(2 if failure=='duplicate' else 1):
        response=Response();result=await keys.registration_options(keys.RegisterIn(password=PASSWORD),request(),response,database,owner)
        data=attestation(result['options'],private,identifier,origin='https://evil.test' if failure=='origin' else ORIGIN,flags=0x41 if failure=='uv' else 0x45)
        if failure=='changed':owner.password_hash=hash_password('changed-password');await database.commit()
        payload=keys.VerifyIn(ticket=result['ticket'],credential=data)
        if failure=='duplicate' and attempt==0:
            await keys.registration_verify(payload,request(binding(response)),Response(),database,owner)
        else:
            with pytest.raises(HTTPException):await keys.registration_verify(payload,request(binding(response)),Response(),database,owner)
    assert await database.scalar(select(func.count()).select_from(WebAuthnCredential))==(1 if failure=='duplicate' else 0)


@pytest.mark.parametrize('origin',['','https://admin.test/','https://user@admin.test','https://admin.test?a=1','http://admin.test','https://admin.test:bad'])
def test_invalid_rp_configuration_fails_closed(monkeypatch,origin):
    monkeypatch.setattr(keys.settings,'webauthn_origin',origin)
    with pytest.raises(HTTPException) as error:keys.rp_config()
    assert error.value.status_code==503


def test_origin_header_is_required(monkeypatch):
    monkeypatch.setattr(keys.settings,'webauthn_origin',ORIGIN)
    with pytest.raises(HTTPException) as error:keys.ceremony_origin(request(origin='https://evil.test'))
    assert error.value.status_code==403


@pytest.mark.asyncio
async def test_cross_origin_assertion_rejected_even_with_valid_signature(database,monkeypatch):
    owner,private,identifier=await registered(database,monkeypatch)
    response=Response();result=await keys.login_options(request(),response,database)
    data=assertion(result['options'],private,identifier,owner.passkey_user_handle)
    client=json.loads(base64url_to_bytes(data['response']['clientDataJSON']));client['crossOrigin']=True;client['topOrigin']='https://evil.test'
    raw=json.dumps(client).encode();data['response']['clientDataJSON']=bytes_to_base64url(raw)
    signed=base64url_to_bytes(data['response']['authenticatorData'])+hashlib.sha256(raw).digest()
    data['response']['signature']=bytes_to_base64url(private.sign(signed,ec.ECDSA(hashes.SHA256())))
    with pytest.raises(HTTPException):await keys.login_verify(keys.VerifyIn(ticket=result['ticket'],credential=data),request(binding(response)),Response(),database)
    assert await database.scalar(select(func.count()).select_from(AdminSession))==0


@pytest.mark.asyncio
async def test_parallel_assertions_consume_challenge_once(database,monkeypatch):
    if database.bind.dialect.name!='postgresql':pytest.skip('Atomic replay rejection requires PostgreSQL')
    import asyncio
    from sqlalchemy.ext.asyncio import AsyncSession
    owner,private,identifier=await registered(database,monkeypatch)
    response=Response();result=await keys.login_options(request(),response,database)
    payload=keys.VerifyIn(ticket=result['ticket'],credential=assertion(result['options'],private,identifier,owner.passkey_user_handle))
    async def attempt():
        async with AsyncSession(database.bind,expire_on_commit=False) as db:
            try:return await keys.login_verify(payload,request(binding(response)),Response(),db)
            except HTTPException as error:return error.status_code
    outcomes=await asyncio.gather(attempt(),attempt())
    assert sum(isinstance(x,dict) for x in outcomes)==1 and 401 in outcomes
    assert await database.scalar(select(func.count()).select_from(AdminSession))==1


@pytest.mark.asyncio
async def test_two_challenges_same_counter_cannot_both_login(database,monkeypatch):
    if database.bind.dialect.name!='postgresql':pytest.skip('Counter serialization requires PostgreSQL')
    import asyncio
    from sqlalchemy.ext.asyncio import AsyncSession
    owner,private,identifier=await registered(database,monkeypatch)
    attempts=[]
    for _ in range(2):
        response=Response();result=await keys.login_options(request(),response,database)
        attempts.append((keys.VerifyIn(ticket=result['ticket'],credential=assertion(result['options'],private,identifier,owner.passkey_user_handle)),binding(response)))
    async def attempt(payload,cookie):
        async with AsyncSession(database.bind,expire_on_commit=False) as db:
            try:return await keys.login_verify(payload,request(cookie),Response(),db)
            except HTTPException as error:return error.status_code
    outcomes=await asyncio.gather(*(attempt(*x) for x in attempts))
    assert sum(isinstance(x,dict) for x in outcomes)==1 and 401 in outcomes
    assert await database.scalar(select(func.count()).select_from(AdminSession))==1


@pytest.mark.asyncio
async def test_postgres_migration_cycle_and_identity_downgrade_guard(database,monkeypatch):
    if database.bind.dialect.name!='postgresql':pytest.skip('Requires PostgreSQL')
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    spec=importlib.util.spec_from_file_location('passkey_migration',Path('services/backend/alembic/versions/0053_admin_passkeys.py'))
    migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
    await database.commit()
    async with database.bind.begin() as connection:
        def cycle(conn):
            with Operations.context(MigrationContext.configure(conn)):
                migration.downgrade();migration.upgrade()
        await connection.run_sync(cycle)
    owner,private,identifier=await registered(database,monkeypatch)
    handle=owner.passkey_user_handle
    with pytest.raises(RuntimeError,match='opaque identities'):
        async with database.bind.begin() as connection:
            def guarded(conn):
                with Operations.context(MigrationContext.configure(conn)):migration.downgrade()
            await connection.run_sync(guarded)
    assert (await database.get(AdminUser,owner.id)).passkey_user_handle==handle


@pytest.mark.asyncio
async def test_disabled_feature_blocks_existing_key_login(database,monkeypatch):
    owner,private,identifier=await registered(database,monkeypatch)
    flag=await database.scalar(select(FeatureFlag).where(FeatureFlag.key=='passkeys'));flag.enabled=False;await database.commit()
    with pytest.raises(HTTPException) as error:await keys.login_options(request(),Response(),database)
    assert error.value.status_code==503
    assert await database.scalar(select(func.count()).select_from(AdminSession))==0


@pytest.mark.asyncio
async def test_unsigned_32_bit_signature_counter_fits_postgres(database,monkeypatch):
    owner,private,identifier=await registered(database,monkeypatch)
    response=Response();result=await keys.login_options(request(),response,database)
    data=assertion(result['options'],private,identifier,owner.passkey_user_handle,count=2**32-1)
    await keys.login_verify(keys.VerifyIn(ticket=result['ticket'],credential=data),request(binding(response)),Response(),database)
    assert (await database.scalar(select(WebAuthnCredential))).sign_count==2**32-1
