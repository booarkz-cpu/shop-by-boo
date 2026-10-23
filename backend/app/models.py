from datetime import datetime
from decimal import Decimal
import secrets
from sqlalchemy import String, Integer, BigInteger, DateTime, Boolean, Numeric, Text, UniqueConstraint, JSON, ForeignKey, Index, text, LargeBinary
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base

class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("passkey_user_handle", name="uq_users_passkey_user_handle"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int|None] = mapped_column(BigInteger, unique=True, index=True)
    yandex_id: Mapped[str|None] = mapped_column(String(255), unique=True, index=True)
    vk_id: Mapped[str|None] = mapped_column(String(255), unique=True, index=True)
    email: Mapped[str|None] = mapped_column(String(320), unique=True, index=True)
    email_password_hash: Mapped[str|None] = mapped_column(String(512))
    email_verified_at: Mapped[datetime|None] = mapped_column(DateTime)
    username: Mapped[str|None] = mapped_column(String(255))
    referral_code: Mapped[str] = mapped_column(String(32), unique=True, index=True, default=lambda: secrets.token_urlsafe(8).upper())
    referred_by_id: Mapped[int|None] = mapped_column(Integer, index=True)
    auto_renew_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    referral_balance: Mapped[Decimal] = mapped_column(Numeric(12,2), default=0, nullable=False)
    wallet_balance: Mapped[Decimal] = mapped_column(Numeric(12,2), default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    deleted_at: Mapped[datetime|None] = mapped_column(DateTime)
    restricted_at: Mapped[datetime|None] = mapped_column(DateTime)
    passkey_user_handle: Mapped[str|None] = mapped_column(String(64))
    merged_into_user_id: Mapped[int|None] = mapped_column(
        ForeignKey("users.id", name="fk_users_merged_into", ondelete="RESTRICT"),
        index=True,
    )
    merged_at: Mapped[datetime|None] = mapped_column(DateTime)


class CustomerImportJob(Base):
    __tablename__ = "customer_import_jobs"
    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    namespace: Mapped[str] = mapped_column(String(64))
    source_sha256: Mapped[str] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(320))
    fingerprint: Mapped[str] = mapped_column(String(64))
    payload_encrypted: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="preview")
    result: Mapped[dict|None] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CustomerImportIdentity(Base):
    __tablename__ = "customer_import_identities"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    telegram_digest: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class HistoryImportJob(Base):
    """Preview/apply/rollback journal of a versioned historical import (subscriptions, payments)."""
    __tablename__ = "history_import_jobs"
    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    namespace: Mapped[str] = mapped_column(String(64))
    adapter: Mapped[str] = mapped_column(String(48))
    source_sha256: Mapped[str] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(320))
    fingerprint: Mapped[str] = mapped_column(String(64))
    payload_encrypted: Mapped[str] = mapped_column(Text)
    control: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="preview")
    result: Mapped[dict|None] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    applied_at: Mapped[datetime|None] = mapped_column(DateTime)
    rolled_back_at: Mapped[datetime|None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ImportedPayment(Base):
    """Payment from a previous shop. History only: never fulfilled, refunded or counted as revenue."""
    __tablename__ = "imported_payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_key: Mapped[str] = mapped_column(String(64), unique=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("history_import_jobs.id", ondelete="RESTRICT"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    source_payment_id: Mapped[str] = mapped_column(String(128))
    amount: Mapped[Decimal] = mapped_column(Numeric(12,2))
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(16))
    paid_at: Mapped[datetime|None] = mapped_column(DateTime)
    description: Mapped[str|None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ImportedSubscriptionLink(Base):
    """Source identity and as-imported snapshot of a subscription created by a history import."""
    __tablename__ = "imported_subscription_links"
    source_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("history_import_jobs.id", ondelete="RESTRICT"), index=True)
    subscription_id: Mapped[int] = mapped_column(ForeignKey("subscriptions.id", ondelete="RESTRICT"), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    snapshot: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CustomerBatchOperation(Base):
    __tablename__ = "customer_batch_operations"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Plan(Base):
    __tablename__ = "plans"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(12,2), nullable=False)
    duration_days: Mapped[int] = mapped_column(Integer, nullable=False)
    traffic_limit_gb: Mapped[int|None] = mapped_column(Integer)
    device_limit: Mapped[int|None] = mapped_column(Integer)
    remnawave_profile_id: Mapped[str|None] = mapped_column(String(255))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (UniqueConstraint("user_id", "idempotency_key", name="uq_payments_user_idempotency_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    subscription_id: Mapped[int|None] = mapped_column(Integer, index=True)
    new_subscription: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    plan_id: Mapped[int] = mapped_column(Integer, nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_payment_id: Mapped[str|None] = mapped_column(String(255), unique=True, index=True, nullable=True)
    order_id: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12,2), nullable=False)
    original_amount: Mapped[Decimal|None] = mapped_column(Numeric(12,2))
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(12,2), default=0, nullable=False)
    # Snapshot commercial terms at checkout so later admin edits to a Plan cannot
    # change the entitlement of an already purchased payment.
    duration_days_snapshot: Mapped[int|None] = mapped_column(Integer)
    traffic_limit_gb_snapshot: Mapped[int|None] = mapped_column(Integer)
    device_limit_snapshot: Mapped[int|None] = mapped_column(Integer)
    remnawave_profile_id_snapshot: Mapped[str|None] = mapped_column(String(255))
    referral_terms_snapshot: Mapped[list|None] = mapped_column(JSON)
    referrer_id_snapshot: Mapped[int|None] = mapped_column(Integer, index=True)
    promo_code: Mapped[str|None] = mapped_column(String(64))
    currency: Mapped[str] = mapped_column(String(3), default="RUB", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    fulfillment_status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    fulfillment_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    fulfillment_error: Mapped[str|None] = mapped_column(Text)
    next_retry_at: Mapped[datetime|None] = mapped_column(DateTime)
    fulfillment_max_attempts: Mapped[int] = mapped_column(Integer, default=8, nullable=False)
    fulfillment_terminal: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    idempotency_key: Mapped[str|None] = mapped_column(String(128), index=True)
    purpose: Mapped[str] = mapped_column(String(24), default="subscription", nullable=False)
    reseller_id: Mapped[int|None] = mapped_column(Integer, index=True)
    reseller_slug_snapshot: Mapped[str|None] = mapped_column(String(64))
    reseller_percent_snapshot: Mapped[Decimal|None] = mapped_column(Numeric(5,2))
    bonus_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    checkout_url: Mapped[str|None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    paid_at: Mapped[datetime|None] = mapped_column(DateTime)

class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (Index("uq_subscriptions_primary_user", "user_id", unique=True,
                           postgresql_where=text("is_primary"), sqlite_where=text("is_primary")),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    name: Mapped[str] = mapped_column(String(80), default="Подписка", nullable=False)
    auto_renew_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    next_renewal_at: Mapped[datetime|None] = mapped_column(DateTime)
    plan_id: Mapped[int] = mapped_column(Integer, nullable=False)
    remnawave_uuid: Mapped[str|None] = mapped_column(String(255))
    subscription_url: Mapped[str|None] = mapped_column(Text)
    expires_at: Mapped[datetime|None] = mapped_column(DateTime)
    # Immutable entitlement limits of the currently active subscription.
    # These are copied from the paid/trial grant so later Plan edits cannot
    # silently change an existing customer's device/traffic entitlement.
    traffic_limit_gb_snapshot: Mapped[int|None] = mapped_column(Integer)
    device_limit_snapshot: Mapped[int|None] = mapped_column(Integer)
    remnawave_profile_id_snapshot: Mapped[str|None] = mapped_column(String(255))
    unit_price_per_day: Mapped[Decimal|None] = mapped_column(Numeric(18,8))
    renewal_terms: Mapped[dict|None] = mapped_column(JSON)
    lifecycle_status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    grace_until: Mapped[datetime|None] = mapped_column(DateTime)
    scheduled_cancel_at: Mapped[datetime|None] = mapped_column(DateTime)
    cancelled_at: Mapped[datetime|None] = mapped_column(DateTime)
    last_renewal_failure_at: Mapped[datetime|None] = mapped_column(DateTime)

class TrafficPackage(Base):
    __tablename__ = "traffic_packages"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    traffic_gb: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(12,2), nullable=False)
    plan_id: Mapped[int|None] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

class EntitlementQuote(Base):
    __tablename__ = "entitlement_quotes"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    subscription_id: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12,2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    before: Mapped[dict] = mapped_column(JSON, nullable=False)
    after: Mapped[dict] = mapped_column(JSON, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

class EntitlementOperation(Base):
    __tablename__ = "entitlement_operations"
    id: Mapped[int] = mapped_column(primary_key=True)
    quote_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    payment_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    subscription_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    before: Mapped[dict] = mapped_column(JSON, nullable=False)
    after: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)
    error: Mapped[str|None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at: Mapped[datetime|None] = mapped_column(DateTime)

class AdminUser(Base):
    __tablename__ = "admin_users"
    __table_args__ = (UniqueConstraint("passkey_user_handle", name="uq_admin_passkey_user_handle"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    telegram_id: Mapped[int|None] = mapped_column(BigInteger, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    role: Mapped[str] = mapped_column(String(32), default="viewer", nullable=False)
    passkey_user_handle: Mapped[str|None] = mapped_column(String(64))
    totp_secret_encrypted: Mapped[str|None] = mapped_column(Text)
    recovery_codes_encrypted: Mapped[str|None] = mapped_column(Text)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    disabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    last_login_at: Mapped[datetime|None] = mapped_column(DateTime)

class FinancialLedger(Base):
    __tablename__ = "financial_ledger"
    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    operation_key: Mapped[str] = mapped_column(String(160), unique=True, index=True, nullable=False)
    user_id: Mapped[int|None] = mapped_column(Integer, index=True)
    payment_id: Mapped[int|None] = mapped_column(Integer, index=True)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12,2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    balance_after: Mapped[Decimal|None] = mapped_column(Numeric(12,2))
    metadata_json: Mapped[str|None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    actor: Mapped[str] = mapped_column(String(320), nullable=False, default="system")
    target: Mapped[str|None] = mapped_column(String(200))
    details: Mapped[str|None] = mapped_column(Text)
    request_id: Mapped[str|None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class AppSetting(Base):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="", nullable=False)


class RuntimeSettingState(Base):
    __tablename__ = "runtime_setting_state"
    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class RuntimeSettingChange(Base):
    __tablename__ = "runtime_setting_changes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    base_version: Mapped[int] = mapped_column(Integer, nullable=False)
    target_version: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    keys: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    payload_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    actor: Mapped[str] = mapped_column(String(320), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    source_change_id: Mapped[str | None] = mapped_column(
        ForeignKey(
            "runtime_setting_changes.id",
            name="fk_runtime_setting_change_source",
            ondelete="RESTRICT",
        )
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime)

class BotMenuItem(Base):
    __tablename__ = "bot_menu_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(255), nullable=False)
    item_type: Mapped[str] = mapped_column(String(32), default="webapp", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    parent_id: Mapped[int|None]=mapped_column(ForeignKey('bot_menu_items.id',name='fk_bot_menu_parent',ondelete='RESTRICT'),index=True)
    style: Mapped[str]=mapped_column(String(16),default='default',nullable=False)
    icon_custom_emoji_id: Mapped[str|None]=mapped_column(String(32))
    icon: Mapped[str]=mapped_column(String(16),default='',nullable=False)

class TariffConstructor(Base):
    __tablename__ = "tariff_constructors"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    base_price: Mapped[Decimal] = mapped_column(Numeric(12,2), default=0, nullable=False)
    plan_id: Mapped[int|None] = mapped_column(Integer, index=True)
    remnawave_profile_id: Mapped[str|None] = mapped_column(String(255))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class TariffConstructorOption(Base):
    __tablename__ = "tariff_constructor_options"
    id: Mapped[int] = mapped_column(primary_key=True)
    constructor_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    value: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(12,2), default=0, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class CabinetMenuItem(Base):
    __tablename__ = "cabinet_menu_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), default="custom", nullable=False)
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

class CustomField(Base):
    __tablename__ = "custom_fields"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    field_type: Mapped[str] = mapped_column(String(32), default="text", nullable=False)
    value: Mapped[str] = mapped_column(Text, default="", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

class MenuImage(Base):
    __tablename__ = "menu_images"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Promotion(Base):
    __tablename__ = "promotions"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), default="percent", nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(12,2), nullable=False)
    plan_ids: Mapped[list|None] = mapped_column(JSON, nullable=True)
    starts_at: Mapped[datetime|None] = mapped_column(DateTime)
    ends_at: Mapped[datetime|None] = mapped_column(DateTime)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    exclusive: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

class PromoCode(Base):
    __tablename__ = "promo_codes"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), default="percent", nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(12,2), nullable=False)
    plan_ids: Mapped[list|None] = mapped_column(JSON, nullable=True)
    starts_at: Mapped[datetime|None] = mapped_column(DateTime)
    ends_at: Mapped[datetime|None] = mapped_column(DateTime)
    usage_limit: Mapped[int|None] = mapped_column(Integer)
    reserved_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    used_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    first_purchase_only: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    max_uses_per_user: Mapped[int|None] = mapped_column(Integer)
    min_amount: Mapped[Decimal|None] = mapped_column(Numeric(12,2))
    referral_only: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class GiftCode(Base):
    __tablename__ = "gift_codes"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    plan_id: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_days: Mapped[int|None] = mapped_column(Integer)
    entitlements_snapshot: Mapped[dict|None] = mapped_column(JSON)
    purchase_fingerprint: Mapped[str|None] = mapped_column(String(64))
    purchase_amount: Mapped[Decimal|None] = mapped_column(Numeric(12,2))
    max_uses: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    used_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    expires_at: Mapped[datetime|None] = mapped_column(DateTime)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    purchaser_user_id: Mapped[int|None] = mapped_column(Integer, index=True)
    idempotency_key: Mapped[str|None] = mapped_column(String(128), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

class GiftRedemption(Base):
    __tablename__ = "gift_redemptions"
    __table_args__ = (UniqueConstraint("gift_code_id", "user_id", name="uq_gift_redemption_code_user"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    gift_code_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    subscription_id: Mapped[int|None] = mapped_column(Integer, index=True)
    operation_key: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="processing", nullable=False)
    remote_user_id: Mapped[str|None] = mapped_column(String(255))
    before_snapshot: Mapped[dict|None] = mapped_column(JSON)
    expected_before_expires_at: Mapped[datetime|None] = mapped_column(DateTime)
    expected_after_expires_at: Mapped[datetime|None] = mapped_column(DateTime)
    error: Mapped[str|None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

class Advertisement(Base):
    __tablename__ = "advertisements"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    image_url: Mapped[str|None] = mapped_column(Text)
    button_text: Mapped[str|None] = mapped_column(String(100))
    button_url: Mapped[str|None] = mapped_column(Text)
    starts_at: Mapped[datetime|None] = mapped_column(DateTime)
    ends_at: Mapped[datetime|None] = mapped_column(DateTime)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

class Broadcast(Base):
    __tablename__ = "broadcasts"
    id: Mapped[int] = mapped_column(primary_key=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    image_url: Mapped[str|None] = mapped_column(Text)
    button_text: Mapped[str|None] = mapped_column(String(100))
    button_url: Mapped[str|None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)
    target: Mapped[str] = mapped_column(String(32), default="all", nullable=False)
    sent_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    finished_at: Mapped[datetime|None] = mapped_column(DateTime)

class AuthExchangeCode(Base):
    __tablename__ = "auth_exchange_codes"
    id: Mapped[int] = mapped_column(primary_key=True)
    code_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used_at: Mapped[datetime|None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class BackupJob(Base):
    __tablename__ = "backup_jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)
    filename: Mapped[str|None] = mapped_column(String(255))
    size_bytes: Mapped[int|None] = mapped_column(BigInteger)
    sha256: Mapped[str|None] = mapped_column(String(64))
    encrypted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    error: Mapped[str|None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    finished_at: Mapped[datetime|None] = mapped_column(DateTime)


class AdminSession(Base):
    __tablename__ = "admin_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    admin_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    jti_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    ip: Mapped[str|None] = mapped_column(String(64))
    user_agent: Mapped[str|None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[datetime|None] = mapped_column(DateTime)


class UserSession(Base):
    __tablename__ = "user_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    jti_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    ip: Mapped[str|None] = mapped_column(String(64))
    user_agent: Mapped[str|None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[datetime|None] = mapped_column(DateTime)

class PromoRedemption(Base):
    __tablename__ = "promo_redemptions"
    id: Mapped[int] = mapped_column(primary_key=True)
    promo_code_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    payment_id: Mapped[int] = mapped_column(Integer, unique=True, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

class PromoReservation(Base):
    __tablename__ = "promo_reservations"
    id: Mapped[int] = mapped_column(primary_key=True)
    promo_code_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    order_id: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    payment_id: Mapped[int|None] = mapped_column(Integer, unique=True, index=True)
    status: Mapped[str] = mapped_column(String(16), default="reserved", nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class ReferralReward(Base):
    __tablename__ = "referral_rewards"
    id: Mapped[int] = mapped_column(primary_key=True)
    referrer_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    referred_user_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    payment_id: Mapped[int] = mapped_column(Integer, unique=True, index=True, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12,2), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="credited", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class ReferralLevelReward(Base):
    __tablename__ = "referral_level_rewards"
    __table_args__ = (UniqueConstraint("payment_id", "level", name="uq_referral_level_payment"),
                     UniqueConstraint("payment_id", "referrer_id", name="uq_referral_level_beneficiary"))
    id: Mapped[int] = mapped_column(primary_key=True)
    referrer_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    referred_user_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    payment_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12,2), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="credited", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class ProvisioningOperation(Base):
    __tablename__ = "provisioning_operations"
    id: Mapped[int] = mapped_column(primary_key=True)
    payment_id: Mapped[int] = mapped_column(Integer, unique=True, index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    operation_key: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False, default="provision")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    remote_user_id: Mapped[str|None] = mapped_column(String(255))
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str|None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at: Mapped[datetime|None] = mapped_column(DateTime)
    expected_before_expires_at: Mapped[datetime|None] = mapped_column(DateTime)
    expected_after_expires_at: Mapped[datetime|None] = mapped_column(DateTime)


class PaymentProviderEvent(Base):
    __tablename__ = "payment_provider_events"
    __table_args__ = (UniqueConstraint("provider", "event_id", name="uq_payment_provider_events_provider_event"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    event_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    payment_id: Mapped[int|None] = mapped_column(Integer, index=True)
    status: Mapped[str] = mapped_column(String(32), default="verified", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str|None] = mapped_column(Text)
    processed_at: Mapped[datetime|None] = mapped_column(DateTime)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class ReferralLedger(Base):
    referral_level_reward_id: Mapped[int|None] = mapped_column(ForeignKey("referral_level_rewards.id", ondelete="RESTRICT", name="fk_referral_ledger_level_reward"), index=True)
    __tablename__ = "referral_ledger"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    source_user_id: Mapped[int|None] = mapped_column(Integer, index=True)
    payment_id: Mapped[int|None] = mapped_column(Integer, unique=True, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12,2), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="reward")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class AutoRenewMethod(Base):
    __tablename__ = "auto_renew_methods"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, unique=True, index=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    external_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_attempt_at: Mapped[datetime|None] = mapped_column(DateTime)
    last_success_at: Mapped[datetime|None] = mapped_column(DateTime)
    last_error: Mapped[str|None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_attempt_at: Mapped[datetime|None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class RefundRequest(Base):
    __tablename__ = "refund_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    payment_id: Mapped[int] = mapped_column(Integer, unique=True, index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12,2), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="requested", nullable=False)
    reason: Mapped[str|None] = mapped_column(Text)
    provider_refund_id: Mapped[str|None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

class SupportTicket(Base):
    __table_args__ = (Index("ix_support_tickets_updated","updated_at","id"),)
    __tablename__ = "support_tickets"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="open", nullable=False)
    admin_reply: Mapped[str|None] = mapped_column(Text)
    topology_version: Mapped[int] = mapped_column(Integer,default=0,nullable=False)
    merged_into_id: Mapped[int|None] = mapped_column(ForeignKey("support_tickets.id", ondelete="RESTRICT", name="fk_support_merged_into"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

class SupportMessage(Base):
    __tablename__ = "support_messages"
    __table_args__ = (UniqueConstraint("ticket_id", "role", "idempotency_key", name="uq_support_message_retry"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("support_tickets.id", ondelete="CASCADE"), index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str|None] = mapped_column(String(128))
    delivery_key: Mapped[str|None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

class SupportAttachment(Base):
    __tablename__ = "support_attachments"
    __table_args__ = (UniqueConstraint("ticket_id", "actor", "idempotency_key", name="uq_support_attachment_retry"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("support_tickets.id", ondelete="CASCADE"), index=True, nullable=False)
    message_id: Mapped[int|None] = mapped_column(ForeignKey("support_messages.id", ondelete="CASCADE"), index=True)
    actor: Mapped[str] = mapped_column(String(350), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    mime: Mapped[str] = mapped_column(String(64), nullable=False)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

class WithdrawalRequest(Base):
    __tablename__ = "withdrawal_requests"
    __table_args__ = (UniqueConstraint("user_id", "idempotency_key", name="uq_withdrawal_user_idempotency"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12,2), nullable=False)
    destination: Mapped[str] = mapped_column(String(255), nullable=False)
    idempotency_key: Mapped[str|None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), default="requested", nullable=False)
    admin_note: Mapped[str|None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

class WorkerState(Base):
    __tablename__ = "worker_states"
    id: Mapped[int] = mapped_column(primary_key=True)
    worker_id: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="online", nullable=False)
    current_job: Mapped[str|None] = mapped_column(String(255))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

class ReleaseRecord(Base):
    __tablename__ = "release_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="created", nullable=False)
    rollback_archive: Mapped[str|None] = mapped_column(Text)
    details: Mapped[str|None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at: Mapped[datetime|None] = mapped_column(DateTime)

class SecurityIncident(Base):
    __tablename__ = "security_incidents"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), default="medium", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="open", nullable=False)
    details: Mapped[str|None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    resolved_at: Mapped[datetime|None] = mapped_column(DateTime)

class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_key: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=8, nullable=False)
    next_retry_at: Mapped[datetime|None] = mapped_column(DateTime)
    locked_at: Mapped[datetime|None] = mapped_column(DateTime)
    worker_id: Mapped[str|None] = mapped_column(String(128), index=True)
    error: Mapped[str|None] = mapped_column(Text)
    payload: Mapped[dict|None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at: Mapped[datetime|None] = mapped_column(DateTime)

class FraudSignal(Base):
    __tablename__ = "fraud_signals"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int|None] = mapped_column(Integer, index=True)
    ip: Mapped[str|None] = mapped_column(String(64), index=True)
    fingerprint: Mapped[str|None] = mapped_column(String(128), index=True)
    kind: Mapped[str] = mapped_column(String(64), index=True)
    score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="open", index=True, nullable=False)
    details: Mapped[str|None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    resolved_at: Mapped[datetime|None] = mapped_column(DateTime)

class PayoutTransaction(Base):
    __tablename__ = "payout_transactions"
    id: Mapped[int] = mapped_column(primary_key=True)
    withdrawal_id: Mapped[int] = mapped_column(Integer, unique=True, index=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(32), default="manual", nullable=False)
    external_id: Mapped[str|None] = mapped_column(String(255), unique=True, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12,2), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="processing", index=True, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str|None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    paid_at: Mapped[datetime|None] = mapped_column(DateTime)

class FeatureFlag(Base):
    __tablename__ = "feature_flags"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)



class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (UniqueConstraint("user_id", "dedupe_key", name="uq_notifications_user_dedupe"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    channel: Mapped[str] = mapped_column(String(24), default="in_app", nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True, nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(160), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str|None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    read_at: Mapped[datetime|None] = mapped_column(DateTime)
    sent_at: Mapped[datetime|None] = mapped_column(DateTime)
    # Set when the push worker has created PushDelivery rows (or decided not to).
    push_fanout_at: Mapped[datetime|None] = mapped_column(DateTime, index=True)


class PushDevice(Base):
    """A mobile app installation that receives native push for one signed-in session."""
    __tablename__ = "push_devices"
    __table_args__ = (UniqueConstraint("token_hash", name="uq_push_devices_token_hash"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    session_id: Mapped[int|None] = mapped_column(ForeignKey("user_sessions.id", ondelete="SET NULL"), index=True)
    platform: Mapped[str] = mapped_column(String(16), nullable=False)
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    app_version: Mapped[str|None] = mapped_column(String(32))
    locale: Mapped[str|None] = mapped_column(String(8))
    failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    revoked_at: Mapped[datetime|None] = mapped_column(DateTime, index=True)
    revoke_reason: Mapped[str|None] = mapped_column(String(32))


class PushDelivery(Base):
    """Per-device delivery attempt state of one notification."""
    __tablename__ = "push_deliveries"
    __table_args__ = (UniqueConstraint("notification_id", "device_id", name="uq_push_deliveries_notification_device"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    notification_id: Mapped[int] = mapped_column(ForeignKey("notifications.id", ondelete="CASCADE"), index=True, nullable=False)
    device_id: Mapped[int] = mapped_column(ForeignKey("push_devices.id", ondelete="CASCADE"), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True, nullable=False)
    last_error: Mapped[str|None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    sent_at: Mapped[datetime|None] = mapped_column(DateTime)


class StatusComponent(Base):
    __tablename__ = "status_components"
    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="operational", nullable=False)
    message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class Deployment(Base):
    __tablename__ = "deployments"
    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    previous_version: Mapped[str|None] = mapped_column(String(64))
    strategy: Mapped[str] = mapped_column(String(24), default="canary", nullable=False)
    traffic_percent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="planned", index=True, nullable=False)
    error_rate_percent: Mapped[Decimal] = mapped_column(Numeric(6,3), default=0, nullable=False)
    rollback_reason: Mapped[str|None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at: Mapped[datetime|None] = mapped_column(DateTime)

class PaymentProviderHealth(Base):
    __tablename__ = "payment_provider_health"
    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    success_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_latency_ms: Mapped[int|None] = mapped_column(Integer)
    last_error: Mapped[str|None] = mapped_column(Text)
    circuit_open_until: Mapped[datetime|None] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

class SecurityIncidentEvent(Base):
    __tablename__ = "security_incident_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    severity: Mapped[str] = mapped_column(String(16), default="medium", nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    details: Mapped[str|None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="open", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    resolved_at: Mapped[datetime|None] = mapped_column(DateTime)

class BackupVerification(Base):
    __tablename__ = "backup_verifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    backup_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)
    checksum_ok: Mapped[bool|None] = mapped_column(Boolean)
    archive_safe: Mapped[bool|None] = mapped_column(Boolean)
    restore_tested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    error: Mapped[str|None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    finished_at: Mapped[datetime|None] = mapped_column(DateTime)

class WebAuthnCredential(Base):
    __tablename__ = "webauthn_credentials"
    id: Mapped[int] = mapped_column(primary_key=True)
    admin_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    credential_id: Mapped[str] = mapped_column(String(1024), unique=True, index=True, nullable=False)
    public_key: Mapped[str] = mapped_column(Text, nullable=False)
    sign_count: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    transports: Mapped[str|None] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(100), default="Passkey", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    last_used_at: Mapped[datetime|None] = mapped_column(DateTime)


class UserDevice(Base):
    __tablename__ = "user_devices"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    subscription_id: Mapped[int|None] = mapped_column(Integer, index=True)
    device_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), default="Устройство", nullable=False)
    platform: Mapped[str|None] = mapped_column(String(64))
    last_ip: Mapped[str|None] = mapped_column(String(64))
    last_seen_at: Mapped[datetime|None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    revoked_at: Mapped[datetime|None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

class Campaign(Base):
    __tablename__ = "campaigns"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), default="broadcast", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False, index=True)
    audience: Mapped[dict|None] = mapped_column(JSON)
    content: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    starts_at: Mapped[datetime|None] = mapped_column(DateTime)
    ends_at: Mapped[datetime|None] = mapped_column(DateTime)
    sent_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

class AutomationRule(Base):
    __tablename__ = "automation_rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    event: Mapped[str] = mapped_column(String(64), nullable=False)
    conditions: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    actions: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    last_run_at: Mapped[datetime|None] = mapped_column(DateTime)
    run_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

class MonitoringCheck(Base):
    __tablename__ = "monitoring_checks"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    method: Mapped[str] = mapped_column(String(8), default="GET", nullable=False)
    interval_seconds: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_status: Mapped[str|None] = mapped_column(String(32))
    last_latency_ms: Mapped[int|None] = mapped_column(Integer)
    last_error: Mapped[str|None] = mapped_column(Text)
    last_checked_at: Mapped[datetime|None] = mapped_column(DateTime)
    failure_streak: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

class TrialGrant(Base):
    __tablename__ = "trial_grants"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, unique=True, index=True, nullable=False)
    subscription_id: Mapped[int|None] = mapped_column(Integer, index=True)
    plan_id: Mapped[int] = mapped_column(Integer, nullable=False)
    days: Mapped[int] = mapped_column(Integer, nullable=False)
    # Freeze trial entitlement at claim time. Later admin edits to Plan must not
    # change a grant that has already been promised to the user.
    traffic_limit_gb_snapshot: Mapped[int|None] = mapped_column(Integer)
    device_limit_snapshot: Mapped[int|None] = mapped_column(Integer)
    remnawave_profile_id_snapshot: Mapped[str|None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    granted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at: Mapped[datetime|None] = mapped_column(DateTime)
    expected_before_expires_at: Mapped[datetime|None] = mapped_column(DateTime)
    expected_after_expires_at: Mapped[datetime|None] = mapped_column(DateTime)


class ConnectionObservation(Base):
    __tablename__ = "connection_observations"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int|None] = mapped_column(Integer, index=True)
    remnawave_uuid: Mapped[str|None] = mapped_column(String(64), index=True)
    ip: Mapped[str] = mapped_column(String(64), nullable=False)
    prefix: Mapped[str] = mapped_column(String(80), nullable=False)
    asn: Mapped[str|None] = mapped_column(String(32))
    asn_org: Mapped[str|None] = mapped_column(String(255))
    country: Mapped[str|None] = mapped_column(String(16))
    lat: Mapped[float|None] = mapped_column(Numeric(8, 5))
    lon: Mapped[float|None] = mapped_column(Numeric(8, 5))
    user_agent: Mapped[str|None] = mapped_column(String(255))
    hwid: Mapped[str|None] = mapped_column(String(128), index=True)
    mobile: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    torrent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class AbuseViolation(Base):
    __tablename__ = "abuse_violations"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int|None] = mapped_column(Integer, index=True)
    score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    recommendation: Mapped[str] = mapped_column(String(32), default="observe", nullable=False)
    analyzers: Mapped[dict|None] = mapped_column(JSON)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="open", index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    reviewed_at: Mapped[datetime|None] = mapped_column(DateTime)


class DeviceBlacklist(Base):
    __tablename__ = "device_blacklist"
    id: Mapped[int] = mapped_column(primary_key=True)
    hwid: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    action: Mapped[str] = mapped_column(String(16), default="alert", nullable=False)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class NodeAgent(Base):
    __tablename__ = "node_agents"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    cpu: Mapped[str|None] = mapped_column(String(32))
    mem: Mapped[str|None] = mapped_column(String(32))
    disk: Mapped[str|None] = mapped_column(String(32))
    xray_ok: Mapped[bool|None] = mapped_column(Boolean)
    version: Mapped[str|None] = mapped_column(String(32))
    last_seen_at: Mapped[datetime|None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class AgentAction(Base):
    __tablename__ = "agent_actions"
    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict|None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class ShopApiKey(Base):
    __tablename__ = "shop_api_keys"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    prefix: Mapped[str] = mapped_column(String(24), nullable=False)
    secret_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    scopes: Mapped[str] = mapped_column(String(255), default="read", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_used_at: Mapped[datetime|None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class OutboundWebhook(Base):
    __tablename__ = "outbound_webhooks"
    id: Mapped[int] = mapped_column(primary_key=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    secret_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    events: Mapped[str] = mapped_column(String(255), default="abuse.scored", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_status: Mapped[str|None] = mapped_column(String(32))
    last_error: Mapped[str|None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class PlatformPlugin(Base):
    __tablename__ = "platform_plugins"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)

class Reseller(Base):
    __tablename__ = "resellers"
    __table_args__ = (UniqueConstraint("owner_user_id", name="uq_reseller_owner"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_user_id: Mapped[int|None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT", name="fk_reseller_owner"))
    balance: Mapped[Decimal] = mapped_column(Numeric(14,2), default=0, nullable=False)
    balance_currency: Mapped[str|None] = mapped_column(String(3))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    api_key_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    commission_percent: Mapped[Decimal] = mapped_column(Numeric(5,2), default=20, nullable=False)
    plan_ids: Mapped[list|None] = mapped_column(JSON)
    branding: Mapped[dict|None] = mapped_column(JSON)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    last_used_at: Mapped[datetime|None] = mapped_column(DateTime)


class PaymentTaxProfile(Base):
    __tablename__ = "payment_tax_profiles"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, unique=True, index=True, nullable=False)
    country: Mapped[str] = mapped_column(String(2), default="DE", nullable=False)
    vat_id: Mapped[str|None] = mapped_column(String(64))
    business_name: Mapped[str|None] = mapped_column(String(255))
    tax_exempt: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reverse_charge: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

class PaymentInvoice(Base):
    __tablename__ = "payment_invoices"
    id: Mapped[int] = mapped_column(primary_key=True)
    payment_id: Mapped[int] = mapped_column(Integer, unique=True, index=True, nullable=False)
    invoice_number: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12,2), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(12,2), default=0, nullable=False)
    total: Mapped[Decimal] = mapped_column(Numeric(12,2), nullable=False)
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(6,3), default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="issued", nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

class PaymentChargeback(Base):
    __tablename__ = "payment_chargebacks"
    id: Mapped[int] = mapped_column(primary_key=True)
    payment_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12,2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="open", index=True, nullable=False)
    reason: Mapped[str|None] = mapped_column(Text)
    evidence: Mapped[dict|None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

class PaymentRiskAssessment(Base):
    __tablename__ = "payment_risk_assessments"
    id: Mapped[int] = mapped_column(primary_key=True)
    payment_id: Mapped[int] = mapped_column(Integer, unique=True, index=True, nullable=False)
    score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    decision: Mapped[str] = mapped_column(String(24), default="allow", nullable=False)
    signals: Mapped[dict|None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

class PaymentProviderMetric(Base):
    __tablename__ = "payment_provider_metrics"
    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    day: Mapped[str] = mapped_column(String(10), index=True, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    succeeded: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    refunded: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(14,2), default=0, nullable=False)
    fees_amount: Mapped[Decimal] = mapped_column(Numeric(14,2), default=0, nullable=False)
    net_amount: Mapped[Decimal] = mapped_column(Numeric(14,2), default=0, nullable=False)

class GiftCard(Base):
    __tablename__ = "gift_cards"
    id: Mapped[int] = mapped_column(primary_key=True)
    code_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    code_prefix: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(12,2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="EUR", nullable=False)
    balance: Mapped[Decimal] = mapped_column(Numeric(12,2), nullable=False)
    expires_at: Mapped[datetime|None] = mapped_column(DateTime)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

class CorporateAccount(Base):
    __tablename__ = "corporate_accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    vat_id: Mapped[str|None] = mapped_column(String(64))
    country: Mapped[str] = mapped_column(String(2), default="DE", nullable=False)
    payment_terms_days: Mapped[int] = mapped_column(Integer, default=14, nullable=False)
    credit_limit: Mapped[Decimal] = mapped_column(Numeric(14,2), default=0, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

class PaymentPriceExperiment(Base):
    __tablename__ = "payment_price_experiments"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    rules: Mapped[dict|None] = mapped_column(JSON)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

class SupportImportLink(Base):
    __tablename__ = 'support_import_links'
    completed: Mapped[bool] = mapped_column(Boolean,default=False,nullable=False)
    source_key: Mapped[str] = mapped_column(String(80),primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey('support_tickets.id',ondelete='CASCADE'),unique=True,nullable=False)

class AccountAction(Base):
    __tablename__='account_actions'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id',ondelete='CASCADE'),index=True,nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64),unique=True,nullable=False)
    purpose: Mapped[str] = mapped_column(String(24),nullable=False)
    email: Mapped[str] = mapped_column(String(320),nullable=False)
    password_fingerprint: Mapped[str|None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime,default=datetime.utcnow,nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime,nullable=False)
    used_at: Mapped[datetime|None] = mapped_column(DateTime)

class AccountMail(Base):
    __tablename__='account_mail'
    id: Mapped[int] = mapped_column(primary_key=True)
    action_id: Mapped[int] = mapped_column(ForeignKey('account_actions.id',ondelete='CASCADE'),unique=True,nullable=False)
    token_encrypted: Mapped[str] = mapped_column(Text,nullable=False)
    status: Mapped[str] = mapped_column(String(16),default='queued',nullable=False)
    attempts: Mapped[int] = mapped_column(Integer,default=0,nullable=False)
    next_retry_at: Mapped[datetime] = mapped_column(DateTime,default=datetime.utcnow,nullable=False)
    error: Mapped[str|None] = mapped_column(String(40))


class AccountMergeAlias(Base):
    __tablename__ = 'account_merge_aliases'
    id: Mapped[int] = mapped_column(primary_key=True)
    source_user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), unique=True, index=True)
    target_user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), index=True)
    telegram_id: Mapped[int|None] = mapped_column(BigInteger, unique=True, index=True)
    yandex_id: Mapped[str|None] = mapped_column(String(255), unique=True, index=True)
    vk_id: Mapped[str|None] = mapped_column(String(255), unique=True, index=True)
    email: Mapped[str|None] = mapped_column(String(320), unique=True, index=True)
    email_password_hash: Mapped[str|None] = mapped_column(String(512))
    email_verified_at: Mapped[datetime|None] = mapped_column(DateTime)
    referral_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    merged_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class AccountMergeAuthorization(Base):
    __tablename__ = 'account_merge_authorizations'
    id: Mapped[int] = mapped_column(primary_key=True)
    source_user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    used_at: Mapped[datetime|None] = mapped_column(DateTime)
    target_user_id: Mapped[int|None] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class AccountMergeOperation(Base):
    __tablename__ = 'account_merge_operations'
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    authorization_id: Mapped[int] = mapped_column(ForeignKey('account_merge_authorizations.id', ondelete='RESTRICT'))
    source_user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), index=True)
    target_user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), index=True)
    result: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

class Survey(Base):
    __tablename__='surveys'
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255),nullable=False)
    description: Mapped[str] = mapped_column(Text,default='',nullable=False)
    questions: Mapped[list] = mapped_column(JSON,nullable=False)
    state: Mapped[str] = mapped_column(String(16),default='draft',nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime,nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime,nullable=False)
    max_responses: Mapped[int] = mapped_column(Integer,nullable=False)
    response_count: Mapped[int] = mapped_column(Integer,default=0,nullable=False)
    reward_amount: Mapped[Decimal] = mapped_column(Numeric(12,2),default=0,nullable=False)
    currency: Mapped[str] = mapped_column(String(3),nullable=False)
    require_verified_email: Mapped[bool] = mapped_column(Boolean,default=False,nullable=False)
    require_subscription: Mapped[bool] = mapped_column(Boolean,default=False,nullable=False)
    results_mode: Mapped[str] = mapped_column(String(16),default='after_vote',nullable=False)
    statistics: Mapped[dict] = mapped_column(JSON,default=dict,nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime,default=datetime.utcnow,nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime,default=datetime.utcnow,nullable=False)

class SurveyResponse(Base):
    __tablename__='survey_responses'
    __table_args__=(UniqueConstraint('survey_id','user_id',name='uq_survey_responses_owner'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    survey_id: Mapped[int] = mapped_column(ForeignKey('surveys.id',ondelete='RESTRICT'),nullable=False,index=True)
    user_id: Mapped[int|None] = mapped_column(ForeignKey('users.id',ondelete='SET NULL'),index=True)
    answers: Mapped[list] = mapped_column(JSON,nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64),nullable=False)
    reward_amount: Mapped[Decimal] = mapped_column(Numeric(12,2),nullable=False)
    currency: Mapped[str] = mapped_column(String(3),nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime,default=datetime.utcnow,nullable=False)

class Giveaway(Base):
    __tablename__ = 'giveaways'
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default='', nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    state: Mapped[str] = mapped_column(String(16), default='draft', nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    max_entries: Mapped[int] = mapped_column(Integer, nullable=False)
    entry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    winners_count: Mapped[int] = mapped_column(Integer, nullable=False)
    prizes: Mapped[list] = mapped_column(JSON, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    budget_limit: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    budget_credited: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    require_subscription: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    drawn_at: Mapped[datetime|None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

class GiveawayEntry(Base):
    __tablename__ = 'giveaway_entries'
    __table_args__ = (UniqueConstraint('giveaway_id', 'user_id', name='uq_giveaway_entries_owner'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    giveaway_id: Mapped[int] = mapped_column(ForeignKey('giveaways.id', ondelete='RESTRICT'), index=True, nullable=False)
    user_id: Mapped[int|None] = mapped_column(ForeignKey('users.id', ondelete='SET NULL'), index=True)
    outcome: Mapped[str] = mapped_column(String(16), default='entered', nullable=False)
    prize_index: Mapped[int|None] = mapped_column(Integer)
    reward_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class WebAuthnChallenge(Base):
    __tablename__ = "webauthn_challenges"
    ticket_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    binding_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    purpose: Mapped[str] = mapped_column(String(24), nullable=False)
    admin_id: Mapped[int|None] = mapped_column(Integer, ForeignKey("admin_users.id", ondelete="CASCADE"))
    challenge: Mapped[str] = mapped_column(String(128), nullable=False)
    context: Mapped[dict] = mapped_column(JSON, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)


class CustomerPasskey(Base):
    __tablename__ = "customer_passkeys"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    credential_id: Mapped[str] = mapped_column(String(1024), unique=True)
    public_key: Mapped[str] = mapped_column(Text)
    user_handle: Mapped[str|None] = mapped_column(String(64))
    sign_count: Mapped[int] = mapped_column(BigInteger, default=0)
    name: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_used_at: Mapped[datetime|None] = mapped_column(DateTime)

class CustomerPasskeyChallenge(Base):
    __tablename__ = "customer_passkey_challenges"
    ticket_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    binding_hash: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[int|None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    purpose: Mapped[str] = mapped_column(String(24))
    challenge: Mapped[str] = mapped_column(String(128))
    context: Mapped[dict] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)


class SupportTopologyOperation(Base):
    __tablename__ = "support_topology_operations"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PartnerCommission(Base):
    __tablename__ = "partner_commissions"
    id: Mapped[int] = mapped_column(primary_key=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey("payments.id", ondelete="RESTRICT"), unique=True)
    reseller_id: Mapped[int] = mapped_column(ForeignKey("resellers.id", ondelete="RESTRICT"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14,2))
    currency: Mapped[str] = mapped_column(String(3))
    percent: Mapped[Decimal] = mapped_column(Numeric(5,2))
    status: Mapped[str] = mapped_column(String(16), default="credited")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    reversed_at: Mapped[datetime|None] = mapped_column(DateTime)

class PartnerWithdrawal(Base):
    __tablename__ = "partner_withdrawals"
    __table_args__ = (UniqueConstraint("reseller_id", "idempotency_key", name="uq_partner_withdrawal_retry"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    reseller_id: Mapped[int] = mapped_column(ForeignKey("resellers.id", ondelete="RESTRICT"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    amount: Mapped[Decimal] = mapped_column(Numeric(14,2))
    currency: Mapped[str] = mapped_column(String(3))
    destination: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default="requested")
    reference: Mapped[str|None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ContentPage(Base):
    __tablename__='content_pages'
    __table_args__=(UniqueConstraint('slug','locale',name='uq_content_page_slug_locale'),)
    id: Mapped[int]=mapped_column(primary_key=True)
    slug: Mapped[str]=mapped_column(String(80))
    locale: Mapped[str]=mapped_column(String(2))
    kind: Mapped[str]=mapped_column(String(16))
    version: Mapped[int]=mapped_column(Integer,default=1)
    draft: Mapped[dict]=mapped_column(JSON)
    published_revision: Mapped[int|None]=mapped_column(Integer)
    archived: Mapped[bool]=mapped_column(Boolean,default=False)
    created_at: Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)
    updated_at: Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)


class ContentRevision(Base):
    __tablename__='content_revisions'
    __table_args__=(UniqueConstraint('page_id','version',name='uq_content_revision_version'),)
    id: Mapped[int]=mapped_column(primary_key=True)
    page_id: Mapped[int]=mapped_column(ForeignKey('content_pages.id',ondelete='RESTRICT'),index=True)
    version: Mapped[int]=mapped_column(Integer)
    snapshot: Mapped[dict]=mapped_column(JSON)
    actor: Mapped[str]=mapped_column(String(320))
    starts_at: Mapped[datetime|None]=mapped_column(DateTime)
    ends_at: Mapped[datetime|None]=mapped_column(DateTime)
    created_at: Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)


class PromoGroup(Base):
    __tablename__='promo_groups'
    id: Mapped[int]=mapped_column(primary_key=True)
    name: Mapped[str]=mapped_column(String(200))
    segment: Mapped[str]=mapped_column(String(16))
    enabled: Mapped[bool]=mapped_column(Boolean,default=True)
    version: Mapped[int]=mapped_column(Integer,default=1)


class PromoGroupMember(Base):
    __tablename__='promo_group_members'
    group_id: Mapped[int]=mapped_column(ForeignKey('promo_groups.id',ondelete='RESTRICT'),primary_key=True)
    user_id: Mapped[int]=mapped_column(ForeignKey('users.id',ondelete='RESTRICT'),primary_key=True)


class PromoAudience(Base):
    __tablename__='promo_audiences'
    promo_id: Mapped[int]=mapped_column(ForeignKey('promo_codes.id',ondelete='RESTRICT'),primary_key=True)
    title: Mapped[str]=mapped_column(String(200))
    description: Mapped[str]=mapped_column(Text,default='')
    group_id: Mapped[int|None]=mapped_column(ForeignKey('promo_groups.id',ondelete='RESTRICT'))
    user_ids: Mapped[list]=mapped_column(JSON,default=list)
    enabled: Mapped[bool]=mapped_column(Boolean,default=True)
    version: Mapped[int]=mapped_column(Integer,default=1)


class PluginPublisher(Base):
    """Trusted Ed25519 publisher key; only packages signed by an active key install."""
    __tablename__ = "plugin_publishers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    public_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    revoked_at: Mapped[datetime|None] = mapped_column(DateTime)


class PluginPackage(Base):
    """One uploaded, signature-verified version of a plugin (manifest only, no code)."""
    __tablename__ = "plugin_packages"
    __table_args__ = (UniqueConstraint("plugin_id", "version", name="uq_plugin_packages_version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    plugin_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    manifest: Mapped[dict] = mapped_column(JSON, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    publisher_fingerprint: Mapped[str] = mapped_column(String(16), nullable=False)
    uploaded_by: Mapped[str] = mapped_column(String(320), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class PluginInstall(Base):
    """Lifecycle of an installed plugin: active version, approved capabilities, credentials."""
    __tablename__ = "plugin_installs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    state: Mapped[str] = mapped_column(String(16), default="installed", nullable=False)
    active_version: Mapped[str|None] = mapped_column(String(32))
    approved_capabilities: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    approved_events: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    settings_encrypted: Mapped[str|None] = mapped_column(Text)
    token_hash: Mapped[str|None] = mapped_column(String(64), unique=True)
    signing_secret_encrypted: Mapped[str|None] = mapped_column(Text)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str|None] = mapped_column(String(255))
    disabled_reason: Mapped[str|None] = mapped_column(String(255))
    enabled_at: Mapped[datetime|None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class PluginDelivery(Base):
    """Signed event delivery to a plugin endpoint, retried with backoff and deduplicated."""
    __tablename__ = "plugin_deliveries"
    __table_args__ = (UniqueConstraint("plugin_id", "event_key", name="uq_plugin_deliveries_event"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    plugin_id: Mapped[str] = mapped_column(ForeignKey("plugin_installs.id", ondelete="CASCADE"), index=True, nullable=False)
    event: Mapped[str] = mapped_column(String(64), nullable=False)
    event_key: Mapped[str] = mapped_column(String(120), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True, nullable=False)
    last_error: Mapped[str|None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    sent_at: Mapped[datetime|None] = mapped_column(DateTime)


class PluginEventCursor(Base):
    """Outbox scan position per event source (users, notifications)."""
    __tablename__ = "plugin_event_cursors"
    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    last_id: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class NetworkIntel(Base):
    """Cached lookup of one IP from one source (ASN/registry or reputation) with freshness."""
    __tablename__ = "network_intel"
    __table_args__ = (UniqueConstraint("ip", "source", name="uq_network_intel_ip_source"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    ip: Mapped[str] = mapped_column(String(45), index=True, nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    data: Mapped[dict|None] = mapped_column(JSON)
    fetched_at: Mapped[datetime|None] = mapped_column(DateTime)
    expires_at: Mapped[datetime|None] = mapped_column(DateTime, index=True)
    error: Mapped[str|None] = mapped_column(String(255))
    error_at: Mapped[datetime|None] = mapped_column(DateTime)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_attempt_at: Mapped[datetime|None] = mapped_column(DateTime)


class NetworkIntelSourceState(Base):
    """Per-source rate-limit window and backoff after HTTP 429."""
    __tablename__ = "network_intel_sources"
    source: Mapped[str] = mapped_column(String(16), primary_key=True)
    window_start: Mapped[datetime|None] = mapped_column(DateTime)
    used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    blocked_until: Mapped[datetime|None] = mapped_column(DateTime)
    last_error: Mapped[str|None] = mapped_column(String(255))


class DmarcReport(Base):
    """One DMARC aggregate report (RFC 7489 appendix C) about the shop's mail domain."""
    __tablename__ = "dmarc_reports"
    __table_args__ = (UniqueConstraint("org_name", "report_id", name="uq_dmarc_reports_org_report"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    org_name: Mapped[str] = mapped_column(String(255), nullable=False)
    report_id: Mapped[str] = mapped_column(String(255), nullable=False)
    reporter_email: Mapped[str|None] = mapped_column(String(255))
    sender_matches: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    policy: Mapped[str|None] = mapped_column(String(16))
    pct: Mapped[int|None] = mapped_column(Integer)
    date_begin: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    date_end: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    messages: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    passed: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    failed: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)


class DmarcRecord(Base):
    """One row of an aggregate report: messages from one source IP with one result."""
    __tablename__ = "dmarc_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    report_row_id: Mapped[int] = mapped_column(ForeignKey("dmarc_reports.id", ondelete="CASCADE"), index=True, nullable=False)
    source_ip: Mapped[str] = mapped_column(String(45), index=True, nullable=False)
    count: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    disposition: Mapped[str|None] = mapped_column(String(16))
    dkim: Mapped[str|None] = mapped_column(String(8))
    spf: Mapped[str|None] = mapped_column(String(8))
    header_from: Mapped[str|None] = mapped_column(String(255))
    dkim_domain: Mapped[str|None] = mapped_column(String(255))
    dkim_result: Mapped[str|None] = mapped_column(String(16))
    spf_domain: Mapped[str|None] = mapped_column(String(255))
    spf_result: Mapped[str|None] = mapped_column(String(16))


class DmarcIntakeState(Base):
    """Read-only IMAP cursor of the DMARC report mailbox and the intake journal."""
    __tablename__ = "dmarc_intake_state"
    mailbox: Mapped[str] = mapped_column(String(64), primary_key=True)
    uidvalidity: Mapped[int|None] = mapped_column(BigInteger)
    last_uid: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    last_success: Mapped[datetime|None] = mapped_column(DateTime)
    last_error: Mapped[str|None] = mapped_column(String(255))
    last_error_at: Mapped[datetime|None] = mapped_column(DateTime)
    imported: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duplicates: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rejected: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    journal: Mapped[list|None] = mapped_column(JSON)
