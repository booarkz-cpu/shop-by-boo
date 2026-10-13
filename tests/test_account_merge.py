"""Verified account merging, reconciliation, conflicts and PostgreSQL races."""

import asyncio
import hashlib
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request as StarletteRequest

from app import account_merge as merge
from app import cabinet_api
from app import main as shop
from app.models import (
    AccountMergeAlias,
    AccountMergeAuthorization,
    AccountMergeOperation,
    CustomerPasskey,
    FinancialLedger,
    Notification,
    Payment,
    Subscription,
    SupportTicket,
    TrialGrant,
    User,
    UserSession,
)
from app.security import hash_password, verify_password
from test_subscription_commerce import database, request


async def prepare_accounts(db, monkeypatch):
    target = await db.get(User, 1)
    source = await db.get(User, 2)
    target.email = 'target@example.test'
    target.email_password_hash = hash_password('target-password')
    target.telegram_id = 1001
    target.referral_balance = Decimal('10.00')
    source.email = 'source@example.test'
    source.email_password_hash = hash_password('source-password')
    source.telegram_id = 2002
    source.username = 'Source profile'
    source.referral_code = 'SOURCE-CODE'
    source.wallet_balance = Decimal('200.00')
    source.referral_balance = Decimal('30.00')
    source.passkey_user_handle = 'c291cmNlLWhhbmRsZQ'
    source_subscription = Subscription(
        user_id=source.id,
        plan_id=2,
        is_primary=True,
        name='Source VPN',
        lifecycle_status='active',
        expires_at=datetime.utcnow() + timedelta(days=10),
    )
    db.add(source_subscription)
    await db.flush()
    db.add_all([
        Payment(
            user_id=source.id,
            subscription_id=source_subscription.id,
            plan_id=2,
            provider='sandbox',
            order_id='source-order',
            amount=Decimal('200.00'),
            currency='RUB',
            status='paid',
            fulfillment_status='completed',
            idempotency_key='source-payment-key',
        ),
        FinancialLedger(
            operation_key='source-wallet-history',
            user_id=source.id,
            kind='wallet_topup',
            direction='credit',
            amount=Decimal('200.00'),
            currency='RUB',
        ),
        SupportTicket(user_id=source.id, subject='Source ticket', message='Keep the conversation'),
        Notification(
            user_id=source.id,
            channel='in_app',
            kind='source',
            title='Source notification',
            body='Keep me',
            dedupe_key='source-notification',
        ),
        CustomerPasskey(
            user_id=source.id,
            credential_id='source-credential',
            public_key='source-public-key',
            user_handle=source.passkey_user_handle,
            name='Source passkey',
        ),
    ])
    await db.commit()
    current = {'id': source.id}

    async def active_user(_request, session):
        return await session.get(User, current['id'])

    monkeypatch.setattr(shop, 'user_from_token', active_user)
    authorization = await merge.create_authorization(
        merge.ReauthenticateIn(password='source-password'), request(), Response(), db
    )
    current['id'] = target.id
    return target, source, current, authorization['code']


