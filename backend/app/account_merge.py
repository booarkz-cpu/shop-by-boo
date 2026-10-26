"""Two-owner account merge with conflict preview, atomic transfer and retry journal."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from .config import settings
from .db import get_db
from .models import (
    AbuseViolation,
    AccountAction,
    AccountMergeAlias,
    AccountMergeAuthorization,
    AccountMergeOperation,
    AuthExchangeCode,
    AutoRenewMethod,
    ConnectionObservation,
    TorrentDetection,
    CustomerImportIdentity,
    CustomerPasskey,
    CustomerPasskeyChallenge,
    EntitlementOperation,
    EntitlementQuote,
    FinancialLedger,
    FraudSignal,
    GiftCode,
    GiftRedemption,
    GiveawayEntry,
    Notification,
    Payment,
    PaymentTaxProfile,
    PromoGroupMember,
    PromoAudience,
    PromoRedemption,
    PromoReservation,
    ProvisioningOperation,
    ReferralLedger,
    ReferralLevelReward,
    ReferralReward,
    RefundRequest,
    Reseller,
    Subscription,
    SupportTicket,
    SurveyResponse,
    TrialGrant,
    User,
    UserDevice,
    UserSession,
    WithdrawalRequest,
)
from .security import decode_token, verify_password


router = APIRouter(prefix='/api/me/account-merge', tags=['account-merge'])
AUTHORIZATION_TTL = timedelta(minutes=10)
FRESH_SESSION_TTL = timedelta(minutes=5)
MAX_ACCOUNT_BALANCE = Decimal('9999999999.99')


class ReauthenticateIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    password: str | None = Field(default=None, min_length=8, max_length=128)


class MergeCodeIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    code: str = Field(min_length=40, max_length=128)


class ConfirmMergeIn(MergeCodeIn, ReauthenticateIn):
    acknowledge_data_transfer: bool


def _digest(*values: object) -> str:
    body = '\x1f'.join(str(value) for value in values)
    return hmac.new(settings.app_secret.encode(), body.encode(), hashlib.sha256).hexdigest()


def _token_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


async def canonical_user(db: AsyncSession, user: User) -> User:
    """Resolve a historical merged row without permitting chains or cycles."""
    seen: set[int] = set()
    current = user
    for _ in range(16):
        if current.id in seen:
            raise HTTPException(409, 'Account merge cycle detected')
        seen.add(current.id)
        if current.merged_into_user_id is None:
            return current
        next_user = await db.get(User, current.merged_into_user_id)
        if not next_user:
            raise HTTPException(409, 'Merged account destination is unavailable')
        current = next_user
    raise HTTPException(409, 'Account merge chain is too deep')


async def identity_user(db: AsyncSession, kind: str, value: object) -> User | None:
    """Resolve a current user from a primary or retained merged login identity."""
    columns = {
        'telegram': (User.telegram_id, AccountMergeAlias.telegram_id),
        'yandex': (User.yandex_id, AccountMergeAlias.yandex_id),
        'vk': (User.vk_id, AccountMergeAlias.vk_id),
        'google': (User.google_id, AccountMergeAlias.google_id),
    }
    if kind not in columns:
        raise ValueError('Unsupported identity kind')
    user_column, alias_column = columns[kind]
    user = (await db.execute(select(User).where(user_column == value))).scalar_one_or_none()
    if user:
        return await canonical_user(db, user)
    target_id = (await db.execute(select(AccountMergeAlias.target_user_id).where(alias_column == value))).scalar_one_or_none()
    if target_id is None:
        return None
    target = await db.get(User, target_id)
    return await canonical_user(db, target) if target else None


async def email_identity(db: AsyncSession, email: str) -> tuple[User | None, str | None, bool]:
    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user:
        canonical = await canonical_user(db, user)
        return canonical, user.email_password_hash, bool(user.email_verified_at)
    alias = (await db.execute(select(AccountMergeAlias).where(AccountMergeAlias.email == email))).scalar_one_or_none()
    if not alias:
        return None, None, False
    target = await db.get(User, alias.target_user_id)
    if not target:
        return None, None, False
    return await canonical_user(db, target), alias.email_password_hash, bool(alias.email_verified_at)


async def email_registered(db: AsyncSession, email: str) -> bool:
    if (await db.execute(select(User.id).where(User.email == email))).scalar_one_or_none():
        return True
    return bool((await db.execute(select(AccountMergeAlias.id).where(AccountMergeAlias.email == email))).scalar_one_or_none())


async def referral_owner(db: AsyncSession, code: str) -> User | None:
    user = (await db.execute(select(User).where(func.upper(User.referral_code) == code.upper()))).scalar_one_or_none()
    if user:
        return await canonical_user(db, user)
    target_id = (await db.execute(select(AccountMergeAlias.target_user_id).where(func.upper(AccountMergeAlias.referral_code) == code.upper()))).scalar_one_or_none()
    if target_id is None:
        return None
    target = await db.get(User, target_id)
    return await canonical_user(db, target) if target else None


async def update_account_password(db: AsyncSession, user_id: int, password_hash: str) -> None:
    await db.execute(update(AccountMergeAlias).where(
        AccountMergeAlias.target_user_id == user_id,
        AccountMergeAlias.email.is_not(None),
    ).values(email_password_hash=password_hash))


async def cleanup_expired_authorizations(db: AsyncSession) -> None:
    retained = select(AccountMergeOperation.authorization_id)
    await db.execute(delete(AccountMergeAuthorization).where(
        AccountMergeAuthorization.expires_at < datetime.utcnow() - timedelta(days=7),
        AccountMergeAuthorization.id.not_in(retained),
    ))


async def account_merge_cleanup_scheduler() -> None:
    from .db import engine
    import logging
    while True:
        try:
            async with AsyncSession(engine, expire_on_commit=False) as db:
                await cleanup_expired_authorizations(db)
                await db.commit()
        except Exception as error:
            logging.getLogger(__name__).warning(
                'Account merge authorization cleanup failed: %s', type(error).__name__
            )
        await asyncio.sleep(3600)


async def _current_session(db: AsyncSession, request: Request, user_id: int) -> UserSession | None:
    auth = request.headers.get('authorization', '')
    token = auth[7:] if auth.startswith('Bearer ') else request.cookies.get('rw_user', '')
    if not token:
        return None
    claims = decode_token(token)
    jti = str(claims.get('jti') or '')
    if not jti:
        return None
    return await db.scalar(select(UserSession).where(
        UserSession.user_id == user_id,
        UserSession.jti_hash == hashlib.sha256(jti.encode()).hexdigest(),
        UserSession.revoked_at.is_(None),
        UserSession.expires_at > datetime.utcnow(),
    ))


async def _reauthenticate(db: AsyncSession, request: Request, user: User, password: str | None) -> None:
    if user.email_password_hash:
        if not password or not verify_password(password, user.email_password_hash):
            raise HTTPException(401, 'Введите текущий пароль этого аккаунта')
        return
    session = await _current_session(db, request, user.id)
    if not session or session.created_at < datetime.utcnow() - FRESH_SESSION_TTL:
        raise HTTPException(401, 'Войдите в этот аккаунт заново перед объединением')


async def _authorization(db: AsyncSession, code: str, lock: bool = False) -> AccountMergeAuthorization:
    query = select(AccountMergeAuthorization).where(AccountMergeAuthorization.token_hash == _token_hash(code))
    if lock:
        query = query.execution_options(populate_existing=True).with_for_update()
    row = await db.scalar(query)
    if not row or row.used_at or row.expires_at <= datetime.utcnow():
        raise HTTPException(400, 'Код объединения недействителен или устарел')
    return row


async def _lock_users(db: AsyncSession, first_id: int, second_id: int) -> tuple[User, User]:
    ids = sorted({first_id, second_id})
    if len(ids) != 2:
        raise HTTPException(409, 'Нельзя объединить аккаунт с самим собой')
    rows = (await db.scalars(select(User).where(User.id.in_(ids)).order_by(User.id).with_for_update())).all()
    by_id = {row.id: row for row in rows}
    if len(by_id) != 2:
        raise HTTPException(404, 'Один из аккаунтов не найден')
    return by_id[first_id], by_id[second_id]


async def _overlap(db: AsyncSession, model, owner_name: str, key_name: str, source_id: int, target_id: int) -> bool:
    left, right = aliased(model), aliased(model)
    left_owner, right_owner = getattr(left, owner_name), getattr(right, owner_name)
    left_key, right_key = getattr(left, key_name), getattr(right, key_name)
    statement = select(left_owner).join(right, left_key == right_key).where(
        left_owner == source_id,
        right_owner == target_id,
        left_key.is_not(None),
    ).limit(1)
    return bool(await db.scalar(statement))


async def _count(db: AsyncSession, model, column, user_id: int) -> int:
    return int(await db.scalar(select(func.count()).select_from(model).where(column == user_id)) or 0)


async def _referral_conflict(db: AsyncSession, source: User, target: User) -> str | None:
    source_parent, target_parent = source.referred_by_id, target.referred_by_id
    if source_parent in {source.id, target.id} or target_parent in {source.id, target.id}:
        return 'Аккаунты уже находятся в одной реферальной ветке'
    if source_parent and target_parent and source_parent != target_parent:
        return 'У аккаунтов разные реферальные родители'
    current = target.id
    seen: set[int] = set()
    for _ in range(64):
        if current in seen:
            return 'В реферальной сети обнаружен цикл'
        seen.add(current)
        parent = await db.scalar(select(User.referred_by_id).where(User.id == current))
        if parent is None:
            break
        if parent == source.id:
            return 'Целевой аккаунт является потомком исходного'
        current = parent
    current = source.id
    seen.clear()
    for _ in range(64):
        if current in seen:
            return 'В реферальной сети обнаружен цикл'
        seen.add(current)
        parent = await db.scalar(select(User.referred_by_id).where(User.id == current))
        if parent is None:
            break
        if parent == target.id:
            return 'Исходный аккаунт является потомком целевого'
        current = parent
    return None


async def _conflicts(db: AsyncSession, source: User, target: User) -> list[dict[str, str]]:
    conflicts: list[dict[str, str]] = []

    def add(code: str, message: str) -> None:
        conflicts.append({'code': code, 'message': message})

    if source.deleted_at or source.merged_into_user_id:
        add('source_unavailable', 'Исходный аккаунт уже удалён или объединён')
    if target.deleted_at or target.merged_into_user_id:
        add('target_unavailable', 'Целевой аккаунт уже удалён или объединён')
    if source.restricted_at or target.restricted_at:
        add('restricted', 'Один из аккаунтов ограничен; сначала требуется проверка администратора')
    wallet_total = Decimal(str(source.wallet_balance or 0)) + Decimal(str(target.wallet_balance or 0))
    referral_total = Decimal(str(source.referral_balance or 0)) + Decimal(str(target.referral_balance or 0))
    if abs(wallet_total) > MAX_ACCOUNT_BALANCE:
        add('wallet_limit', 'Итоговый баланс кошелька превышает допустимый предел')
    if abs(referral_total) > MAX_ACCOUNT_BALANCE:
        add('referral_balance_limit', 'Итоговый реферальный баланс превышает допустимый предел')
    if await _overlap(db, Payment, 'user_id', 'idempotency_key', source.id, target.id):
        add('payment_retry_key', 'Совпадают ключи повторов платежей')
    if await _overlap(db, WithdrawalRequest, 'user_id', 'idempotency_key', source.id, target.id):
        add('withdrawal_retry_key', 'Совпадают ключи повторов выплат')
    if await _overlap(db, GiftRedemption, 'user_id', 'gift_code_id', source.id, target.id):
        add('gift_redemption', 'Оба аккаунта активировали один подарочный код')
    if await _overlap(db, SurveyResponse, 'user_id', 'survey_id', source.id, target.id):
        add('survey_response', 'Оба аккаунта уже ответили на один опрос')
    if await _overlap(db, GiveawayEntry, 'user_id', 'giveaway_id', source.id, target.id):
        add('giveaway_entry', 'Оба аккаунта участвуют в одном конкурсе')
    if await _overlap(db, Notification, 'user_id', 'dedupe_key', source.id, target.id):
        add('notification_identity', 'Совпадают постоянные идентификаторы уведомлений')
    if await _overlap(db, PromoGroupMember, 'user_id', 'group_id', source.id, target.id):
        add('promo_membership', 'Оба аккаунта состоят в одной ручной промогруппе')
    if await _overlap(db, ReferralLevelReward, 'referrer_id', 'payment_id', source.id, target.id):
        add('referral_reward', 'Оба аккаунта получили многоуровневую награду за один платёж')
    identity_columns = (
        ('telegram_identity', AccountMergeAlias.telegram_id, source.telegram_id),
        ('yandex_identity', AccountMergeAlias.yandex_id, source.yandex_id),
        ('vk_identity', AccountMergeAlias.vk_id, source.vk_id),
        ('google_identity', AccountMergeAlias.google_id, source.google_id),
        ('email_identity', AccountMergeAlias.email, source.email),
        ('referral_identity', AccountMergeAlias.referral_code, source.referral_code),
    )
    for code, column, value in identity_columns:
        if value is not None and await db.scalar(select(AccountMergeAlias.id).where(
            column == value,
            AccountMergeAlias.target_user_id.not_in((source.id, target.id)),
        ).limit(1)):
            add(code, 'Способ входа уже закреплён за другим аккаунтом')
    singleton_models = (
        (AutoRenewMethod, 'saved_payment_method', 'У обоих аккаунтов есть сохранённый способ автопродления'),
        (TrialGrant, 'trial_history', 'Оба аккаунта уже использовали пробный период'),
        (PaymentTaxProfile, 'tax_profile', 'У обоих аккаунтов настроен налоговый профиль'),
        (Reseller, 'partner_profile', 'Оба аккаунта являются владельцами партнёрских профилей'),
    )
    for model, code, message in singleton_models:
        column = model.owner_user_id if model is Reseller else model.user_id
        if await _count(db, model, column, source.id) and await _count(db, model, column, target.id):
            add(code, message)
    passkeys = await _count(db, CustomerPasskey, CustomerPasskey.user_id, source.id) + await _count(db, CustomerPasskey, CustomerPasskey.user_id, target.id)
    if passkeys > 10:
        add('passkey_limit', 'После объединения будет больше 10 ключей доступа')
    subscriptions = await _count(db, Subscription, Subscription.user_id, source.id) + await _count(db, Subscription, Subscription.user_id, target.id)
    if subscriptions > 20:
        add('subscription_limit', 'После объединения будет больше 20 подписок')
    active_grants = await db.scalar(select(Payment.id).where(
        Payment.user_id.in_((source.id, target.id)),
        Payment.status.in_(('paid', 'fulfilled', 'refunded_pending_revoke')),
        Payment.fulfillment_status != 'completed',
    ).limit(1))
    active_entitlement = await db.scalar(select(EntitlementOperation.id).where(
        EntitlementOperation.user_id.in_((source.id, target.id)),
        EntitlementOperation.status.in_(('queued', 'applying', 'refund_pending')),
    ).limit(1))
    active_gift = await db.scalar(select(GiftRedemption.id).where(
        GiftRedemption.user_id.in_((source.id, target.id)),
        GiftRedemption.status != 'completed',
    ).limit(1))
    if active_grants or active_entitlement or active_gift:
        add('commerce_in_progress', 'Сначала дождитесь завершения выдачи, подарка или возврата')
    referral = await _referral_conflict(db, source, target)
    if referral:
        add('referral_graph', referral)
    return conflicts


async def _summary(db: AsyncSession, source: User, target: User) -> dict:
    conflicts = await _conflicts(db, source, target)
    source_subscriptions = await _count(db, Subscription, Subscription.user_id, source.id)
    target_subscriptions = await _count(db, Subscription, Subscription.user_id, target.id)
    source_payments = await _count(db, Payment, Payment.user_id, source.id)
    target_payments = await _count(db, Payment, Payment.user_id, target.id)
    source_passkeys = await _count(db, CustomerPasskey, CustomerPasskey.user_id, source.id)
    target_passkeys = await _count(db, CustomerPasskey, CustomerPasskey.user_id, target.id)
    wallet = Decimal(str(source.wallet_balance or 0)) + Decimal(str(target.wallet_balance or 0))
    referral = Decimal(str(source.referral_balance or 0)) + Decimal(str(target.referral_balance or 0))
    return {
        'allowed': not conflicts,
        'source': {
            'created_at': source.created_at.isoformat(),
            'wallet_balance': str(source.wallet_balance or 0),
            'referral_balance': str(source.referral_balance or 0),
            'subscriptions': source_subscriptions,
            'payments': source_payments,
            'passkeys': source_passkeys,
            'login_methods': sum(bool(value) for value in (source.email, source.telegram_id, source.yandex_id, source.vk_id, source.google_id, source.passkey_user_handle)),
        },
        'target': {
            'created_at': target.created_at.isoformat(),
            'wallet_balance': str(target.wallet_balance or 0),
            'referral_balance': str(target.referral_balance or 0),
            'subscriptions': target_subscriptions,
            'payments': target_payments,
            'passkeys': target_passkeys,
            'login_methods': sum(bool(value) for value in (target.email, target.telegram_id, target.yandex_id, target.vk_id, target.google_id, target.passkey_user_handle)),
        },
        'result': {
            'wallet_balance': str(wallet),
            'referral_balance': str(referral),
            'subscriptions': source_subscriptions + target_subscriptions,
            'payments': source_payments + target_payments,
            'passkeys': source_passkeys + target_passkeys,
        },
        'conflicts': conflicts,
        'effects': [
            'Данные исходного аккаунта перейдут в текущий аккаунт',
            'Способы входа сохранятся, но для всех email будет действовать пароль текущего аккаунта',
            'Сессии исходного аккаунта и другие сессии основного аккаунта будут отозваны',
            'Операцию нельзя автоматически отменить после подтверждения',
        ],
    }


async def _move(db: AsyncSession, model, column, source_id: int, target_id: int) -> None:
    await db.execute(update(model).where(column == source_id).values({column.key: target_id}))


async def _transfer(db: AsyncSession, source: User, target: User, authorization: AccountMergeAuthorization,
        preserved_session_id: int | None) -> dict:
    now = datetime.utcnow()
    source_email = source.email
    source_password = source.email_password_hash
    source_email_verified_at = source.email_verified_at
    source_telegram_id = source.telegram_id
    source_yandex_id = source.yandex_id
    source_vk_id = source.vk_id
    source_google_id = source.google_id
    source_referral_code = source.referral_code
    source_passkey_handle = source.passkey_user_handle
    before_wallet = Decimal(str(source.wallet_balance or 0)) + Decimal(str(target.wallet_balance or 0))
    before_referral = Decimal(str(source.referral_balance or 0)) + Decimal(str(target.referral_balance or 0))
    source_subscription_count = await _count(db, Subscription, Subscription.user_id, source.id)
    source_payment_count = await _count(db, Payment, Payment.user_id, source.id)

    target_primary = await db.scalar(select(Subscription.id).where(
        Subscription.user_id == target.id,
        Subscription.is_primary.is_(True),
    ).with_for_update())
    await db.execute(select(Subscription.id).where(Subscription.user_id == source.id).with_for_update())
    if target_primary:
        await db.execute(update(Subscription).where(Subscription.user_id == source.id).values(is_primary=False))

    target_password = target.email_password_hash or source_password
    moved_email = bool(not target.email and source_email)
    moved_telegram = bool(target.telegram_id is None and source_telegram_id is not None)
    moved_yandex = bool(not target.yandex_id and source_yandex_id)
    moved_vk = bool(not target.vk_id and source_vk_id)
    moved_google = bool(not target.google_id and source_google_id)
    source.telegram_id = None
    source.yandex_id = None
    source.vk_id = None
    source.google_id = None
    source.email = None
    source.email_password_hash = None
    source.email_verified_at = None
    source.referral_code = f'MERGED_{source.id}_{secrets.token_hex(4)}'
    source.passkey_user_handle = None
    await db.flush()
    if moved_email:
        target.email = source_email
        target.email_verified_at = source_email_verified_at
    if target_password:
        target.email_password_hash = target_password
    if moved_telegram:
        target.telegram_id = source_telegram_id
    if moved_yandex:
        target.yandex_id = source_yandex_id
    if moved_vk:
        target.vk_id = source_vk_id
    if moved_google:
        target.google_id = source_google_id
    if not target.username and source.username:
        target.username = source.username
    if not target.passkey_user_handle and source_passkey_handle:
        target.passkey_user_handle = source_passkey_handle
    target.auto_renew_enabled = bool(target.auto_renew_enabled or source.auto_renew_enabled)
    target.wallet_balance = before_wallet
    target.referral_balance = before_referral
    target.referred_by_id = target.referred_by_id or source.referred_by_id

    source_passkeys = (await db.scalars(select(CustomerPasskey).where(CustomerPasskey.user_id == source.id).with_for_update())).all()
    for credential in source_passkeys:
        credential.user_handle = credential.user_handle or source_passkey_handle
        credential.user_id = target.id
    target_passkeys = (await db.scalars(select(CustomerPasskey).where(CustomerPasskey.user_id == target.id).with_for_update())).all()
    for credential in target_passkeys:
        credential.user_handle = credential.user_handle or target.passkey_user_handle

    await db.execute(update(AccountMergeAlias).where(
        AccountMergeAlias.target_user_id.in_((source.id, target.id)),
        AccountMergeAlias.email.is_not(None),
    ).values(email_password_hash=target_password))
    await db.execute(update(AccountMergeAlias).where(AccountMergeAlias.target_user_id == source.id).values(target_user_id=target.id))
    alias = AccountMergeAlias(
        source_user_id=source.id,
        target_user_id=target.id,
        telegram_id=None if moved_telegram else source_telegram_id,
        yandex_id=None if moved_yandex else source_yandex_id,
        vk_id=None if moved_vk else source_vk_id,
        google_id=None if moved_google else source_google_id,
        email=None if moved_email else source_email,
        email_password_hash=target_password if source_email and not moved_email else None,
        email_verified_at=source_email_verified_at if source_email and not moved_email else None,
        referral_code=source_referral_code,
        merged_at=now,
    )
    db.add(alias)

    direct_moves = (
        (CustomerImportIdentity, CustomerImportIdentity.user_id),
        (Payment, Payment.user_id),
        (Subscription, Subscription.user_id),
        (EntitlementQuote, EntitlementQuote.user_id),
        (EntitlementOperation, EntitlementOperation.user_id),
        (FinancialLedger, FinancialLedger.user_id),
        (GiftRedemption, GiftRedemption.user_id),
        (PromoRedemption, PromoRedemption.user_id),
        (PromoReservation, PromoReservation.user_id),
        (ProvisioningOperation, ProvisioningOperation.user_id),
        (RefundRequest, RefundRequest.user_id),
        (SupportTicket, SupportTicket.user_id),
        (WithdrawalRequest, WithdrawalRequest.user_id),
        (FraudSignal, FraudSignal.user_id),
        (Notification, Notification.user_id),
        (UserDevice, UserDevice.user_id),
        (TrialGrant, TrialGrant.user_id),
        (ConnectionObservation, ConnectionObservation.user_id),
        (TorrentDetection, TorrentDetection.user_id),
        (AbuseViolation, AbuseViolation.user_id),
        (PaymentTaxProfile, PaymentTaxProfile.user_id),
        (SurveyResponse, SurveyResponse.user_id),
        (GiveawayEntry, GiveawayEntry.user_id),
        (AutoRenewMethod, AutoRenewMethod.user_id),
    )
    for model, column in direct_moves:
        await _move(db, model, column, source.id, target.id)
    await _move(db, GiftCode, GiftCode.purchaser_user_id, source.id, target.id)
    await _move(db, Reseller, Reseller.owner_user_id, source.id, target.id)
    await _move(db, ReferralReward, ReferralReward.referrer_id, source.id, target.id)
    await _move(db, ReferralReward, ReferralReward.referred_user_id, source.id, target.id)
    await _move(db, ReferralLevelReward, ReferralLevelReward.referrer_id, source.id, target.id)
    await _move(db, ReferralLevelReward, ReferralLevelReward.referred_user_id, source.id, target.id)
    await _move(db, ReferralLedger, ReferralLedger.user_id, source.id, target.id)
    await _move(db, ReferralLedger, ReferralLedger.source_user_id, source.id, target.id)
    await db.execute(update(User).where(User.referred_by_id == source.id, User.id != target.id).values(referred_by_id=target.id))

    await _move(db, PromoGroupMember, PromoGroupMember.user_id, source.id, target.id)
    audiences = (await db.scalars(select(PromoAudience).with_for_update())).all()
    for audience in audiences:
        values = [target.id if value == source.id else value for value in (audience.user_ids or [])]
        audience.user_ids = list(dict.fromkeys(values))

    revoke_sessions = update(UserSession).where(
        UserSession.user_id.in_((source.id, target.id)),
        UserSession.revoked_at.is_(None),
    )
    if preserved_session_id is not None:
        revoke_sessions = revoke_sessions.where(UserSession.id != preserved_session_id)
    await db.execute(revoke_sessions.values(revoked_at=now))
    await db.execute(update(AuthExchangeCode).where(
        AuthExchangeCode.user_id.in_((source.id, target.id)),
        AuthExchangeCode.used_at.is_(None),
    ).values(used_at=now))
    await db.execute(update(AccountAction).where(
        AccountAction.user_id.in_((source.id, target.id)),
        AccountAction.used_at.is_(None),
    ).values(used_at=now))
    await db.execute(delete(CustomerPasskeyChallenge).where(CustomerPasskeyChallenge.user_id.in_((source.id, target.id))))
    await db.execute(update(AccountMergeAuthorization).where(
        AccountMergeAuthorization.source_user_id.in_((source.id, target.id)),
        AccountMergeAuthorization.used_at.is_(None),
    ).values(used_at=now))
    authorization.used_at = now
    authorization.target_user_id = target.id

    source.username = f'merged_{source.id}'
    source.referred_by_id = None
    source.auto_renew_enabled = False
    source.wallet_balance = Decimal('0')
    source.referral_balance = Decimal('0')
    source.merged_into_user_id = target.id
    source.merged_at = now
    source.deleted_at = now

    await db.flush()
    if Decimal(str(target.wallet_balance or 0)) != before_wallet or Decimal(str(source.wallet_balance or 0)) != 0:
        raise RuntimeError('Wallet reconciliation failed')
    if Decimal(str(target.referral_balance or 0)) != before_referral or Decimal(str(source.referral_balance or 0)) != 0:
        raise RuntimeError('Referral reconciliation failed')
    if await _count(db, Subscription, Subscription.user_id, source.id) != 0:
        raise RuntimeError('Subscription ownership reconciliation failed')
    if await _count(db, Payment, Payment.user_id, source.id) != 0:
        raise RuntimeError('Payment ownership reconciliation failed')
    return {
        'ok': True,
        'source_user_id': source.id,
        'target_user_id': target.id,
        'wallet_balance': str(before_wallet),
        'referral_balance': str(before_referral),
        'subscriptions_transferred': source_subscription_count,
        'payments_transferred': source_payment_count,
        'merged_at': now.isoformat(),
    }


@router.post('/authorization')
async def create_authorization(payload: ReauthenticateIn, request: Request, response: Response,
        db: AsyncSession = Depends(get_db)):
    from .main import audit, user_from_token
    user = await user_from_token(request, db)
    user = await canonical_user(db, user)
    user = await db.scalar(select(User).where(User.id == user.id).execution_options(populate_existing=True).with_for_update())
    if not user or user.deleted_at or user.merged_into_user_id:
        raise HTTPException(409, 'Аккаунт недоступен для объединения')
    await _reauthenticate(db, request, user, payload.password)
    now = datetime.utcnow()
    await db.execute(update(AccountMergeAuthorization).where(
        AccountMergeAuthorization.source_user_id == user.id,
        AccountMergeAuthorization.used_at.is_(None),
    ).values(used_at=now))
    raw = secrets.token_urlsafe(36)
    row = AccountMergeAuthorization(
        source_user_id=user.id,
        token_hash=_token_hash(raw),
        expires_at=now + AUTHORIZATION_TTL,
        created_at=now,
    )
    db.add(row)
    await audit(db, 'account.merge.authorization_created', f'user:{user.id}', str(user.id))
    await db.commit()
    response.headers['Cache-Control'] = 'private, no-store'
    return {'code': raw, 'expires_at': row.expires_at.isoformat(), 'valid_for_seconds': int(AUTHORIZATION_TTL.total_seconds())}


@router.post('/preview')
async def preview_merge(payload: MergeCodeIn, request: Request, response: Response,
        db: AsyncSession = Depends(get_db)):
    from .main import user_from_token
    target = await canonical_user(db, await user_from_token(request, db))
    authorization = await _authorization(db, payload.code)
    source = await db.get(User, authorization.source_user_id)
    if not source:
        raise HTTPException(404, 'Исходный аккаунт не найден')
    source = await canonical_user(db, source)
    if source.id == target.id:
        raise HTTPException(409, 'Нельзя объединить аккаунт с самим собой')
    response.headers['Cache-Control'] = 'private, no-store'
    return await _summary(db, source, target)


@router.post('/confirm')
async def confirm_merge(payload: ConfirmMergeIn, request: Request, response: Response,
        db: AsyncSession = Depends(get_db)):
    from .main import _set_auth_cookies, audit, create_user_session, user_from_token
    if not payload.acknowledge_data_transfer:
        raise HTTPException(422, 'Подтвердите необратимый перенос данных')
    idempotency_key = request.headers.get('Idempotency-Key', '')
    if not idempotency_key or len(idempotency_key) > 128:
        raise HTTPException(400, 'Idempotency-Key is required')
    target = await canonical_user(db, await user_from_token(request, db))
    token_hash = _token_hash(payload.code)
    operation_key = _digest('account-merge-operation-v1', target.id, idempotency_key)
    fingerprint = _digest('account-merge-request-v1', target.id, token_hash)
    existing = await db.get(AccountMergeOperation, operation_key)
    if existing:
        if not hmac.compare_digest(existing.fingerprint, fingerprint):
            raise HTTPException(409, 'Ключ повтора уже использован для другого объединения')
        response.headers['Cache-Control'] = 'private, no-store'
        return existing.result

    authorization_seed = await _authorization(db, payload.code)
    source, target = await _lock_users(db, authorization_seed.source_user_id, target.id)
    existing = await db.scalar(select(AccountMergeOperation).where(AccountMergeOperation.key == operation_key).with_for_update())
    if existing:
        if not hmac.compare_digest(existing.fingerprint, fingerprint):
            raise HTTPException(409, 'Ключ повтора уже использован для другого объединения')
        response.headers['Cache-Control'] = 'private, no-store'
        return existing.result
    authorization = await _authorization(db, payload.code, lock=True)
    if authorization.id != authorization_seed.id:
        raise HTTPException(409, 'Код объединения изменился; начните заново')
    if source.merged_into_user_id or target.merged_into_user_id:
        raise HTTPException(409, 'Один из аккаунтов уже объединён')
    await _reauthenticate(db, request, target, payload.password)
    current_session = await _current_session(db, request, target.id)
    conflicts = await _conflicts(db, source, target)
    if conflicts:
        raise HTTPException(409, {'message': 'Объединение остановлено из-за конфликтов', 'conflicts': conflicts})
    result = await _transfer(db, source, target, authorization, current_session.id if current_session else None)
    operation = AccountMergeOperation(
        key=operation_key,
        fingerprint=fingerprint,
        authorization_id=authorization.id,
        source_user_id=source.id,
        target_user_id=target.id,
        result=result,
    )
    db.add(operation)
    await audit(db, 'account.merge.completed', f'user:{target.id}', f'user:{source.id}', {
        'source_user_id': source.id,
        'target_user_id': target.id,
        'subscriptions_transferred': result['subscriptions_transferred'],
        'payments_transferred': result['payments_transferred'],
    })
    await db.commit()
    if current_session is None:
        token = await create_user_session(db, target, request)
        response.set_cookie('rw_user', token, httponly=True, secure=settings.cookie_secure,
            samesite=settings.cookie_samesite, max_age=3600)
        _set_auth_cookies(response, token)
    response.headers['Cache-Control'] = 'private, no-store'
    return result
