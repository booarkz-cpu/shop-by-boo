"""Recovery ownership, expiry, revocation, queue retries and PG one-use races."""
import asyncio,hashlib
from datetime import datetime,timedelta
import pytest
from fastapi import HTTPException,Response
from sqlalchemy import select,func
from sqlalchemy.ext.asyncio import AsyncSession
from app import account_actions as actions
from app import main as shop
from app.models import User,AccountAction,AccountMail,UserSession,AuthExchangeCode
from app.security import hash_password,verify_password,decrypt_secret
from test_subscription_commerce import database,request

async def issue(db,monkeypatch,purpose='password_reset'):
    monkeypatch.setattr(actions.settings,'smtp_host','smtp.example.test')
    monkeypatch.setattr(actions.settings,'smtp_from','shop@example.test')
    monkeypatch.setattr(actions.settings,'cabinet_url','https://cabinet.example.test')
    user=await db.get(User,1);user.email='owner@example.test';user.email_password_hash=hash_password('old-password')
    await db.commit();await actions.enqueue(db,user,purpose);await db.commit()
    mail=await db.scalar(select(AccountMail).order_by(AccountMail.id.desc()))
    return user,mail,decrypt_secret(mail.token_encrypted)

@pytest.mark.asyncio
async def test_reset_only_once_revokes_sessions_and_exchange_codes(database,monkeypatch):
    user,mail,token=await issue(database,monkeypatch)
    database.add_all([UserSession(user_id=1,jti_hash='s'*64,expires_at=datetime.utcnow()+timedelta(hours=1)),
        AuthExchangeCode(user_id=1,code_hash='e'*64,expires_at=datetime.utcnow()+timedelta(hours=1))]);await database.commit()
    row=await database.get(AccountAction,mail.action_id)
    assert row.token_hash==hashlib.sha256(token.encode()).hexdigest() and token not in mail.token_encrypted
    await actions.confirm_reset(actions.ResetIn(token=token,password='new-password'),Response(),database)
    assert verify_password('new-password',user.email_password_hash)
    assert (await database.scalar(select(UserSession))).revoked_at
    assert (await database.scalar(select(AuthExchangeCode))).used_at
    with pytest.raises(HTTPException):await actions.confirm_reset(actions.ResetIn(token=token,password='evil-password'),Response(),database)
    assert verify_password('new-password',user.email_password_hash)

@pytest.mark.asyncio
@pytest.mark.parametrize('change',['expired','email','deleted','password'])
async def test_reset_rejects_stale_owner_state(database,monkeypatch,change):
    user,mail,token=await issue(database,monkeypatch)
    row=await database.get(AccountAction,mail.action_id)
    if change=='expired':row.expires_at=datetime.utcnow()-timedelta(seconds=1)
    elif change=='email':user.email='different@example.test'
    elif change=='deleted':user.deleted_at=datetime.utcnow()
    else:user.email_password_hash=hash_password('independently-changed')
    await database.commit()
    with pytest.raises(HTTPException) as error:await actions.confirm_reset(actions.ResetIn(token=token,password='evil-password'),Response(),database)
    assert error.value.status_code==400

@pytest.mark.asyncio
async def test_reset_cannot_assign_password_to_oauth_only_account(database,monkeypatch):
    user,mail,token=await issue(database,monkeypatch)
    user.email_password_hash=None;await database.commit()
    await database.delete(mail);await database.delete(await database.get(AccountAction,mail.action_id));await database.commit()
    oauth=await actions.request_reset(actions.EmailIn(email=user.email),request(),Response(),database)
    missing=await actions.request_reset(actions.EmailIn(email='missing@example.test'),request(),Response(),database)
    assert oauth==missing and await database.scalar(select(func.count()).select_from(AccountAction))==0