@pytest.mark.asyncio
async def test_merge_transfers_money_subscriptions_history_and_login_aliases(database, monkeypatch):
    target, source, _, code = await prepare_accounts(database, monkeypatch)
    preview = await merge.preview_merge(merge.MergeCodeIn(code=code), request(), Response(), database)
    assert preview['allowed'] is True
    assert preview['result'] == {
        'wallet_balance': '1200.00',
        'referral_balance': '40.00',
        'subscriptions': 2,
        'payments': 1,
        'passkeys': 1,
    }

    payload = merge.ConfirmMergeIn(
        code=code,
        password='target-password',
        acknowledge_data_transfer=True,
    )
    result = await merge.confirm_merge(payload, request('merge-once'), Response(), database)
    assert result['target_user_id'] == target.id
    assert result['source_user_id'] == source.id
    assert result['subscriptions_transferred'] == 1
    assert result['payments_transferred'] == 1

    target_id, source_id = target.id, source.id
    database.expire_all()
    target = await database.get(User, target_id)
    source = await database.get(User, source_id)
    assert target.wallet_balance == Decimal('1200.00')
    assert target.referral_balance == Decimal('40.00')
    assert source.wallet_balance == 0 and source.referral_balance == 0
    assert source.deleted_at and source.merged_into_user_id == target.id
    assert await database.scalar(select(func.count()).select_from(Subscription).where(Subscription.user_id == target.id)) == 2
    assert await database.scalar(select(func.count()).select_from(Subscription).where(Subscription.user_id == source.id)) == 0
    assert await database.scalar(select(func.count()).select_from(Subscription).where(
        Subscription.user_id == target.id,
        Subscription.is_primary.is_(True),
    )) == 1
    assert await database.scalar(select(Payment.user_id).where(Payment.order_id == 'source-order')) == target.id
    assert await database.scalar(select(FinancialLedger.user_id).where(FinancialLedger.operation_key == 'source-wallet-history')) == target.id
    assert await database.scalar(select(SupportTicket.user_id).where(SupportTicket.subject == 'Source ticket')) == target.id
    credential = await database.scalar(select(CustomerPasskey).where(CustomerPasskey.credential_id == 'source-credential'))
    assert credential.user_id == target.id and credential.user_handle == 'c291cmNlLWhhbmRsZQ'

    alias = await database.scalar(select(AccountMergeAlias).where(AccountMergeAlias.source_user_id == source.id))
    assert alias.target_user_id == target.id
    assert alias.email == 'source@example.test' and alias.telegram_id == 2002
    assert alias.referral_code == 'SOURCE-CODE'
    alias_user, password_hash, _ = await merge.email_identity(database, 'source@example.test')
    assert alias_user.id == target.id and verify_password('target-password', password_hash)
    assert not verify_password('source-password', password_hash)
    assert (await merge.identity_user(database, 'telegram', 2002)).id == target.id
    assert (await merge.referral_owner(database, 'source-code')).id == target.id
    assert await merge.email_registered(database, 'source@example.test')
    assert await database.scalar(select(func.count()).select_from(AccountMergeOperation)) == 1
    authorization = await database.scalar(select(AccountMergeAuthorization))
    assert authorization.used_at and authorization.target_user_id == target.id
    assert authorization.token_hash == hashlib.sha256(code.encode()).hexdigest()
    assert code not in authorization.token_hash
    assert await database.scalar(select(func.count()).select_from(UserSession).where(
        UserSession.user_id == target.id,
        UserSession.revoked_at.is_(None),
    )) == 1

    login = await cabinet_api.auth_login(
        cabinet_api.EmailAuthIn(email='source@example.test', password='target-password'),
        request(),
        Response(),
        database,
    )
    assert login['id'] == target.id
    with pytest.raises(HTTPException) as old_password:
        await cabinet_api.auth_login(
            cabinet_api.EmailAuthIn(email='source@example.test', password='source-password'),
            request(),
            Response(),
            database,
        )
    assert old_password.value.status_code == 401

    repeated = await merge.confirm_merge(payload, request('merge-once'), Response(), database)
    assert repeated == result
    assert await database.scalar(select(func.count()).select_from(AccountMergeOperation)) == 1
    expired = AccountMergeAuthorization(
        source_user_id=source.id,
        token_hash='f' * 64,
        expires_at=datetime.utcnow() - timedelta(days=8),
    )
    database.add(expired)
    await database.commit()
    expired_id = expired.id
    await merge.cleanup_expired_authorizations(database)
    await database.commit()
    assert await database.get(AccountMergeAuthorization, expired_id) is None
    assert await database.scalar(select(func.count()).select_from(AccountMergeAuthorization)) == 1


@pytest.mark.asyncio
async def test_merge_preserves_authenticated_target_session_for_safe_retry(database, monkeypatch):
    target, _, _, code = await prepare_accounts(database, monkeypatch)
    now = datetime.utcnow()
    jti = 'merge-target-session'
    preserved = UserSession(
        user_id=target.id,
        jti_hash=hashlib.sha256(jti.encode()).hexdigest(),
        expires_at=now + timedelta(hours=1),
    )
    revoked = UserSession(
        user_id=target.id,
        jti_hash=hashlib.sha256(b'other-target-session').hexdigest(),
        expires_at=now + timedelta(hours=1),
    )
    database.add_all([preserved, revoked])
    await database.commit()
    preserved_id, revoked_id = preserved.id, revoked.id
    headers = [
        (b'authorization', f'Bearer {shop.issue_user_token(target, jti=jti)}'.encode()),
        (b'idempotency-key', b'preserved-session-merge'),
    ]
    authenticated_request = StarletteRequest({'type': 'http', 'headers': headers})
    payload = merge.ConfirmMergeIn(
        code=code,
        password='target-password',
        acknowledge_data_transfer=True,
    )
    first = await merge.confirm_merge(payload, authenticated_request, Response(), database)
    database.expire_all()
    assert (await database.get(UserSession, preserved_id)).revoked_at is None
    assert (await database.get(UserSession, revoked_id)).revoked_at is not None
    repeated = await merge.confirm_merge(payload, authenticated_request, Response(), database)
    assert repeated == first


