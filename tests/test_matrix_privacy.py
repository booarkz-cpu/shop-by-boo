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


@pytest.mark.asyncio
async def test_an_endless_subscription_blocks_deletion_and_a_panel_failure_stops_it(database, monkeypatch):
    """C1, stage 19: replaces test_v44_5_15_deep_regressions.test_privacy_delete_blocks_indefinite_subscription_… (three
    source lines): a subscription without an end date counts as active, and the account is never anonymised while
    its VPN access may still be switched on."""
    sub = await database.get(Subscription, 1)
    sub.expires_at = None
    await database.commit()
    with pytest.raises(HTTPException) as error:
        await shop.privacy_delete(request(), database)
    assert error.value.status_code == 409

    sub.expires_at = datetime.utcnow() - timedelta(days=1)
    await database.commit()
    calls = []

    class Down:
        async def disable_user(self, uuid):
            calls.append(uuid)
            raise RuntimeError('panel is down')
    monkeypatch.setattr(shop, 'RemnawaveClient', Down)
    with pytest.raises(HTTPException) as error:
        await shop.privacy_delete(request(), database)
    assert error.value.status_code == 503 and calls == ['remote-1']
    await database.rollback()
    assert (await database.get(User, 1, populate_existing=True)).deleted_at is None
    assert (await database.get(Subscription, 1, populate_existing=True)).remnawave_uuid == 'remote-1', 'the link to the panel is kept for the next try'


@pytest.mark.asyncio
async def test_the_customer_exports_own_data_without_secrets_or_other_customers(database):
    """REQ-SHOP-0017: «Скачать мои данные» in the cabinet — GET /api/me/privacy/export."""
    from decimal import Decimal
    from app.models import Payment, SupportTicket
    from app import operations_api
    owner = await database.get(User, 1)
    owner.email = 'owner@example.test'; owner.email_password_hash = 'pbkdf2$secret-hash'
    database.add_all([
        Payment(user_id=1, plan_id=1, amount=Decimal('100'), currency='RUB', provider='sandbox', status='fulfilled', idempotency_key='own-1', order_id='own-order-1'),
        Payment(user_id=2, plan_id=1, amount=Decimal('999'), currency='RUB', provider='sandbox', status='fulfilled', idempotency_key='other-1', order_id='other-order-1'),
        SupportTicket(user_id=1, subject='Не подключается', message='Помогите', status='open'),
        SupportTicket(user_id=2, subject='Чужое обращение', message='не моё', status='open'),
    ])
    await database.commit()
    data = await operations_api.privacy_export(request(), database)
    assert data['user']['id'] == 1 and data['user']['referral_code'] == 'OWNER'
    assert [p['id'] for p in data['payments']] and all(p['amount'].startswith('100') for p in data['payments'])
    assert len(data['payments']) == 1
    assert [t['subject'] for t in data['tickets']] == ['Не подключается']
    assert [s['id'] for s in data['subscriptions']] == [1]
    text = repr(data)
    assert 'secret-hash' not in text and 'Чужое обращение' not in text and '999' not in text
    assert data['exported_at']


@pytest.mark.asyncio
@pytest.mark.parametrize('linked', [False, True])
async def test_privacy_export_includes_own_login_identities_but_not_credentials(database, linked):
    """REQ-SHOP-0017: account identifiers belong in the owner's download, authentication secrets do not."""
    from app import operations_api

    owner = await database.get(User, 1)
    verified_at = datetime(2026, 11, 1, 12, 30) if linked else None
    identities = {
        'telegram_id': 711001 if linked else None,
        'yandex_id': 'yandex-owner' if linked else None,
        'vk_id': 'vk-owner' if linked else None,
        'email': 'owner+privacy@example.test' if linked else None,
        'email_verified_at': verified_at,
    }
    for field, value in identities.items():
        setattr(owner, field, value)
    owner.email_password_hash = 'private-owner-password-hash'
    owner.passkey_user_handle = 'private-owner-passkey-handle'
    other = await database.get(User, 2)
    other.email = 'other-private@example.test'
    other.vk_id = 'vk-other-private'
    other.yandex_id = 'yandex-other-private'
    other.email_password_hash = 'private-other-password-hash'
    await database.commit()

    data = await operations_api.privacy_export(request(), database)

    assert data['user']['id'] == owner.id
    assert {field: data['user'][field] for field in identities} == identities
    assert 'email_password_hash' not in data['user']
    assert 'passkey_user_handle' not in data['user']
    exported = repr(data)
    for private in ('private-owner-password-hash', 'private-owner-passkey-handle',
                    'other-private@example.test', 'vk-other-private',
                    'yandex-other-private', 'private-other-password-hash'):
        assert private not in exported


@pytest.mark.asyncio
@pytest.mark.parametrize('authorized', [True, False])
async def test_privacy_download_cannot_be_stored_in_http_caches(database, monkeypatch, authorized):
    """Exercise the export route, dependency injection and production middleware over HTTP."""
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from app import operations_api
    from app.db import get_db

    application = FastAPI()
    application.add_middleware(shop.SecurityHeadersMiddleware)
    application.get('/api/me/privacy/export')(operations_api.privacy_export)

    async def session():
        yield database

    application.dependency_overrides[get_db] = session
    if not authorized:
        async def reject(request, db):
            raise HTTPException(401, 'Authentication required')
        monkeypatch.setattr(shop, 'user_from_token', reject)

    async with AsyncClient(transport=ASGITransport(app=application), base_url='https://shop.example.test') as client:
        response = await client.get('/api/me/privacy/export')

    assert response.status_code == (200 if authorized else 401)
    assert response.headers['cache-control'] == 'no-store'
    if authorized:
        assert response.json()['user']['id'] == 1
        assert 'email' in response.json()['user']
    else:
        assert response.json() == {'detail': 'Authentication required'}
