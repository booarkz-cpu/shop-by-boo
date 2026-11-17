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
    assert [Decimal(p['amount']) for p in data['payments']] == [Decimal('100')]
    assert len(data['payments']) == 1
    assert [t['subject'] for t in data['tickets']] == ['Не подключается']
    assert [s['id'] for s in data['subscriptions']] == [1]
    text = repr(data)
    assert 'email_password_hash' not in data['user']
    assert 'secret-hash' not in text and 'Чужое обращение' not in text
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


@pytest.mark.asyncio
async def test_privacy_export_includes_owned_session_metadata_without_authentication_hashes(database):
    from app import operations_api
    from app.models import UserSession

    stamp = datetime(2026, 11, 1, 12, 30)
    rows = [
        UserSession(user_id=1, jti_hash='a'*64, ip='192.0.2.1', user_agent='Owner browser',
                    created_at=stamp, last_seen_at=stamp, expires_at=stamp+timedelta(days=1)),
        UserSession(user_id=1, jti_hash='b'*64, ip='2001:db8::1', user_agent='Revoked browser',
                    created_at=stamp, last_seen_at=stamp, expires_at=stamp+timedelta(days=1),
                    revoked_at=stamp+timedelta(hours=1)),
        UserSession(user_id=2, jti_hash='c'*64, ip='192.0.2.99', user_agent='Foreign browser',
                    created_at=stamp, last_seen_at=stamp, expires_at=stamp+timedelta(days=1)),
    ]
    database.add_all(rows)
    await database.commit()

    exported = await operations_api.privacy_export(request(), database)

    assert exported['sessions'] == [
        {'id': row.id, 'ip': row.ip, 'user_agent': row.user_agent, 'created_at': stamp,
         'last_seen_at': stamp, 'expires_at': row.expires_at, 'revoked_at': row.revoked_at}
        for row in rows[:2]
    ]
    assert 'jti_hash' not in repr(exported['sessions'])
    for private in ('a'*64, 'b'*64, 'c'*64, '192.0.2.99', 'Foreign browser'):
        assert private not in repr(exported)


@pytest.mark.asyncio
async def test_privacy_attachment_index_matches_private_download_permissions(database, monkeypatch):
    import base64
    import hashlib

    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from app import operations_api, support_attachments
    from app.db import get_db
    from app.models import SupportAttachment, SupportMessage, SupportTicket

    database.add_all([
        SupportTicket(id=1, user_id=1, subject='Owner ticket', message='Help'),
        SupportTicket(id=2, user_id=2, subject='Foreign ticket', message='Private'),
    ])
    await database.flush()
    sent = SupportMessage(ticket_id=1, role='customer', body='Sent file')
    foreign_message = SupportMessage(ticket_id=2, role='customer', body='Other file')
    database.add_all([sent, foreign_message])
    await database.flush()

    def attachment(name, ticket_id, actor, message_id=None):
        data = name.encode()
        return SupportAttachment(ticket_id=ticket_id, message_id=message_id, actor=actor,
            idempotency_key=name, name=name, mime='text/plain', data=data, size=len(data),
            sha256=hashlib.sha256(data).hexdigest())

    visible = [
        attachment('sent.txt', 1, 'customer:1', sent.id),
        attachment('reply.txt', 1, 'admin:operator@example.test', sent.id),
        attachment('draft.txt', 1, 'customer:1'),
    ]
    staff_draft = attachment('staff-private.txt', 1, 'admin:operator@example.test')
    foreign = attachment('foreign-private.txt', 2, 'customer:2', foreign_message.id)
    database.add_all([*visible, staff_draft, foreign])
    await database.commit()

    application = FastAPI()
    application.add_middleware(shop.SecurityHeadersMiddleware)
    application.get('/api/me/privacy/export')(operations_api.privacy_export)
    application.include_router(support_attachments.router)

    async def session():
        yield database
    application.dependency_overrides[get_db] = session

    async with AsyncClient(transport=ASGITransport(app=application), base_url='https://shop.example.test') as client:
        response = await client.get('/api/me/privacy/export')
        assert response.status_code == 200
        assert response.headers['cache-control'] == 'no-store'
        exported = response.json()
        assert [item['id'] for item in exported['support_attachments']] == [item.id for item in visible]
        assert exported['support_messages'][0]['id'] == sent.id
        for item, row in zip(exported['support_attachments'], visible):
            assert item == {
                'id': row.id, 'ticket_id': row.ticket_id, 'message_id': row.message_id,
                'name': row.name, 'mime': row.mime, 'size': row.size, 'sha256': row.sha256,
                'created_at': row.created_at.isoformat(),
                'download_path': f'/api/me/support/attachments/{row.id}',
            }
            downloaded = await client.get(item['download_path'])
            assert downloaded.status_code == 200
            assert 'no-store' in downloaded.headers['cache-control']
            assert base64.b64decode(downloaded.json()['content_base64']) == row.data
        assert 'content_base64' not in response.text and 'idempotency_key' not in response.text
        assert 'staff-private' not in response.text and 'foreign-private' not in response.text

        async def other_owner(request, db):
            return await db.get(User, 2)
        monkeypatch.setattr(shop, 'user_from_token', other_owner)
        for row in visible:
            denied = await client.get(f'/api/me/support/attachments/{row.id}')
            assert denied.status_code == 404
        other = (await client.get('/api/me/privacy/export')).json()
        assert [item['id'] for item in other['support_attachments']] == [foreign.id]
