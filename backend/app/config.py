"""
Конфигурация приложения.

Все значения читаются из переменных окружения или из файла .env
(см. .env.example).
"""
from __future__ import annotations

from typing import List

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки приложения."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------- Приложение ----------
    app_secret: str = Field(default="change-me", alias="APP_SECRET")
    app_secret_previous: str = Field(default="", alias="APP_SECRET_PREVIOUS")
    app_env: str = Field(default="production", alias="APP_ENV")
    default_language: str = Field(default="ru", alias="DEFAULT_LANGUAGE")
    tz: str = Field(default="Europe/Moscow", alias="TZ")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    trusted_proxy_cidrs: str = Field(default="", alias="TRUSTED_PROXY_CIDRS")
    cabinet_cors_origins: str = Field(default="", alias="CABINET_CORS_ORIGINS")

    support_bridge_token: str = Field(default="", alias="SUPPORT_BRIDGE_TOKEN")

    # ---------- PostgreSQL ----------
    db_user: str = Field(default="vpnshop", alias="DB_USER")
    db_password: str = Field(default="change-me", alias="DB_PASSWORD")
    db_name: str = Field(default="vpnshop", alias="DB_NAME")
    database_url: str = Field(
        default="postgresql+asyncpg://vpnshop:change-me@db:5432/vpnshop",
        alias="DATABASE_URL",
    )

    # ---------- Redis ----------
    redis_url: str = Field(default="redis://redis:6379/0", alias="REDIS_URL")
    redis_password: str = Field(default="", alias="REDIS_PASSWORD")

    # ---------- Telegram ----------
    bot_token: str = Field(default="", alias="BOT_TOKEN")
    bot_username: str = Field(default="", alias="BOT_USERNAME")
    admin_telegram_id: int = Field(default=0, alias="ADMIN_TELEGRAM_ID")

    # ---------- Remnawave ----------
    remnawave_url: str = Field(default="", alias="REMNAWAVE_URL")
    remnawave_token: str = Field(default="", alias="REMNAWAVE_TOKEN")
    remnawave_cb_failures: int = Field(default=5, alias="REMNAWAVE_CB_FAILURES")
    remnawave_cb_cooldown: int = Field(default=30, alias="REMNAWAVE_CB_COOLDOWN")
    # Remnawave WEBHOOK_SECRET_HEADER: verifies X-Remnawave-Signature of /api/webhooks/remnawave.
    remnawave_webhook_secret: str = Field(default="", alias="REMNAWAVE_WEBHOOK_SECRET")

    # ---------- Админ-панель ----------
    customer_webauthn_origin: str = Field(default="", alias="CUSTOMER_WEBAUTHN_ORIGIN")
    # Native passkeys in the customer apps: the cabinet domain publishes
    # /.well-known/assetlinks.json and apple-app-site-association from these values.
    android_user_package: str = Field(default="shop.remnawave.user", alias="ANDROID_USER_PACKAGE")
    android_user_cert_sha256: str = Field(default="", alias="ANDROID_USER_CERT_SHA256")
    ios_user_app_id: str = Field(default="", alias="IOS_USER_APP_ID")
    webauthn_origin: str = Field(default="", alias="WEBAUTHN_ORIGIN")
    admin_email: str = Field(default="admin@example.com", alias="ADMIN_EMAIL")
    admin_password: str = Field(default="change-me", alias="ADMIN_PASSWORD")
    admin_cors_origins: str = Field(
        default="", alias="ADMIN_CORS_ORIGINS"
    )
    public_base_url: str = Field(
        default="https://api.example.com", alias="PUBLIC_BASE_URL"
    )
    mini_app_url: str = Field(
        default="https://app.example.com", alias="MINI_APP_URL"
    )
    cookie_secure: bool = Field(default=True, alias="COOKIE_SECURE")
    cookie_samesite: str = Field(default="none", alias="COOKIE_SAMESITE")

    # ---------- Домены ----------
    admin_domain: str = Field(default="localhost", alias="ADMIN_DOMAIN")
    app_domain: str = Field(default="localhost", alias="APP_DOMAIN")
    api_domain: str = Field(default="localhost", alias="API_DOMAIN")
    # Reserve API domains served by the same backend (mobile domain rotation, docs/modules/anti_blocking.md).
    api_mirror_domains: str = Field(default="", alias="API_MIRROR_DOMAINS")

    def api_domains(self) -> list[str]:
        """The API domain and its reserve domains, as the apps may reach them."""
        return [self.api_domain, *[d.strip().lower() for d in self.api_mirror_domains.replace(",", " ").split() if d.strip()]]
    miniapp_domain: str = Field(default="localhost", alias="MINIAPP_DOMAIN")
    cabinet_domain: str = Field(default="localhost", alias="CABINET_DOMAIN")
    bot_domain: str = Field(default="localhost", alias="BOT_DOMAIN")
    webhook_domain: str = Field(default="localhost", alias="WEBHOOK_DOMAIN")
    panel_domain: str = Field(default="localhost", alias="PANEL_DOMAIN")
    caddy_email: str = Field(
        default="admin@example.com", alias="CADDY_EMAIL"
    )
    caddy_http_port: int = Field(default=80, alias="CADDY_HTTP_PORT")
    caddy_https_port: int = Field(default=443, alias="CADDY_HTTPS_PORT")

    # ---------- Валюта и цены ----------
    default_currency: str = Field(default="RUB", alias="DEFAULT_CURRENCY")
    price_1: int = Field(default=199, alias="PRICE_1")
    price_3: int = Field(default=499, alias="PRICE_3")
    price_6: int = Field(default=899, alias="PRICE_6")
    price_12: int = Field(default=1499, alias="PRICE_12")

    # ---------- YooKassa ----------
    yookassa_api_url: str = Field(
        default="https://api.yookassa.ru", alias="YOOKASSA_API_URL"
    )
    yookassa_shop_id: str = Field(default="", alias="YOOKASSA_SHOP_ID")
    yookassa_secret_key: str = Field(
        default="", alias="YOOKASSA_SECRET_KEY"
    )
    yookassa_webhook_ip_allowlist: str = Field(
        default="", alias="YOOKASSA_WEBHOOK_IP_ALLOWLIST"
    )

    # ---------- Platega ----------
    platega_api_url: str = Field(
        default="https://app.platega.io", alias="PLATEGA_API_URL"
    )
    platega_merchant_id: str = Field(
        default="", alias="PLATEGA_MERCHANT_ID"
    )
    platega_secret: str = Field(default="", alias="PLATEGA_SECRET")
    platega_refund_url: str = Field(
        default="", alias="PLATEGA_REFUND_URL"
    )
    platega_refund_status_url: str = Field(
        default="", alias="PLATEGA_REFUND_STATUS_URL"
    )

    # ---------- RollyPay ----------
    rollypay_api_url: str = Field(
        default="https://rollypay.io", alias="ROLLYPAY_API_URL"
    )
    rollypay_api_key: str = Field(default="", alias="ROLLYPAY_API_KEY")
    rollypay_signing_secret: str = Field(
        default="", alias="ROLLYPAY_SIGNING_SECRET"
    )
    rollypay_test_mode: bool = Field(
        default=False, alias="ROLLYPAY_TEST_MODE"
    )
    rollypay_refund_url: str = Field(
        default="", alias="ROLLYPAY_REFUND_URL"
    )
    rollypay_refund_status_url: str = Field(
        default="", alias="ROLLYPAY_REFUND_STATUS_URL"
    )

    # ---------- AI support assistant (drafts only, never sent by itself) ----------
    support_ai_url: str = Field(default="", alias="SUPPORT_AI_URL")
    support_ai_key: str = Field(default="", alias="SUPPORT_AI_KEY")
    support_ai_model: str = Field(default="", alias="SUPPORT_AI_MODEL")

    # ---------- CryptoBot ----------
    cryptobot_token: str = Field(default="", alias="CRYPTOBOT_TOKEN")
    cryptobot_network: str = Field(
        default="mainnet", alias="CRYPTOBOT_NETWORK"
    )

    # ---------- Freekassa (reserve gateway: cards, SBP, wallets) ----------
    freekassa_shop_id: str = Field(default="", alias="FREEKASSA_SHOP_ID")
    freekassa_secret1: str = Field(default="", alias="FREEKASSA_SECRET1")
    freekassa_secret2: str = Field(default="", alias="FREEKASSA_SECRET2")
    freekassa_api_key: str = Field(default="", alias="FREEKASSA_API_KEY")
    freekassa_webhook_ip_allowlist: str = Field(
        default="168.119.157.136,168.119.60.227,178.154.197.79,51.250.54.238", alias="FREEKASSA_WEBHOOK_IP_ALLOWLIST"
    )

    # ---------- CloudPayments, Lava, Pal24, Mulen Pay, WATA, Antilopay (more gateways, payments_extra.py) ----------
    cloudpayments_public_id: str = Field(default="", alias="CLOUDPAYMENTS_PUBLIC_ID")
    cloudpayments_api_secret: str = Field(default="", alias="CLOUDPAYMENTS_API_SECRET")
    lava_shop_id: str = Field(default="", alias="LAVA_SHOP_ID")
    lava_secret_key: str = Field(default="", alias="LAVA_SECRET_KEY")
    lava_webhook_secret: str = Field(default="", alias="LAVA_WEBHOOK_SECRET")
    pal24_api_token: str = Field(default="", alias="PAL24_API_TOKEN")
    pal24_shop_id: str = Field(default="", alias="PAL24_SHOP_ID")
    pal24_signature_token: str = Field(default="", alias="PAL24_SIGNATURE_TOKEN")
    mulenpay_api_key: str = Field(default="", alias="MULENPAY_API_KEY")
    mulenpay_secret_key: str = Field(default="", alias="MULENPAY_SECRET_KEY")
    mulenpay_shop_id: str = Field(default="", alias="MULENPAY_SHOP_ID")
    wata_access_token: str = Field(default="", alias="WATA_ACCESS_TOKEN")
    antilopay_project_id: str = Field(default="", alias="ANTILOPAY_PROJECT_ID")
    antilopay_secret_id: str = Field(default="", alias="ANTILOPAY_SECRET_ID")
    antilopay_private_key: str = Field(default="", alias="ANTILOPAY_PRIVATE_KEY")
    antilopay_public_key: str = Field(default="", alias="ANTILOPAY_PUBLIC_KEY")
    antilopay_customer_email: str = Field(default="", alias="ANTILOPAY_CUSTOMER_EMAIL")

    # ---------- Stripe ----------
    stripe_secret_key: str = Field(
        default="", alias="STRIPE_SECRET_KEY"
    )
    stripe_webhook_secret: str = Field(
        default="", alias="STRIPE_WEBHOOK_SECRET"
    )
    stripe_api_url: str = Field(default="https://api.stripe.com", alias="STRIPE_API_URL")
    paypal_api_url: str = Field(default="https://api-m.paypal.com", alias="PAYPAL_API_URL")
    paypal_client_id: str = Field(default="", alias="PAYPAL_CLIENT_ID")
    paypal_client_secret: str = Field(default="", alias="PAYPAL_CLIENT_SECRET")
    paypal_webhook_id: str = Field(default="", alias="PAYPAL_WEBHOOK_ID")
    apple_issuer_id: str = Field(default="", alias="APPLE_ISSUER_ID")
    apple_key_id: str = Field(default="", alias="APPLE_KEY_ID")
    apple_private_key: str = Field(default="", alias="APPLE_PRIVATE_KEY")
    apple_bundle_id: str = Field(default="", alias="APPLE_BUNDLE_ID")
    apple_appstore_api_url: str = Field(default="https://api.storekit.apple.com", alias="APPLE_APPSTORE_API_URL")
    google_play_package: str = Field(default="", alias="GOOGLE_PLAY_PACKAGE")
    google_service_account_json: str = Field(default="", alias="GOOGLE_SERVICE_ACCOUNT_JSON")
    google_play_api_url: str = Field(default="https://androidpublisher.googleapis.com", alias="GOOGLE_PLAY_API_URL")
    # JSON object {"store.product.id": plan_id}. Empty refuses Apple and Google purchases.
    mobile_store_products: str = Field(default="", alias="MOBILE_STORE_PRODUCTS")
    crypto_gateway_url: str = Field(default="", alias="CRYPTO_GATEWAY_URL")
    crypto_gateway_key: str = Field(default="", alias="CRYPTO_GATEWAY_KEY")
    sepa_enabled: bool = Field(default=False, alias="SEPA_ENABLED")
    payment_router_enabled: bool = Field(default=True, alias="PAYMENT_ROUTER_ENABLED")
    payment_risk_block_score: int = Field(default=90, alias="PAYMENT_RISK_BLOCK_SCORE")
    payment_risk_review_score: int = Field(default=60, alias="PAYMENT_RISK_REVIEW_SCORE")
    auto_renew_grace_days: int = Field(default=3, alias="AUTO_RENEW_GRACE_DAYS")
    auto_renew_max_retries: int = Field(default=5, alias="AUTO_RENEW_MAX_RETRIES")
    default_tax_rate: float = Field(default=19.0, alias="DEFAULT_TAX_RATE")

    # ---------- Вебхуки ----------
    webhook_base_url: str = Field(
        default="https://shop.example.com", alias="WEBHOOK_BASE_URL"
    )

    # ---------- Бизнес-логика ----------
    referral_reward_percent: float = Field(
        default=5.0, alias="REFERRAL_REWARD_PERCENT"
    )
    notification_expiry_days: int = Field(
        default=3, alias="NOTIFICATION_EXPIRY_DAYS"
    )
    auto_renew_enabled: bool = Field(
        default=False, alias="AUTO_RENEW_ENABLED"
    )
    auto_renew_lead_days: int = Field(
        default=3, alias="AUTO_RENEW_LEAD_DAYS", ge=1, le=14
    )
    required_telegram_channel: str = Field(
        default="", alias="REQUIRED_TELEGRAM_CHANNEL"
    )
    trial_max_days: int = Field(default=3, alias="TRIAL_MAX_DAYS", ge=1, le=30)
    payments_sandbox: bool = Field(default=False, alias="PAYMENTS_SANDBOX")
    mobile_client_key: str = Field(
        default="", alias="MOBILE_CLIENT_KEY"
    )
    mobile_require_proof: bool = Field(default=False, alias="MOBILE_REQUIRE_PROOF")
    fulfillment_max_attempts: int = Field(
        default=8, alias="FULFILLMENT_MAX_ATTEMPTS"
    )
    worker_role: str = Field(default="worker", alias="WORKER_ROLE")

    # ---------- S3 ----------
    backup_s3_enabled: bool = Field(
        default=False, alias="BACKUP_S3_ENABLED"
    )
    s3_endpoint_url: str = Field(default="", alias="S3_ENDPOINT_URL")
    s3_bucket: str = Field(default="", alias="S3_BUCKET")
    s3_region: str = Field(default="auto", alias="S3_REGION")
    s3_access_key: str = Field(default="", alias="S3_ACCESS_KEY")
    s3_secret_key: str = Field(default="", alias="S3_SECRET_KEY")

    # ---------- Мониторинг ----------
    metrics_enabled: bool = Field(default=True, alias="METRICS_ENABLED")
    metrics_token: str = Field(default="", alias="METRICS_TOKEN")
    alert_telegram_chat_id: str = Field(
        default="", alias="ALERT_TELEGRAM_CHAT_ID"
    )
    alert_email: str = Field(default="", alias="ALERT_EMAIL")
    smtp_host: str = Field(default="", alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_user: str = Field(default="", alias="SMTP_USER")
    smtp_password: str = Field(default="", alias="SMTP_PASSWORD")
    smtp_from: str = Field(default="", alias="SMTP_FROM")

    # ---------- Мобильные push-уведомления ----------
    # Firebase Cloud Messaging HTTP v1 (Android): service-account JSON or its base64.
    fcm_project_id: str = Field(default="", alias="FCM_PROJECT_ID")
    fcm_service_account_json: str = Field(default="", alias="FCM_SERVICE_ACCOUNT_JSON")
    # Apple Push Notification service (iOS): token-based auth with a .p8 key.
    apns_key_id: str = Field(default="", alias="APNS_KEY_ID")
    apns_team_id: str = Field(default="", alias="APNS_TEAM_ID")
    apns_bundle_id: str = Field(default="shop.remnawave.user", alias="APNS_BUNDLE_ID")
    apns_private_key: str = Field(default="", alias="APNS_PRIVATE_KEY")
    apns_environment: str = Field(default="production", alias="APNS_ENVIRONMENT")

    # ---------- Сетевая аналитика узлов (ASN и репутация) ----------
    # RIPEstat (без ключа) даёт ASN, владельца и страну RIR; AbuseIPDB — репутацию, только с ключом.
    network_intel_enabled: bool = Field(default=True, alias="NETWORK_INTEL_ENABLED")
    abuseipdb_api_key: str = Field(default="", alias="ABUSEIPDB_API_KEY")
    mail_domain: str = Field(default="", alias="MAIL_DOMAIN")
    mail_dns_doh_url: str = Field(default="https://cloudflare-dns.com/dns-query", alias="MAIL_DNS_DOH_URL")
    dmarc_imap_host: str = Field(default="", alias="DMARC_IMAP_HOST")
    dmarc_imap_port: int = Field(default=993, alias="DMARC_IMAP_PORT")
    dmarc_imap_user: str = Field(default="", alias="DMARC_IMAP_USER")
    dmarc_imap_password: str = Field(default="", alias="DMARC_IMAP_PASSWORD")
    dmarc_imap_folder: str = Field(default="INBOX", alias="DMARC_IMAP_FOLDER")
    dmarc_report_retention_days: int = Field(default=180, alias="DMARC_REPORT_RETENTION_DAYS")
    terminal_enabled: bool = Field(default=False, alias="TERMINAL_ENABLED")
    terminal_max_minutes: int = Field(default=30, alias="TERMINAL_MAX_MINUTES")
    terminal_idle_minutes: int = Field(default=10, alias="TERMINAL_IDLE_MINUTES")
    terminal_transcript_days: int = Field(default=90, alias="TERMINAL_TRANSCRIPT_DAYS")
    mail_receiver_enabled: bool = Field(default=False, alias="MAIL_RECEIVER_ENABLED")
    mail_receiver_port: int = Field(default=2525, alias="MAIL_RECEIVER_PORT")
    mail_receiver_routes: str = Field(default="", alias="MAIL_RECEIVER_ROUTES")
    mail_receiver_hostname: str = Field(default="", alias="MAIL_RECEIVER_HOSTNAME")
    mail_receiver_max_mb: int = Field(default=10, alias="MAIL_RECEIVER_MAX_MB")
    mail_receiver_tls_cert: str = Field(default="", alias="MAIL_RECEIVER_TLS_CERT")
    mail_receiver_tls_key: str = Field(default="", alias="MAIL_RECEIVER_TLS_KEY")
    mail_receiver_clamav: str = Field(default="", alias="MAIL_RECEIVER_CLAMAV")
    mail_receiver_greylist: bool = Field(default=True, alias="MAIL_RECEIVER_GREYLIST")
    mail_support_inbound_url: str = Field(default="", alias="MAIL_SUPPORT_INBOUND_URL")
    mail_inbound_secret: str = Field(default="", alias="MAIL_INBOUND_SECRET")

    # ---------- Безопасность ----------
    firewall_mode: str = Field(default="strict", alias="FIREWALL_MODE")
    require_pinned_images: bool = Field(
        default=True, alias="REQUIRE_PINNED_IMAGES"
    )

    # ---------- Образы ----------
    python_base_image: str = Field(default="", alias="PYTHON_BASE_IMAGE")
    node_base_image: str = Field(default="", alias="NODE_BASE_IMAGE")
    nginx_base_image: str = Field(default="", alias="NGINX_BASE_IMAGE")
    redis_image: str = Field(default="", alias="REDIS_IMAGE")
    postgres_image: str = Field(default="", alias="POSTGRES_IMAGE")
    caddy_image: str = Field(default="", alias="CADDY_IMAGE")

    # ---------- Релизы ----------
    release_manifest_url: str = Field(
        default="", alias="RELEASE_MANIFEST_URL"
    )
    release_manifest_public_key: str = Field(
        default="", alias="RELEASE_MANIFEST_PUBLIC_KEY"
    )

    # ---------- Порты ----------
    backend_port: int = Field(default=8000, alias="BACKEND_PORT")
    admin_port: int = Field(default=3000, alias="ADMIN_PORT")
    miniapp_port: int = Field(default=8080, alias="MINIAPP_PORT")

    # ---------- Файлы и каталоги ----------
    # Docker Compose монтирует эти пути в backend/worker. Не меняйте их,
    # если не меняете volumes в docker-compose.yml.
    media_dir: str = Field(default="/data/media", alias="MEDIA_DIR")
    backups_dir: str = Field(default="/data/backups", alias="BACKUPS_DIR")
    project_dir: str = Field(default="/project", alias="PROJECT_DIR")
    backup_s3_prefix: str = Field(default="vpn-shop", alias="BACKUP_S3_PREFIX")

    # ---------- Yandex ID ----------
    yandex_client_id: str = Field(default="", alias="YANDEX_CLIENT_ID")
    yandex_client_secret: str = Field(default="", alias="YANDEX_CLIENT_SECRET")
    yandex_redirect_uri: str = Field(default="", alias="YANDEX_REDIRECT_URI")

    # ---------- Google sign-in (OpenID Connect) ----------
    google_client_id: str = Field(default="", alias="GOOGLE_CLIENT_ID")
    google_client_secret: str = Field(default="", alias="GOOGLE_CLIENT_SECRET")
    google_redirect_uri: str = Field(default="", alias="GOOGLE_REDIRECT_URI")
    # Custom URL scheme of the native apps (corgi://login?...)
    mobile_app_scheme: str = Field(default="corgi", alias="MOBILE_APP_SCHEME")
    # Genuine app / device check of native sign-ins: off | report | enforce (mobile_integrity.py)
    mobile_integrity_mode: str = Field(default="off", alias="MOBILE_INTEGRITY_MODE")
    devicecheck_key_id: str = Field(default="", alias="DEVICECHECK_KEY_ID")
    devicecheck_private_key: str = Field(default="", alias="DEVICECHECK_PRIVATE_KEY")

    # ---------- VK ID ----------
    vk_client_id: str = Field(default="", alias="VK_CLIENT_ID")
    vk_client_secret: str = Field(default="", alias="VK_CLIENT_SECRET")
    vk_redirect_uri: str = Field(default="", alias="VK_REDIRECT_URI")

    # Public cabinet URL (separate from Telegram Mini App when needed)
    cabinet_url: str = Field(default="", alias="CABINET_URL")

    # ---------- Support Pro integration ----------
    support_pro_url: str = Field(default="", alias="SUPPORT_PRO_URL")
    support_pro_sso_secret: str = Field(default="", alias="SUPPORT_PRO_SSO_SECRET")
    support_pro_timeout_seconds: float = Field(default=4.0, alias="SUPPORT_PRO_TIMEOUT_SECONDS", ge=1.0, le=20.0)

    # Жёсткий env-флаг. Операционный режим также хранится в настройке БД maintenance_mode.
    maintenance_mode: bool = Field(default=False, alias="MAINTENANCE_MODE")

    # ---------- Валидаторы ----------
    @field_validator("admin_telegram_id", mode="before")
    @classmethod
    def _optional_admin_telegram_id(cls, value):
        return 0 if isinstance(value, str) and not value.strip() else value

    @model_validator(mode="after")
    def _require_secure_production_cookie(self) -> "Settings":
        if self.app_env.lower() == "production" and not self.cookie_secure:
            raise ValueError("COOKIE_SECURE must be true when APP_ENV=production")
        return self

    @field_validator("admin_cors_origins", mode="before")
    @classmethod
    def _normalize_cors(cls, v: object) -> object:
        """Убираем пробелы и пустые элементы."""
        if isinstance(v, str):
            return ",".join(
                part.strip() for part in v.split(",") if part.strip()
            )
        return v

    def admin_cors_origins_list(self) -> List[str]:
        """Вернуть список origin'ов для CORS middleware."""
        if not self.admin_cors_origins:
            return []
        return [
            o.strip()
            for o in self.admin_cors_origins.split(",")
            if o.strip()
        ]


    def validate_security(self):
        from .runtime_security import validate_configuration
        validate_configuration(self)

    def redis_connection_kwargs(self):
        from .runtime_security import redis_connection_kwargs
        return redis_connection_kwargs(self.redis_url, self.redis_password)

settings = Settings()