@pytest.mark.asyncio
async def test_verify_does_not_change_password_or_sign_in(database,monkeypatch):
    user,mail,token=await issue(database,monkeypatch,'email_verification')
    with pytest.raises(HTTPException):await actions.confirm_reset(actions.ResetIn(token=token,password='new-password'),Response(),database)
    await actions.confirm_verification(actions.TokenIn(token=token),Response(),database)
    assert user.email_verified_at and verify_password('old-password',user.email_password_hash)
    assert await database.scalar(select(func.count()).select_from(UserSession))==0
    with pytest.raises(HTTPException):await actions.confirm_verification(actions.TokenIn(token=token),Response(),database)

@pytest.mark.asyncio
async def test_mail_retry_uses_same_token_then_erases_ciphertext(database,monkeypatch):
    user,mail,token=await issue(database,monkeypatch);seen=[]
    def send(email,purpose,raw):
        seen.append((email,purpose,raw))
        if len(seen)==1:raise RuntimeError('secret token should never be stored in error')
    monkeypatch.setattr(actions,'send_mail',send)
    await actions.deliver_one(database,mail.id)
    assert mail.status=='queued' and mail.error=='RuntimeError' and mail.token_encrypted
    mail.next_retry_at=datetime.utcnow()-timedelta(seconds=1);await database.commit()
    await actions.deliver_one(database,mail.id)
    assert mail.status=='sent' and mail.token_encrypted=='' and len(seen)==2 and seen[0]==seen[1]
    assert seen[0][2]==token

@pytest.mark.asyncio
async def test_deleted_owner_mail_is_cancelled(database,monkeypatch):
    user,mail,token=await issue(database,monkeypatch)
    user.deleted_at=datetime.utcnow();await database.commit()
    def forbidden(*args):raise AssertionError('deleted account must not receive mail')
    monkeypatch.setattr(actions,'send_mail',forbidden)
    await actions.deliver_one(database,mail.id)
    assert mail.status=='cancelled' and not mail.token_encrypted

@pytest.mark.asyncio
async def test_parallel_reset_exactly_once_on_postgres(database,monkeypatch):
    if database.bind.dialect.name!='postgresql':pytest.skip('Requires real PostgreSQL row locks')
    user,mail,token=await issue(database,monkeypatch);await database.commit()
    async def reset(password):
        async with AsyncSession(database.bind,expire_on_commit=False) as db:
            try:
                await actions.confirm_reset(actions.ResetIn(token=token,password=password),Response(),db)
                return True
            except HTTPException:
                await db.rollback();return False
    results=await asyncio.gather(reset('first-password'),reset('second-password'))
    assert results.count(True)==1


@pytest.mark.asyncio
async def test_reset_request_does_not_tell_whether_the_account_exists(database,monkeypatch):
    """Master prompt v6 (REQ-SHOP-0016): the same answer for a known address, an unknown one and an account without a password."""
    monkeypatch.setattr(actions.settings,'smtp_host','smtp.example.test')
    monkeypatch.setattr(actions.settings,'smtp_from','shop@example.test')
    monkeypatch.setattr(actions.settings,'cabinet_url','https://cabinet.example.test')
    user=await database.get(User,1);user.email='owner@example.test';user.email_password_hash=hash_password('old-password')
    await database.commit()
    before=await database.scalar(select(func.count()).select_from(AccountAction))
    answers=[]
    for email in ('owner@example.test','nobody@example.test'):
        response=Response()
        body=await actions.request_reset(actions.EmailIn(email=email),request(),response,database)
        answers.append((body,response.headers.get('cache-control')))
    assert answers[0]==answers[1] and answers[0][0]['ok'] is True and answers[0][1]=='private, no-store'
    # A reset is prepared only for the address that has a password; the unknown address gets none.
    assert await database.scalar(select(func.count()).select_from(AccountAction))==before+1
    # Asked again at once: no second letter (two-minute limit), and still the same answer.
    response=Response()
    assert (await actions.request_reset(actions.EmailIn(email='owner@example.test'),request(),response,database),response.headers.get('cache-control'))==answers[0]
    assert await database.scalar(select(func.count()).select_from(AccountAction))==before+1
