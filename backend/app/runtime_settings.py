"""Typed, encrypted and versioned application settings that reload without restart."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import ipaddress
import re
import urllib.parse
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import SessionLocal, get_db
from .models import (
    AppSetting,
    AuditLog,
    RuntimeSettingChange,
    RuntimeSettingState,
)
from .security import decrypt_secret, encrypt_secret, require_permission


logger = logging.getLogger("remnawave.runtime_settings")
router = APIRouter(prefix="/api/admin/runtime-settings", tags=["runtime-settings"])

SettingKind = Literal["boolean", "integer", "number", "string", "secret", "select"]
SettingValue = bool | int | float | str | None
RUNTIME_SETTING_PREFIX = "runtime."
POLL_INTERVAL_SECONDS = 5


@dataclass(frozen=True, slots=True)
class SettingDefinition:
    key: str
    group: str
    title: str
    description: str
    kind: SettingKind
    env_attr: str
    secret: bool = False
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[str, ...] = ()
    optional: bool = False
    unit: str = ""


DEFINITIONS = (
    SettingDefinition("default_language", "general", "Язык по умолчанию", "Язык бота и кабинета, если клиент не передал предпочтение.", "select", "default_language", choices=("ru", "en")),
    SettingDefinition("log_level", "general", "Уровень журналирования", "Минимальный уровень сообщений Python-приложения.", "select", "log_level", choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")),
    SettingDefinition("notification_expiry_days", "general", "Предупреждать до окончания", "За сколько дней создать уведомление об окончании подписки.", "integer", "notification_expiry_days", minimum=1, maximum=30, unit="дн."),
    SettingDefinition("trial_max_days", "general", "Максимальный пробный период", "Верхняя граница пробной подписки для новых клиентов.", "integer", "trial_max_days", minimum=1, maximum=30, unit="дн."),
    SettingDefinition("required_telegram_channel", "general", "Обязательный Telegram-канал", "Username канала, подписка на который нужна для доступа; пустое значение отключает проверку.", "string", "required_telegram_channel", optional=True),
    SettingDefinition("payment_router_enabled", "billing", "Умная маршрутизация платежей", "Разрешает выбирать доступного провайдера по состоянию и приоритету.", "boolean", "payment_router_enabled"),
    SettingDefinition("payment_risk_review_score", "billing", "Порог ручной проверки", "Оценка риска, начиная с которой платёж требует проверки.", "integer", "payment_risk_review_score", minimum=0, maximum=99, unit="баллов"),
    SettingDefinition("payment_risk_block_score", "billing", "Порог блокировки", "Оценка риска, начиная с которой платёж блокируется.", "integer", "payment_risk_block_score", minimum=1, maximum=100, unit="баллов"),
    SettingDefinition("default_tax_rate", "billing", "Налоговая ставка", "Ставка по умолчанию для расчёта налоговой части счёта.", "number", "default_tax_rate", minimum=0, maximum=100, unit="%"),
    SettingDefinition("referral_reward_percent", "billing", "Реферальное вознаграждение", "Базовый процент вознаграждения, если уровень не задаёт другое значение.", "number", "referral_reward_percent", minimum=0, maximum=100, unit="%"),
    SettingDefinition("auto_renew_enabled", "renewal", "Автопродление", "Разрешает фоновому процессу создавать повторные списания.", "boolean", "auto_renew_enabled"),
    SettingDefinition("auto_renew_lead_days", "renewal", "Запуск до окончания", "За сколько дней до окончания подписки начать автопродление.", "integer", "auto_renew_lead_days", minimum=1, maximum=14, unit="дн."),
    SettingDefinition("auto_renew_grace_days", "renewal", "Льготный период", "Сколько дней сохранять доступ после неуспешного продления.", "integer", "auto_renew_grace_days", minimum=0, maximum=30, unit="дн."),
    SettingDefinition("auto_renew_max_retries", "renewal", "Попытки продления", "Максимальное число повторов неуспешного автопродления.", "integer", "auto_renew_max_retries", minimum=1, maximum=20),
    SettingDefinition("remnawave_cb_failures", "remnawave", "Ошибок до размыкания circuit", "Число последовательных ошибок Remnawave до временной блокировки запросов.", "integer", "remnawave_cb_failures", minimum=1, maximum=50),
    SettingDefinition("remnawave_cb_cooldown", "remnawave", "Пауза circuit breaker", "Пауза перед пробным запросом к Remnawave после серии ошибок.", "integer", "remnawave_cb_cooldown", minimum=1, maximum=3600, unit="сек."),
    SettingDefinition("metrics_enabled", "monitoring", "Prometheus-метрики", "Включает защищённую точку /metrics.", "boolean", "metrics_enabled"),
    SettingDefinition("metrics_token", "monitoring", "Токен метрик", "Секрет заголовка X-Metrics-Token. Значение никогда не возвращается из API.", "secret", "metrics_token", secret=True, optional=True),
    SettingDefinition("alert_telegram_chat_id", "monitoring", "Telegram chat ID алертов", "Числовой chat ID для системных предупреждений; требует BOT_TOKEN в окружении.", "string", "alert_telegram_chat_id", optional=True),
    SettingDefinition("alert_email", "monitoring", "Email алертов", "Адрес получателя системных предупреждений.", "string", "alert_email", optional=True),
    SettingDefinition("smtp_host", "mail", "SMTP-сервер", "DNS-имя или IP SMTP-сервера без схемы и пути.", "string", "smtp_host", optional=True),
    SettingDefinition("smtp_port", "mail", "SMTP-порт", "Порт 465 использует TLS сразу, остальные порты — STARTTLS.", "integer", "smtp_port", minimum=1, maximum=65535),
    SettingDefinition("smtp_user", "mail", "SMTP-пользователь", "Логин SMTP и резервный адрес отправителя.", "string", "smtp_user", optional=True),
    SettingDefinition("smtp_password", "mail", "SMTP-пароль", "Пароль хранится в AES-GCM и никогда не возвращается в браузер.", "secret", "smtp_password", secret=True, optional=True),
    SettingDefinition("smtp_from", "mail", "Адрес отправителя", "Email в заголовке From для писем магазина.", "string", "smtp_from", optional=True),
    SettingDefinition("tz", "general", "Часовой пояс", "Часовой пояс для расписаний и операторского интерфейса.", "string", "tz"),
    SettingDefinition("trusted_proxy_cidrs", "security", "Доверенные proxy CIDR", "Сети reverse proxy, от которых принимаются forwarded-заголовки.", "string", "trusted_proxy_cidrs", optional=True),
    SettingDefinition("support_bridge_token", "support", "Токен моста поддержки", "Секрет аутентификации двустороннего моста Support Pro.", "secret", "support_bridge_token", secret=True, optional=True),
    SettingDefinition("bot_username", "telegram", "Username Telegram-бота", "Публичное имя бота без URL; токен polling остаётся restart-bound.", "string", "bot_username", optional=True),
    SettingDefinition("admin_telegram_id", "telegram", "Telegram ID владельца", "Числовой ID, которому разрешена операторская команда бота.", "integer", "admin_telegram_id", minimum=0, maximum=9_223_372_036_854_775_807),
    SettingDefinition("remnawave_url", "remnawave", "URL Remnawave", "Публичный HTTPS URL панели Remnawave.", "string", "remnawave_url", optional=True),
    SettingDefinition("remnawave_token", "remnawave", "Токен Remnawave", "Bearer-токен API Remnawave; хранится зашифрованно.", "secret", "remnawave_token", secret=True, optional=True),
    SettingDefinition("public_base_url", "urls", "Публичный URL API", "HTTPS URL backend, используемый во внешних callback и ссылках.", "string", "public_base_url"),
    SettingDefinition("mini_app_url", "urls", "URL Mini App", "HTTPS URL Telegram Mini App.", "string", "mini_app_url"),
    SettingDefinition("cabinet_url", "urls", "URL кабинета", "Отдельный HTTPS URL кабинета; пустое значение использует Mini App.", "string", "cabinet_url", optional=True),
    SettingDefinition("webhook_base_url", "urls", "Базовый URL webhook", "Публичный HTTPS URL для регистрации callback провайдеров.", "string", "webhook_base_url"),
    SettingDefinition("price_1", "pricing", "Цена за 1 месяц", "Резервная цена простого месячного тарифа.", "integer", "price_1", minimum=0, maximum=100_000_000, unit="RUB"),
    SettingDefinition("price_3", "pricing", "Цена за 3 месяца", "Резервная цена простого трёхмесячного тарифа.", "integer", "price_3", minimum=0, maximum=100_000_000, unit="RUB"),
    SettingDefinition("price_6", "pricing", "Цена за 6 месяцев", "Резервная цена простого шестимесячного тарифа.", "integer", "price_6", minimum=0, maximum=100_000_000, unit="RUB"),
    SettingDefinition("price_12", "pricing", "Цена за 12 месяцев", "Резервная цена простого годового тарифа.", "integer", "price_12", minimum=0, maximum=100_000_000, unit="RUB"),
    SettingDefinition("yookassa_api_url", "yookassa", "YooKassa API URL", "HTTPS endpoint YooKassa.", "string", "yookassa_api_url"),
    SettingDefinition("yookassa_shop_id", "yookassa", "YooKassa Shop ID", "Идентификатор магазина YooKassa.", "string", "yookassa_shop_id", optional=True),
    SettingDefinition("yookassa_secret_key", "yookassa", "YooKassa secret key", "Секрет API YooKassa; хранится зашифрованно.", "secret", "yookassa_secret_key", secret=True, optional=True),
    SettingDefinition("yookassa_webhook_ip_allowlist", "yookassa", "YooKassa webhook CIDR", "Разрешённые IP/CIDR источников callback через запятую.", "string", "yookassa_webhook_ip_allowlist", optional=True),
    SettingDefinition("platega_api_url", "platega", "Platega API URL", "HTTPS endpoint Platega.", "string", "platega_api_url"),
    SettingDefinition("platega_merchant_id", "platega", "Platega Merchant ID", "Идентификатор мерчанта Platega.", "string", "platega_merchant_id", optional=True),
    SettingDefinition("platega_secret", "platega", "Platega secret", "Секрет callback и API Platega.", "secret", "platega_secret", secret=True, optional=True),
    SettingDefinition("platega_refund_url", "platega", "Platega refund URL", "HTTPS endpoint создания возврата.", "string", "platega_refund_url", optional=True),
    SettingDefinition("platega_refund_status_url", "platega", "Platega refund status URL", "HTTPS endpoint статуса возврата.", "string", "platega_refund_status_url", optional=True),
    SettingDefinition("rollypay_api_url", "rollypay", "RollyPay API URL", "HTTPS endpoint RollyPay.", "string", "rollypay_api_url"),
    SettingDefinition("rollypay_api_key", "rollypay", "RollyPay API key", "API-ключ RollyPay; хранится зашифрованно.", "secret", "rollypay_api_key", secret=True, optional=True),
    SettingDefinition("rollypay_signing_secret", "rollypay", "RollyPay signing secret", "Секрет подписи callback RollyPay.", "secret", "rollypay_signing_secret", secret=True, optional=True),
    SettingDefinition("rollypay_test_mode", "rollypay", "RollyPay test mode", "Передаёт test=true при создании платежа.", "boolean", "rollypay_test_mode"),
    SettingDefinition("rollypay_refund_url", "rollypay", "RollyPay refund URL", "HTTPS endpoint создания возврата.", "string", "rollypay_refund_url", optional=True),
    SettingDefinition("rollypay_refund_status_url", "rollypay", "RollyPay refund status URL", "HTTPS endpoint статуса возврата.", "string", "rollypay_refund_status_url", optional=True),
    SettingDefinition("cryptobot_token", "crypto", "CryptoBot token", "API-токен CryptoBot; хранится зашифрованно.", "secret", "cryptobot_token", secret=True, optional=True),
    SettingDefinition("cryptobot_network", "crypto", "Сеть CryptoBot", "Рабочая сеть CryptoBot.", "select", "cryptobot_network", choices=("mainnet", "testnet")),
    SettingDefinition("stripe_api_url", "stripe", "Stripe API URL", "HTTPS endpoint Stripe.", "string", "stripe_api_url"),
    SettingDefinition("stripe_secret_key", "stripe", "Stripe secret key", "Секрет API Stripe.", "secret", "stripe_secret_key", secret=True, optional=True),
    SettingDefinition("stripe_webhook_secret", "stripe", "Stripe webhook secret", "Секрет подписи Stripe webhook.", "secret", "stripe_webhook_secret", secret=True, optional=True),
    SettingDefinition("paypal_api_url", "paypal", "PayPal API URL", "HTTPS endpoint PayPal.", "string", "paypal_api_url"),
    SettingDefinition("paypal_client_id", "paypal", "PayPal client ID", "Идентификатор OAuth-приложения PayPal.", "string", "paypal_client_id", optional=True),
    SettingDefinition("paypal_client_secret", "paypal", "PayPal client secret", "Секрет OAuth-приложения PayPal.", "secret", "paypal_client_secret", secret=True, optional=True),
    SettingDefinition("paypal_webhook_id", "paypal", "PayPal webhook ID", "Идентификатор зарегистрированного webhook PayPal.", "string", "paypal_webhook_id", optional=True),
    SettingDefinition("apple_issuer_id", "mobile_stores", "Apple issuer ID", "Issuer ID App Store Connect API.", "string", "apple_issuer_id", optional=True),
    SettingDefinition("apple_key_id", "mobile_stores", "Apple key ID", "Key ID App Store Connect API.", "string", "apple_key_id", optional=True),
    SettingDefinition("apple_private_key", "mobile_stores", "Apple private key", "Приватный ключ App Store Connect; хранится зашифрованно.", "secret", "apple_private_key", secret=True, optional=True),
    SettingDefinition("apple_bundle_id", "mobile_stores", "Apple bundle ID", "Bundle ID проверяемого iOS-приложения.", "string", "apple_bundle_id", optional=True),
    SettingDefinition("apple_appstore_api_url", "mobile_stores", "App Store API URL", "HTTPS endpoint App Store Server API.", "string", "apple_appstore_api_url"),
    SettingDefinition("google_play_package", "mobile_stores", "Google Play package", "Package name Android-приложения.", "string", "google_play_package", optional=True),
    SettingDefinition("google_service_account_json", "mobile_stores", "Google service account", "JSON сервисного аккаунта Google Play; хранится зашифрованно.", "secret", "google_service_account_json", secret=True, optional=True),
    SettingDefinition("google_play_api_url", "mobile_stores", "Google Play API URL", "HTTPS endpoint Android Publisher API.", "string", "google_play_api_url"),
    SettingDefinition("mobile_store_products", "mobile_stores", "Mapping store products", "JSON object: product ID → ID тарифа.", "string", "mobile_store_products", optional=True),
    SettingDefinition("mobile_client_key", "mobile", "Ключ native-клиента", "Общий ключ доказательства native-запроса; хранится зашифрованно.", "secret", "mobile_client_key", secret=True, optional=True),
    SettingDefinition("mobile_require_proof", "mobile", "Требовать native proof", "Отклоняет mobile API без корректного доказательства клиента.", "boolean", "mobile_require_proof"),
    SettingDefinition("crypto_gateway_url", "crypto", "Crypto gateway URL", "HTTPS endpoint собственного криптопроцессинга.", "string", "crypto_gateway_url", optional=True),
    SettingDefinition("crypto_gateway_key", "crypto", "Crypto gateway key", "API-ключ криптопроцессинга.", "secret", "crypto_gateway_key", secret=True, optional=True),
    SettingDefinition("sepa_enabled", "billing", "SEPA", "Показывает доступность SEPA в маршрутизаторе платежей.", "boolean", "sepa_enabled"),
    SettingDefinition("fulfillment_max_attempts", "billing", "Попытки выдачи", "Максимальное число попыток выдать оплаченную подписку.", "integer", "fulfillment_max_attempts", minimum=1, maximum=100),
    SettingDefinition("s3_endpoint_url", "storage", "S3 endpoint", "HTTPS endpoint S3/R2/B2 для off-site backup.", "string", "s3_endpoint_url", optional=True),
    SettingDefinition("s3_bucket", "storage", "S3 bucket", "Bucket резервных копий.", "string", "s3_bucket", optional=True),
    SettingDefinition("s3_region", "storage", "S3 region", "Регион S3 или auto для совместимого сервиса.", "string", "s3_region", optional=True),
    SettingDefinition("s3_access_key", "storage", "S3 access key", "Access key S3; хранится зашифрованно.", "secret", "s3_access_key", secret=True, optional=True),
    SettingDefinition("s3_secret_key", "storage", "S3 secret key", "Secret key S3; хранится зашифрованно.", "secret", "s3_secret_key", secret=True, optional=True),
    SettingDefinition("backup_s3_prefix", "storage", "S3 prefix", "Префикс объектов резервных копий.", "string", "backup_s3_prefix"),
    SettingDefinition("release_manifest_url", "updates", "URL release manifest", "HTTPS URL подписанного манифеста обновления.", "string", "release_manifest_url", optional=True),
    SettingDefinition("release_manifest_public_key", "updates", "Ключ проверки manifest", "Публичный ключ проверки релиза; значение маскируется в API.", "secret", "release_manifest_public_key", secret=True, optional=True),
    SettingDefinition("yandex_client_id", "oauth", "Yandex client ID", "Client ID приложения Yandex ID.", "string", "yandex_client_id", optional=True),
    SettingDefinition("yandex_client_secret", "oauth", "Yandex client secret", "Client secret Yandex ID.", "secret", "yandex_client_secret", secret=True, optional=True),
    SettingDefinition("yandex_redirect_uri", "oauth", "Yandex redirect URI", "Точный HTTPS callback Yandex ID.", "string", "yandex_redirect_uri", optional=True),
    SettingDefinition("vk_client_id", "oauth", "VK client ID", "Client ID приложения VK ID.", "string", "vk_client_id", optional=True),
    SettingDefinition("vk_client_secret", "oauth", "VK client secret", "Client secret VK ID.", "secret", "vk_client_secret", secret=True, optional=True),
    SettingDefinition("vk_redirect_uri", "oauth", "VK redirect URI", "Точный HTTPS callback VK ID.", "string", "vk_redirect_uri", optional=True),
    SettingDefinition("google_client_id", "oauth", "Google client ID", "Client ID OAuth-клиента Google (тип «Веб-приложение»).", "string", "google_client_id", optional=True),
    SettingDefinition("google_client_secret", "oauth", "Google client secret", "Client secret OAuth-клиента Google.", "secret", "google_client_secret", secret=True, optional=True),
    SettingDefinition("support_pro_url", "support", "URL Support Pro", "HTTPS URL отдельного сервиса Support Pro.", "string", "support_pro_url", optional=True),
    SettingDefinition("support_pro_sso_secret", "support", "Support Pro SSO secret", "Общий SSO-секрет; хранится зашифрованно.", "secret", "support_pro_sso_secret", secret=True, optional=True),
    SettingDefinition("support_pro_timeout_seconds", "support", "Timeout Support Pro", "Лимит ожидания ответа Support Pro.", "number", "support_pro_timeout_seconds", minimum=1, maximum=20, unit="сек."),
)

DEFINITION_BY_KEY = {definition.key: definition for definition in DEFINITIONS}
if len(DEFINITION_BY_KEY) != len(DEFINITIONS):
    raise RuntimeError("Runtime settings registry contains duplicate keys")
HOT_SETTING_FIELDS = {definition.env_attr for definition in DEFINITIONS}
unknown_fields = HOT_SETTING_FIELDS.difference(settings.__class__.model_fields)
if unknown_fields:
    raise RuntimeError(
        f"Runtime settings registry contains unknown fields: {', '.join(sorted(unknown_fields))}"
    )
ENVIRONMENT_VALUES = {
    definition.key: getattr(settings, definition.env_attr) for definition in DEFINITIONS
}
_loaded_version = -1

MANAGED_ELSEWHERE = (
    {
        "key": "backup_s3_enabled",
        "env": "BACKUP_S3_ENABLED",
        "location": "Резервные копии → Политика backup",
        "reason": "Операционный флаг уже хранится в AppSetting и меняется вместе с расписанием, bucket и retention.",
    },
    {
        "key": "maintenance_mode",
        "env": "MAINTENANCE_MODE",
        "location": "Операции → Recovery",
        "reason": "Операционный режим связан с restore-lock и переключается транзакционно процедурой восстановления.",
    },
)
MANAGED_ELSEWHERE_KEYS = {item["key"] for item in MANAGED_ELSEWHERE}


def _restart_reason(key: str) -> str:
    if key in {"app_secret", "app_secret_previous"}:
        return "Корневой ключ шифрования и подписи токенов меняется по отдельной процедуре ротации."
    if key in {"database_url", "db_user", "db_password", "db_name", "redis_url", "redis_password"}:
        return "Подключение создаётся при запуске процесса и требует контролируемого restart."
    if key in {"backend_port", "admin_port", "miniapp_port", "caddy_http_port", "caddy_https_port"}:
        return "Порт принадлежит Docker/Caddy и применяется только пересозданием контейнера."
    if key.endswith("_domain") or key in {"admin_cors_origins", "cabinet_cors_origins", "cookie_secure", "cookie_samesite", "customer_webauthn_origin", "webauthn_origin"}:
        return "Значение входит в middleware/origin-контракт, построенный при старте."
    if key in {"media_dir", "backups_dir", "project_dir"}:
        return "Путь связан с volume/static mount и не может безопасно меняться внутри процесса."
    if key.endswith("_image") or key in {"require_pinned_images", "firewall_mode"}:
        return "Параметр относится к deployment policy, а не к runtime приложения."
    if key in {"bot_token", "worker_role", "app_env", "admin_email", "admin_password", "payments_sandbox"}:
        return "Параметр определяет идентичность или режим процесса и проверяется до запуска."
    if key in {"network_intel_enabled", "abuseipdb_api_key"}:
        return "Источник сетевой аналитики настраивается в .env и применяется после restart worker; ключ AbuseIPDB не хранится в БД."
    if key.startswith("terminal_"):
        return "Терминал узлов — граница безопасности: включается и ограничивается только через .env и restart backend, панель не может его включить."
    if key.startswith("mail_receiver_") or key in {"mail_support_inbound_url", "mail_inbound_secret"}:
        return "Приёмник почты (MX) работает отдельным процессом mail_receiver; адреса, TLS и секрет меняются через .env и перезапуск сервиса."
    if key == "mail_domain" or key.startswith("mail_dns_") or key.startswith("dmarc_"):
        return "Почтовый домен и ящик DMARC-отчётов настраиваются в .env; пароль ящика не хранится в БД, изменения применяются после restart backend и worker."
    if key in {"android_user_package", "android_user_cert_sha256", "ios_user_app_id"}:
        return "Привязка приложений к домену кабинета для passkeys публикуется в /.well-known; меняется через .env и restart backend."
    if key.startswith("fcm_") or key.startswith("apns_"):
        return "Ключ провайдера push — секрет сервера; меняется через .env и restart worker, не хранится в БД."
    if key == "remnawave_webhook_secret":
        return "Секрет подписи вебхуков Remnawave совпадает с WEBHOOK_SECRET_HEADER панели; меняется в .env вместе с панелью и restart backend."
    if key == "default_currency":
        return "Смена расчётной валюты требует миграции тарифов и финансовых снимков, затем контролируемого restart."
    return "Параметр инициализируется до обработки запросов и требует контролируемого restart."


RESTART_REQUIRED = tuple(
    {
        "key": key,
        "env": str(field.alias or key).upper(),
        "reason": _restart_reason(key),
    }
    for key, field in settings.__class__.model_fields.items()
    if key not in HOT_SETTING_FIELDS and key not in MANAGED_ELSEWHERE_KEYS
)

if len(HOT_SETTING_FIELDS) + len(RESTART_REQUIRED) + len(MANAGED_ELSEWHERE) != len(
    settings.__class__.model_fields
):
    raise RuntimeError("Runtime settings registry does not cover every Settings field")


ChangeReason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]


class StageSettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    base_version: int = Field(ge=0)
    changes: dict[str, SettingValue] = Field(default_factory=dict, max_length=50)
    clear: list[str] = Field(default_factory=list, max_length=50)
    reason: ChangeReason


class ApplySettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    expected_version: int = Field(ge=0)
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")


class RollbackSettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    expected_version: int = Field(ge=0)
    reason: ChangeReason


def _setting_key(key: str) -> str:
    return RUNTIME_SETTING_PREFIX + key


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _fingerprint(payload: dict[str, object]) -> str:
    return hmac.new(
        settings.app_secret.encode(),
        _canonical(payload).encode(),
        hashlib.sha256,
    ).hexdigest()


def _parse_value(definition: SettingDefinition, value: object) -> bool | int | float | str:
    if definition.kind == "boolean":
        if type(value) is not bool:
            raise HTTPException(422, f"{definition.key}: требуется boolean")
        return value
    if definition.kind == "integer":
        if type(value) is not int:
            raise HTTPException(422, f"{definition.key}: требуется целое число")
        if definition.minimum is not None and value < definition.minimum:
            raise HTTPException(422, f"{definition.key}: значение меньше {definition.minimum:g}")
        if definition.maximum is not None and value > definition.maximum:
            raise HTTPException(422, f"{definition.key}: значение больше {definition.maximum:g}")
        return value
    if definition.kind == "number":
        if type(value) not in {int, float}:
            raise HTTPException(422, f"{definition.key}: требуется число")
        try:
            numeric = float(value)
        except OverflowError as exc:
            raise HTTPException(422, f"{definition.key}: недопустимое число") from exc
        if not (-1e308 < numeric < 1e308):
            raise HTTPException(422, f"{definition.key}: недопустимое число")
        if definition.minimum is not None and numeric < definition.minimum:
            raise HTTPException(422, f"{definition.key}: значение меньше {definition.minimum:g}")
        if definition.maximum is not None and numeric > definition.maximum:
            raise HTTPException(422, f"{definition.key}: значение больше {definition.maximum:g}")
        return numeric
    if not isinstance(value, str):
        raise HTTPException(422, f"{definition.key}: требуется строка")
    normalized = value if definition.secret else value.strip()
    if not normalized and not definition.optional:
        raise HTTPException(422, f"{definition.key}: значение обязательно")
    maximum_length = 100_000 if definition.secret else 2048
    if len(normalized) > maximum_length or "\x00" in normalized:
        raise HTTPException(422, f"{definition.key}: недопустимая строка")
    if not definition.secret and ("\r" in normalized or "\n" in normalized):
        raise HTTPException(422, f"{definition.key}: переносы строк запрещены")
    if definition.choices and normalized not in definition.choices:
        raise HTTPException(422, f"{definition.key}: допустимо {', '.join(definition.choices)}")
    if definition.key in {"alert_email", "smtp_from"} and normalized:
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", normalized):
            raise HTTPException(422, f"{definition.key}: некорректный email")
    if definition.key == "smtp_host" and normalized:
        if "://" in normalized or "/" in normalized or " " in normalized or len(normalized) > 253:
            raise HTTPException(422, "smtp_host: укажите только DNS-имя или IP")
    if definition.key == "alert_telegram_chat_id" and normalized:
        if not re.fullmatch(r"-?[1-9][0-9]{4,19}", normalized):
            raise HTTPException(422, "alert_telegram_chat_id: требуется числовой chat ID")
    if definition.key == "required_telegram_channel" and normalized:
        if not re.fullmatch(r"@?[A-Za-z0-9_]{5,32}", normalized):
            raise HTTPException(422, "required_telegram_channel: некорректный username")
    if definition.key == "metrics_token" and normalized and len(normalized) < 24:
        raise HTTPException(422, "metrics_token: минимум 24 символа")
    if definition.key in {"support_bridge_token", "support_pro_sso_secret", "mobile_client_key"} and normalized and len(normalized) < 32:
        raise HTTPException(422, f"{definition.key}: минимум 32 символа")
    if definition.key == "tz" and normalized:
        try:
            ZoneInfo(normalized)
        except ZoneInfoNotFoundError as exc:
            raise HTTPException(422, "tz: неизвестный часовой пояс IANA") from exc
    if definition.key == "bot_username" and normalized:
        if not re.fullmatch(r"@?[A-Za-z][A-Za-z0-9_]{4,31}", normalized):
            raise HTTPException(422, "bot_username: некорректный username")
        normalized = normalized.removeprefix("@")
    if definition.key in {"trusted_proxy_cidrs", "yookassa_webhook_ip_allowlist"} and normalized:
        try:
            for network in normalized.split(","):
                ipaddress.ip_network(network.strip(), strict=False)
        except ValueError as exc:
            raise HTTPException(422, f"{definition.key}: некорректный IP/CIDR") from exc
    if definition.key.endswith("_url") or definition.key.endswith("_uri"):
        if normalized:
            parsed = urllib.parse.urlparse(normalized)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                raise HTTPException(422, f"{definition.key}: требуется абсолютный HTTPS URL без credentials")
    if definition.key == "mobile_store_products" and normalized:
        try:
            products = json.loads(normalized)
        except json.JSONDecodeError as exc:
            raise HTTPException(422, "mobile_store_products: требуется JSON object") from exc
        if not isinstance(products, dict) or not all(
            isinstance(key, str) and key and type(plan_id) is int and plan_id > 0
            for key, plan_id in products.items()
        ):
            raise HTTPException(422, "mobile_store_products: требуется object product ID → положительный plan ID")
        normalized = _canonical(products)
    if definition.key == "google_service_account_json" and normalized:
        try:
            service_account = json.loads(normalized)
        except json.JSONDecodeError as exc:
            raise HTTPException(422, "google_service_account_json: требуется JSON object") from exc
        if not isinstance(service_account, dict) or not isinstance(service_account.get("client_email"), str) or not isinstance(service_account.get("private_key"), str):
            raise HTTPException(422, "google_service_account_json: отсутствуют client_email/private_key")
        normalized = _canonical(service_account)
    return normalized


def _dependency_errors(values: dict[str, bool | int | float | str]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    review = int(values["payment_risk_review_score"])
    block = int(values["payment_risk_block_score"])
    if review >= block:
        errors.append("Порог ручной проверки должен быть меньше порога блокировки.")
    if bool(values["auto_renew_enabled"]) and int(values["auto_renew_max_retries"]) < 1:
        errors.append("Для автопродления нужна хотя бы одна попытка.")
    if bool(values["metrics_enabled"]) and not str(values["metrics_token"]):
        warnings.append("Метрики включены, но METRICS_TOKEN не задан: /metrics вернёт 503.")
    if str(values["alert_email"]) and not str(values["smtp_host"]):
        errors.append("Для email-алертов необходимо указать SMTP-сервер.")
    if str(values["smtp_host"]) and not (str(values["smtp_from"]) or str(values["smtp_user"])):
        errors.append("Для SMTP нужен адрес отправителя или SMTP-пользователь.")
    pairs = (
        ("Remnawave", ("remnawave_url", "remnawave_token")),
        ("Platega", ("platega_merchant_id", "platega_secret")),
        ("RollyPay", ("rollypay_api_key", "rollypay_signing_secret")),
        ("PayPal", ("paypal_client_id", "paypal_client_secret")),
        ("Crypto gateway", ("crypto_gateway_url", "crypto_gateway_key")),
        ("Release manifest", ("release_manifest_url", "release_manifest_public_key")),
        ("Support Pro", ("support_pro_url", "support_pro_sso_secret")),
    )
    for title, keys in pairs:
        configured = [bool(str(values[key])) for key in keys]
        if any(configured) and not all(configured):
            errors.append(f"{title}: заполните связанные параметры вместе ({', '.join(keys)}).")
    for title, keys in (
        ("Yandex ID", ("yandex_client_id", "yandex_client_secret", "yandex_redirect_uri")),
        ("VK ID", ("vk_client_id", "vk_client_secret", "vk_redirect_uri")),
        ("Google", ("google_client_id", "google_client_secret")),
        ("Apple Store", ("apple_issuer_id", "apple_key_id", "apple_private_key", "apple_bundle_id")),
        ("Google Play", ("google_play_package", "google_service_account_json")),
    ):
        configured = [bool(str(values[key])) for key in keys]
        if any(configured) and not all(configured):
            errors.append(f"{title}: конфигурация должна быть заполнена целиком ({', '.join(keys)}).")
    yookassa_credentials = [bool(str(values[key])) for key in ("yookassa_shop_id", "yookassa_secret_key")]
    yookassa_allowlist = bool(str(values["yookassa_webhook_ip_allowlist"]))
    if any(yookassa_credentials) and not (all(yookassa_credentials) and yookassa_allowlist):
        errors.append("YooKassa: нужны shop ID, secret key и webhook IP allowlist.")
    s3_keys = ("s3_endpoint_url", "s3_bucket", "s3_access_key", "s3_secret_key")
    s3 = [bool(str(values[key])) for key in s3_keys]
    if any(s3) and not all(s3):
        errors.append(f"S3: заполните связанные параметры вместе ({', '.join(s3_keys)}).")
    if bool(values["mobile_require_proof"]) and not str(values["mobile_client_key"]):
        errors.append("Для обязательного native proof задайте mobile_client_key.")
    if str(values["stripe_secret_key"]) and not str(values["stripe_webhook_secret"]):
        warnings.append("Stripe API настроен без webhook secret: callback будет отклонён.")
    return errors, warnings


def _serialize_stored(definition: SettingDefinition, value: bool | int | float | str) -> str:
    serialized = _canonical(value)
    return encrypt_secret(serialized) if definition.secret else serialized


def _deserialize_stored(definition: SettingDefinition, value: str) -> bool | int | float | str:
    serialized = decrypt_secret(value) if definition.secret else value
    decoded = json.loads(serialized)
    return _parse_value(definition, decoded)


async def _state(db: AsyncSession, *, lock: bool = False) -> RuntimeSettingState:
    statement = select(RuntimeSettingState).where(RuntimeSettingState.id == 1).execution_options(populate_existing=True)
    if lock:
        statement = statement.with_for_update()
    row = await db.scalar(statement)
    if row is None:
        row = RuntimeSettingState(id=1, version=0, updated_at=datetime.utcnow())
        db.add(row)
        await db.flush()
    return row


async def _override_rows(db: AsyncSession) -> dict[str, AppSetting]:
    keys = [_setting_key(definition.key) for definition in DEFINITIONS]
    rows = (await db.scalars(select(AppSetting).where(AppSetting.key.in_(keys)).execution_options(populate_existing=True))).all()
    return {row.key.removeprefix(RUNTIME_SETTING_PREFIX): row for row in rows}


def _effective_values(overrides: dict[str, AppSetting]) -> dict[str, bool | int | float | str]:
    values: dict[str, bool | int | float | str] = {}
    for definition in DEFINITIONS:
        row = overrides.get(definition.key)
        value = ENVIRONMENT_VALUES[definition.key]
        if row is not None:
            value = _deserialize_stored(definition, row.value)
        values[definition.key] = _parse_value(definition, value)
    return values


def _validated_projection(
    overrides: dict[str, AppSetting],
    changes: dict[str, object],
    clear: list[object],
) -> list[str]:
    projected = _effective_values(overrides)
    for key, value in changes.items():
        definition = DEFINITION_BY_KEY.get(key)
        if definition is None:
            raise HTTPException(409, f"Определение {key} больше не поддерживается")
        projected[key] = _parse_value(definition, value)
    for key in clear:
        if not isinstance(key, str) or key not in DEFINITION_BY_KEY:
            raise HTTPException(409, "Набор содержит неподдерживаемый сброс настройки")
        projected[key] = _parse_value(DEFINITION_BY_KEY[key], ENVIRONMENT_VALUES[key])
    errors, warnings = _dependency_errors(projected)
    if errors:
        raise HTTPException(422, {"message": "Зависимости настроек не выполнены", "errors": errors})
    return warnings


def _safe_change(row: RuntimeSettingChange, version: int) -> dict[str, object]:
    return {
        "id": row.id,
        "base_version": row.base_version,
        "target_version": row.target_version,
        "status": row.status,
        "keys": list(row.keys),
        "fingerprint": row.fingerprint,
        "actor": row.actor,
        "reason": row.reason,
        "source_change_id": row.source_change_id,
        "created_at": row.created_at.isoformat() + "Z",
        "applied_at": row.applied_at.isoformat() + "Z" if row.applied_at else None,
        "can_apply": row.status == "staged" and row.base_version == version,
        "can_discard": row.status == "staged",
        "can_rollback": row.status == "applied" and row.target_version == version,
    }


async def refresh_runtime_settings(db: AsyncSession, *, force: bool = False) -> int:
    """Apply the latest committed overrides to this process as one event-loop operation."""
    global _loaded_version
    state = await _state(db)
    if not force and state.version == _loaded_version:
        return state.version
    overrides = await _override_rows(db)
    try:
        values = _effective_values(overrides)
        errors, _ = _dependency_errors(values)
        if errors:
            raise ValueError("; ".join(errors))
    except (HTTPException, ValueError, TypeError, json.JSONDecodeError) as exc:
        logger.error("Runtime settings version %s is invalid: %s", state.version, exc)
        return _loaded_version
    for definition in DEFINITIONS:
        setattr(settings, definition.env_attr, values[definition.key])
    logging.getLogger().setLevel(str(values["log_level"]))
    _loaded_version = state.version
    return state.version


async def runtime_settings_scheduler() -> None:
    """Converge each API/worker process to the database version."""
    while True:
        try:
            async with SessionLocal() as db:
                await refresh_runtime_settings(db)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Runtime settings refresh failed: %s", exc)
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


async def catalog(db: AsyncSession, *, can_write: bool = False) -> dict[str, object]:
    state = await _state(db)
    overrides = await _override_rows(db)
    values = _effective_values(overrides)
    errors, warnings = _dependency_errors(values)
    rows = (await db.scalars(
        select(RuntimeSettingChange)
        .order_by(RuntimeSettingChange.created_at.desc())
        .limit(50)
    )).all()
    definitions: list[dict[str, object]] = []
    for definition in DEFINITIONS:
        value = values[definition.key]
        definitions.append({
            "key": definition.key,
            "group": definition.group,
            "title": definition.title,
            "description": definition.description,
            "kind": definition.kind,
            "secret": definition.secret,
            "minimum": definition.minimum,
            "maximum": definition.maximum,
            "choices": list(definition.choices),
            "optional": definition.optional,
            "unit": definition.unit,
            "value": None if definition.secret else value,
            "configured": bool(value) if definition.secret else True,
            "overridden": definition.key in overrides,
            "source": "database" if definition.key in overrides else "environment",
        })
    return {
        "version": state.version,
        "registry_version": 1,
        "convergence_seconds": POLL_INTERVAL_SECONDS,
        "hot_reload_count": len(DEFINITIONS),
        "restart_required_count": len(RESTART_REQUIRED),
        "managed_elsewhere_count": len(MANAGED_ELSEWHERE),
        "can_write": can_write,
        "settings": definitions,
        "restart_required": list(RESTART_REQUIRED),
        "managed_elsewhere": list(MANAGED_ELSEWHERE),
        "warnings": warnings,
        "errors": errors,
        "staged": [_safe_change(row, state.version) for row in rows if row.status == "staged"],
        "history": [_safe_change(row, state.version) for row in rows if row.status != "staged"],
    }


async def stage_change(
    payload: StageSettingsIn,
    db: AsyncSession,
    actor: str,
) -> dict[str, object]:
    state = await _state(db)
    if state.version != payload.base_version:
        raise HTTPException(409, "Настройки уже изменились; обновите страницу")
    clear = sorted(set(payload.clear))
    overlap = set(clear) & set(payload.changes)
    if overlap:
        raise HTTPException(422, f"Нельзя изменить и сбросить одновременно: {', '.join(sorted(overlap))}")
    keys = sorted(set(payload.changes) | set(clear))
    if not keys:
        raise HTTPException(422, "Добавьте хотя бы одно изменение")
    unknown = [key for key in keys if key not in DEFINITION_BY_KEY]
    if unknown:
        raise HTTPException(422, f"Неизвестные настройки: {', '.join(unknown)}")
    normalized: dict[str, bool | int | float | str] = {}
    for key, value in payload.changes.items():
        if value is None:
            raise HTTPException(422, f"{key}: используйте clear для сброса")
        normalized[key] = _parse_value(DEFINITION_BY_KEY[key], value)
    overrides = await _override_rows(db)
    warnings = _validated_projection(overrides, normalized, clear)
    before = {
        key: {
            "present": key in overrides,
            "value": overrides[key].value if key in overrides else None,
        }
        for key in keys
    }
    change_id = str(uuid.uuid4())
    internal: dict[str, object] = {
        "id": change_id,
        "base_version": state.version,
        "environment_fingerprint": _fingerprint(ENVIRONMENT_VALUES),
        "changes": normalized,
        "clear": clear,
        "before": before,
    }
    fingerprint = _fingerprint(internal)
    row = RuntimeSettingChange(
        id=change_id,
        base_version=state.version,
        status="staged",
        keys=keys,
        payload_encrypted=encrypt_secret(_canonical(internal)),
        fingerprint=fingerprint,
        actor=actor,
        reason=payload.reason.strip(),
        created_at=datetime.utcnow(),
    )
    db.add(row)
    db.add(AuditLog(
        action="runtime_settings.staged",
        actor=actor,
        target=change_id,
        details=_canonical({"keys": keys, "base_version": state.version, "fingerprint": fingerprint}),
    ))
    await db.commit()
    preview = []
    for key in keys:
        definition = DEFINITION_BY_KEY[key]
        preview.append({
            "key": key,
            "title": definition.title,
            "clear": key in clear,
            "value": None if definition.secret else normalized.get(key),
            "secret_changed": definition.secret and key in normalized,
        })
    return {"change": _safe_change(row, state.version), "preview": preview, "warnings": warnings}


def _load_payload(row: RuntimeSettingChange) -> dict[str, object]:
    try:
        decoded = json.loads(decrypt_secret(row.payload_encrypted))
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(500, "Зашифрованный набор изменений повреждён") from exc
    if not isinstance(decoded, dict) or not hmac.compare_digest(_fingerprint(decoded), row.fingerprint):
        raise HTTPException(409, "Целостность набора изменений нарушена")
    return decoded


def _check_environment(payload: dict[str, object]) -> None:
    expected = payload.get("environment_fingerprint")
    if not isinstance(expected, str) or not hmac.compare_digest(expected, _fingerprint(ENVIRONMENT_VALUES)):
        raise HTTPException(409, "Параметры .env изменились; подготовьте новый явный набор настроек")


async def _write_normalized(
    db: AsyncSession,
    changes: dict[str, object],
    clear: list[object],
) -> None:
    clear_keys = {str(key) for key in clear}
    for key in clear_keys:
        row = await db.get(AppSetting, _setting_key(key))
        if row is not None:
            await db.delete(row)
    for key, raw_value in changes.items():
        definition = DEFINITION_BY_KEY.get(key)
        if definition is None:
            raise HTTPException(409, f"Определение {key} больше не поддерживается")
        value = _parse_value(definition, raw_value)
        stored = _serialize_stored(definition, value)
        row = await db.get(AppSetting, _setting_key(key))
        if row is None:
            db.add(AppSetting(key=_setting_key(key), value=stored))
        else:
            row.value = stored


async def apply_change(
    change_id: str,
    payload: ApplySettingsIn,
    db: AsyncSession,
    actor: str,
) -> dict[str, object]:
    state = await _state(db, lock=True)
    row = await db.get(RuntimeSettingChange, change_id, with_for_update=True)
    if row is None:
        raise HTTPException(404, "Набор изменений не найден")
    if row.status != "staged":
        raise HTTPException(409, "Набор уже обработан")
    if state.version != payload.expected_version or row.base_version != state.version:
        raise HTTPException(409, "Версия изменилась; создайте новый staged-набор")
    if not hmac.compare_digest(row.fingerprint, payload.fingerprint):
        raise HTTPException(409, "Fingerprint набора не совпадает")
    internal = _load_payload(row)
    _check_environment(internal)
    raw_changes = internal.get("changes")
    raw_clear = internal.get("clear")
    if not isinstance(raw_changes, dict) or not isinstance(raw_clear, list):
        raise HTTPException(409, "Формат набора изменений повреждён")
    # A deployment can change .env without incrementing the database version.
    # Recheck the full candidate under the version lock before writing anything.
    _validated_projection(await _override_rows(db), raw_changes, raw_clear)
    await _write_normalized(db, raw_changes, raw_clear)
    next_version = state.version + 1
    state.version = next_version
    state.updated_at = datetime.utcnow()
    row.status = "applied"
    row.target_version = next_version
    row.applied_at = datetime.utcnow()
    pending = (await db.scalars(
        select(RuntimeSettingChange).where(
            RuntimeSettingChange.status == "staged",
            RuntimeSettingChange.base_version < next_version,
            RuntimeSettingChange.id != row.id,
        )
    )).all()
    for stale in pending:
        stale.status = "superseded"
    db.add(AuditLog(
        action="runtime_settings.applied",
        actor=actor,
        target=row.id,
        details=_canonical({"keys": list(row.keys), "version": next_version, "fingerprint": row.fingerprint}),
    ))
    await db.commit()
    await refresh_runtime_settings(db, force=True)
    return {"version": next_version, "change": _safe_change(row, next_version), "convergence_seconds": POLL_INTERVAL_SECONDS}


async def rollback_change(
    change_id: str,
    payload: RollbackSettingsIn,
    db: AsyncSession,
    actor: str,
) -> dict[str, object]:
    state = await _state(db, lock=True)
    source = await db.get(RuntimeSettingChange, change_id, with_for_update=True)
    if source is None:
        raise HTTPException(404, "Изменение не найдено")
    if state.version != payload.expected_version:
        raise HTTPException(409, "Версия изменилась; обновите страницу")
    if source.status != "applied" or source.target_version != state.version:
        raise HTTPException(409, "Безопасно откатить можно только последнюю применённую версию")
    source_payload = _load_payload(source)
    _check_environment(source_payload)
    restore = source_payload.get("before")
    if not isinstance(restore, dict):
        raise HTTPException(409, "В наборе отсутствует снимок для отката")
    current = await _override_rows(db)
    before = {
        key: {"present": key in current, "value": current[key].value if key in current else None}
        for key in source.keys
    }
    rollback_id = str(uuid.uuid4())
    internal: dict[str, object] = {
        "id": rollback_id,
        "base_version": state.version,
        "environment_fingerprint": _fingerprint(ENVIRONMENT_VALUES),
        "changes": {},
        "clear": [],
        "before": before,
        "restore_raw": restore,
    }
    fingerprint = _fingerprint(internal)
    projected = dict(current)
    for key in source.keys:
        if key not in DEFINITION_BY_KEY:
            raise HTTPException(409, f"Определение {key} больше не поддерживается")
        snapshot = restore.get(key)
        if not isinstance(snapshot, dict) or type(snapshot.get("present")) is not bool:
            raise HTTPException(409, "Снимок отката повреждён")
        if snapshot["present"]:
            stored = snapshot.get("value")
            if not isinstance(stored, str):
                raise HTTPException(409, "Снимок отката повреждён")
            projected[key] = AppSetting(key=_setting_key(key), value=stored)
        else:
            projected.pop(key, None)
    _validated_projection(projected, {}, [])
    for key in source.keys:
        snapshot = restore.get(key)
        if not isinstance(snapshot, dict) or type(snapshot.get("present")) is not bool:
            raise HTTPException(409, "Снимок отката повреждён")
        row = await db.get(AppSetting, _setting_key(key))
        if snapshot["present"]:
            stored = snapshot.get("value")
            if not isinstance(stored, str):
                raise HTTPException(409, "Снимок отката повреждён")
            if row is None:
                db.add(AppSetting(key=_setting_key(key), value=stored))
            else:
                row.value = stored
        elif row is not None:
            await db.delete(row)
    next_version = state.version + 1
    rollback = RuntimeSettingChange(
        id=rollback_id,
        base_version=state.version,
        target_version=next_version,
        status="applied",
        keys=list(source.keys),
        payload_encrypted=encrypt_secret(_canonical(internal)),
        fingerprint=fingerprint,
        actor=actor,
        reason=payload.reason.strip(),
        source_change_id=source.id,
        created_at=datetime.utcnow(),
        applied_at=datetime.utcnow(),
    )
    db.add(rollback)
    source.status = "rolled_back"
    state.version = next_version
    state.updated_at = datetime.utcnow()
    db.add(AuditLog(
        action="runtime_settings.rolled_back",
        actor=actor,
        target=source.id,
        details=_canonical({"rollback_change_id": rollback_id, "keys": list(source.keys), "version": next_version}),
    ))
    await db.commit()
    await refresh_runtime_settings(db, force=True)
    return {"version": next_version, "change": _safe_change(rollback, next_version), "convergence_seconds": POLL_INTERVAL_SECONDS}


async def discard_change(change_id: str, db: AsyncSession, actor: str) -> dict[str, object]:
    row = await db.get(RuntimeSettingChange, change_id, with_for_update=True)
    if row is None:
        raise HTTPException(404, "Набор изменений не найден")
    if row.status != "staged":
        raise HTTPException(409, "Удалить можно только staged-набор")
    row.status = "discarded"
    db.add(AuditLog(
        action="runtime_settings.discarded",
        actor=actor,
        target=row.id,
        details=_canonical({"keys": list(row.keys), "fingerprint": row.fingerprint}),
    ))
    await db.commit()
    return {"discarded": True, "id": row.id}


@router.get("")
async def admin_runtime_settings(
    db: AsyncSession = Depends(get_db),
    admin=Depends(require_permission("settings.runtime.read")),
):
    return await catalog(db, can_write=admin.role == "admin")


@router.post("/stage")
async def admin_stage_runtime_settings(
    payload: StageSettingsIn,
    db: AsyncSession = Depends(get_db),
    admin=Depends(require_permission("settings.runtime.write")),
):
    return await stage_change(payload, db, admin.email)


@router.post("/changes/{change_id}/apply")
async def admin_apply_runtime_settings(
    change_id: str,
    payload: ApplySettingsIn,
    db: AsyncSession = Depends(get_db),
    admin=Depends(require_permission("settings.runtime.write")),
):
    return await apply_change(change_id, payload, db, admin.email)


@router.post("/changes/{change_id}/rollback")
async def admin_rollback_runtime_settings(
    change_id: str,
    payload: RollbackSettingsIn,
    db: AsyncSession = Depends(get_db),
    admin=Depends(require_permission("settings.runtime.write")),
):
    return await rollback_change(change_id, payload, db, admin.email)


@router.delete("/changes/{change_id}")
async def admin_discard_runtime_settings(
    change_id: str,
    db: AsyncSession = Depends(get_db),
    admin=Depends(require_permission("settings.runtime.write")),
):
    return await discard_change(change_id, db, admin.email)
