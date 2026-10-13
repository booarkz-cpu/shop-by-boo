from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app import main as shop
from app.models import (
    AccountAction,
    AccountMergeAlias,
    CustomerPasskey,
    CustomerPasskeyChallenge,
    PartnerWithdrawal,
    Reseller,
    Subscription,
    User,
)
from test_subscription_commerce import database, request


@pytest.mark.asyncio
@pytest.mark.parametrize('obligation', ['balance', 'debt', 'pending', 'approved'])
async def test_partner_obligations_block_account_anonymization(database, obligation):
    partner=Reseller(owner_user_id=1,name='Owner',slug='owner',api_key_hash='original',
        balance=10 if obligation=='balance' else -10 if obligation=='debt' else 0)
    database.add(partner);await database.flush()
    if obligation in {'pending','approved'}:
        database.add(PartnerWithdrawal(reseller_id=partner.id,amount=10,currency='RUB',
            destination='Bank',idempotency_key='payout',status=obligation))
    await database.commit()
    with pytest.raises(HTTPException) as error:await shop.privacy_delete(request(),database)
    assert error.value.status_code==409 and 'партнёрские' in error.value.detail
    assert (await database.get(User,1)).deleted_at is None and partner.enabled


@pytest.mark.asyncio
async def test_account_deletion_erases_customer_keys_and_disables_partner(database,monkeypatch):
    if database.bind.dialect.name!='postgresql':pytest.skip('Privacy device SQL uses PostgreSQL')
    user=await database.get(User,1);user.passkey_user_handle='private-handle'
    sub=await database.get(Subscription,1);sub.expires_at=datetime.utcnow()-timedelta(days=1)
    partner=Reseller(owner_user_id=1,name='Owner',slug='owner',api_key_hash='original',balance=0)
    database.add_all([partner,AccountMergeAlias(source_user_id=2,target_user_id=1,email='old@example.test',
        email_password_hash='private-hash',referral_code='OLD-CODE',merged_at=datetime.utcnow()),
        AccountAction(user_id=2,token_hash='a'*64,purpose='password_reset',email='old@example.test',
            expires_at=datetime.utcnow()+timedelta(minutes=5)),
        CustomerPasskey(user_id=1,credential_id='private',public_key='key',name='Device'),
        CustomerPasskeyChallenge(user_id=1,ticket_hash='ticket',binding_hash='binding',purpose='register',
            challenge='challenge',context={},expires_at=datetime.utcnow()+timedelta(minutes=5))])
    await database.commit()
    class Remote:
        async def disable_user(self,uuid):pass
    monkeypatch.setattr(shop,'RemnawaveClient',Remote)
    assert (await shop.privacy_delete(request(),database))['anonymized']
    assert user.passkey_user_handle is None and not partner.enabled and partner.api_key_hash!='original'
    for model in (CustomerPasskey,CustomerPasskeyChallenge):
        assert await database.scalar(select(func.count()).select_from(model))==0
    assert await database.scalar(select(func.count()).select_from(AccountMergeAlias))==0
    assert await database.scalar(select(func.count()).select_from(AccountAction))==0