@pytest.mark.asyncio
async def test_preview_conflict_rolls_back_without_partial_transfer(database, monkeypatch):
    target, source, _, code = await prepare_accounts(database, monkeypatch)
    database.add_all([
        TrialGrant(user_id=target.id, subscription_id=1, plan_id=1, days=3, status='completed'),
        TrialGrant(user_id=source.id, plan_id=2, days=3, status='completed'),
    ])
    await database.commit()
    preview = await merge.preview_merge(merge.MergeCodeIn(code=code), request(), Response(), database)
    assert preview['allowed'] is False
    assert 'trial_history' in {row['code'] for row in preview['conflicts']}
    with pytest.raises(HTTPException) as error:
        await merge.confirm_merge(
            merge.ConfirmMergeIn(code=code, password='target-password', acknowledge_data_transfer=True),
            request('blocked-merge'),
            Response(),
            database,
        )
    assert error.value.status_code == 409
    target_id, source_id = target.id, source.id
    await database.rollback()
    database.expire_all()
    assert (await database.get(User, source_id)).deleted_at is None
    assert (await database.get(User, target_id)).wallet_balance == Decimal('1000.00')
    assert await database.scalar(select(Payment.user_id).where(Payment.order_id == 'source-order')) == source_id
    assert await database.scalar(select(func.count()).select_from(AccountMergeAlias)) == 0


@pytest.mark.asyncio
async def test_preview_blocks_numeric_balance_overflow(database, monkeypatch):
    target, source, _, code = await prepare_accounts(database, monkeypatch)
    target.wallet_balance = Decimal('9999999999.99')
    source.wallet_balance = Decimal('0.01')
    await database.commit()
    preview = await merge.preview_merge(merge.MergeCodeIn(code=code), request(), Response(), database)
    assert preview['allowed'] is False
    assert 'wallet_limit' in {row['code'] for row in preview['conflicts']}
    assert target.wallet_balance == Decimal('9999999999.99')
    assert source.wallet_balance == Decimal('0.01')


@pytest.mark.asyncio
async def test_merge_requires_both_passwords_and_rejects_self(database, monkeypatch):
    target, source, current, code = await prepare_accounts(database, monkeypatch)
    source_id = source.id
    current['id'] = source.id
    with pytest.raises(HTTPException) as error:
        await merge.preview_merge(merge.MergeCodeIn(code=code), request(), Response(), database)
    assert error.value.status_code == 409
    current['id'] = target.id
    with pytest.raises(HTTPException) as error:
        await merge.confirm_merge(
            merge.ConfirmMergeIn(code=code, password='wrong-password', acknowledge_data_transfer=True),
            request('wrong-password'),
            Response(),
            database,
        )
    assert error.value.status_code == 401
    await database.rollback()
    assert (await database.get(User, source_id)).deleted_at is None


@pytest.mark.asyncio
async def test_parallel_confirmation_commits_once_on_postgres(database, monkeypatch):
    if database.bind.dialect.name != 'postgresql':
        pytest.skip('PostgreSQL row locks run in CI')
    target, source, _, code = await prepare_accounts(database, monkeypatch)
    target_id = target.id
    source_id = source.id

    async def active_target(_request, session):
        return await session.get(User, target_id)

    monkeypatch.setattr(shop, 'user_from_token', active_target)
    payload = merge.ConfirmMergeIn(code=code, password='target-password', acknowledge_data_transfer=True)

    async def confirm():
        async with AsyncSession(database.bind, expire_on_commit=False) as session:
            return await merge.confirm_merge(payload, request('parallel-merge'), Response(), session)

    first, second = await asyncio.gather(confirm(), confirm())
    assert first == second
    database.expire_all()
    assert await database.scalar(select(func.count()).select_from(AccountMergeOperation)) == 1
    assert (await database.get(User, source_id)).merged_into_user_id == target_id
