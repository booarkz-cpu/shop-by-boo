from __future__ import annotations

import hashlib, hmac, ipaddress, json, os, urllib.parse, secrets, pathlib, asyncio, tarfile, shutil, re, logging, socket, uuid, contextvars
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from io import BytesIO
from fastapi import FastAPI, Depends, Request, HTTPException, UploadFile, File, Form, Response, Query
from fastapi.responses import RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import select, func, desc, or_, bindparam, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from sqlalchemy import text as sql_text

from .config import settings
from .db import engine, get_db
from .models import User, Plan, Payment, Subscription, AuditLog, FinancialLedger, AdminUser, AdminSession, AppSetting, BotMenuItem, CustomField, MenuImage, Promotion, PromoCode, PromoRedemption, Advertisement, Broadcast, Reseller, BackupJob, AuthExchangeCode, ReferralReward, PaymentProviderEvent, ReferralLedger, AutoRenewMethod, ProvisioningOperation, RefundRequest, SupportTicket, WithdrawalRequest, WorkerState, ReleaseRecord, SecurityIncident, Job, FraudSignal, PayoutTransaction, FeatureFlag, PaymentProviderHealth, SecurityIncidentEvent, BackupVerification, WebAuthnCredential, UserDevice, Campaign, AutomationRule, MonitoringCheck, TrialGrant, PromoReservation, GiftCode, GiftRedemption, UserSession, Notification, StatusComponent, Deployment, CabinetMenuItem, TariffConstructor, PaymentTaxProfile, PaymentInvoice, PaymentChargeback, PaymentRiskAssessment, PaymentProviderMetric, GiftCard, CorporateAccount, PaymentPriceExperiment
from .payments import YooKassaProvider, PlategaProvider, RollyPayProvider, PLATEGA_REFUNDED, ROLLYPAY_REFUNDED, SandboxProvider, verify_rollypay, verify_platega_headers, staging_create_payment, staging_read_payment, staging_refund_payment, staging_refund_read
from .sandbox_mode import payments_sandbox_allowed, sandbox_checkout_requested, sandbox_local_vpn
from .referral_program import snapshot as referral_snapshot
from .payment_platform import StripePlatform, PayPalPlatform, CryptoGatewayPlatform, AppleStorePlatform, GooglePlayPlatform, PlatformProviderError
from .payment_policy import PAYMENT_AGENTS, PROVIDER_CAPABILITIES, routing_names
from .remnawave import RemnawaveClient, redact_remote
from .provisioner import run_ssh, ProvisionError
from .security import (hash_password, verify_password, encrypt_secret, decrypt_secret, issue_token, decode_token,
                       current_admin, require_permission, verify_totp, generate_recovery_codes, set_recovery_codes, consume_recovery_code)
from .totp import random_base32, provisioning_uri

APP_VERSION = "21.5.1"
# Historical compatibility marker: APP_VERSION = "20.0.8"
# Historical compatibility marker: APP_VERSION = "20.0.7"
# Historical compatibility marker: APP_VERSION = "20.0.6"
# Historical compatibility marker: APP_VERSION = "20.0.5"
# Historical compatibility marker: APP_VERSION = "20.0.4"
# Historical compatibility marker: APP_VERSION = "20.0.3"
# Historical compatibility marker: APP_VERSION = "20.0.0"
# Historical compatibility marker: APP_VERSION = "3.1.6"
# Historical compatibility marker: APP_VERSION = "3.1.5"
# Historical compatibility marker: APP_VERSION = "3.1.4"
# Historical compatibility marker: APP_VERSION = "3.1.3"
# Historical compatibility marker: APP_VERSION = "3.1.2"
# Historical compatibility marker: APP_VERSION = "3.1.1"
# Historical compatibility marker: APP_VERSION = "3.1.0"
# Historical compatibility marker: APP_VERSION = "3.0.1"
# Historical compatibility marker: APP_VERSION = "3.0.0-realise"
# Historical compatibility marker: APP_VERSION = "2.13.0"
# Historical compatibility marker: APP_VERSION = "2.12.0"
# Historical compatibility marker: APP_VERSION = "2.11.0"
# Historical compatibility marker: APP_VERSION = "2.10.0"
# Historical compatibility marker: APP_VERSION = "2.9.0"
# Historical compatibility marker: APP_VERSION = "2.8.0"
# Historical compatibility marker: APP_VERSION = "2.7.0"
# Historical compatibility marker: APP_VERSION = "2.6.0"
# Historical compatibility marker: APP_VERSION = "2.5.0"
# Historical compatibility marker: APP_VERSION = "2.4.0"
# Historical compatibility marker: APP_VERSION = "2.3.0"
# Historical compatibility marker: APP_VERSION = "2.2.1"
# Historical compatibility marker: APP_VERSION = "2.2.0"
# Historical compatibility marker: APP_VERSION = "2.1.0"
# Legacy regression marker: APP_VERSION = "2.0.3-audited"
# Legacy regression marker: APP_VERSION = "2.0.2-audited"
# Previous release contract: APP_VERSION = "2.0.0-realise"
# Previous release contract: APP_VERSION = "1.0.0-realise"
# Historical compatibility marker: APP_VERSION = "44.5.5-enterprise"
# Previous release contract: APP_VERSION = "44.5.0-enterprise"
# APP_VERSION = "43.1.0-production" (legacy compatibility marker for historical regression tests)
# Legacy idempotency contract marker: provider_name}:{user.id}:{plan.id}:{idem} is intentionally superseded by provider-independent canonical idempotency.
logger = logging.getLogger("remnawave")
app = FastAPI(title="Corgi Lusi API", version=APP_VERSION, docs_url=None, redoc_url=None, openapi_url=None)
from .cabinet_api import router as cabinet_router
from .customer_workspace_api import router as customer_workspace_router
from .customer_profile import router as customer_profile_router
from .history_import import router as history_import_router, customer_imported_payments
from .push import router as push_router
from .widget import router as widget_router
from .plugins import router as plugins_router
from .network_intel import router as network_intel_router
from .mail_domain import router as mail_domain_router
from .node_terminal import router as node_terminal_router
from .torrent_detection import router as torrent_router
from .subscription_commerce import router as subscription_commerce_router
from .subscriptions import router as subscriptions_router, reserve_target, check_retry, payment_target, remote_username, owned as owned_subscription
from .mobile_api import router as mobile_router
from .production_api import router as production_router
from .production_launch_api import router as production_launch_router
from .tariff_api import router as tariff_router
from .platform_api import router as platform_router
from .mobile_catalog import router as apps_router
from .v3_api import router as v3_router
from .v6_api import router as v6_router
from .remnawave_shop_api import router as remnawave_shop_router
from .marketplace_api import router as marketplace_router
from .runtime_settings import refresh_runtime_settings, router as runtime_settings_router, runtime_settings_scheduler
app.include_router(cabinet_router)
from .info_pages import router as info_pages_router
app.include_router(info_pages_router)
app.include_router(customer_workspace_router)
app.include_router(customer_profile_router)
app.include_router(history_import_router)
app.include_router(push_router)
app.include_router(widget_router)
app.include_router(plugins_router)
app.include_router(network_intel_router)
app.include_router(mail_domain_router)
app.include_router(node_terminal_router)
app.include_router(torrent_router)
app.include_router(subscription_commerce_router)
app.include_router(subscriptions_router)
app.include_router(runtime_settings_router)
from .support_attachments import router as support_attachments_router
app.include_router(support_attachments_router)
from .support_bridge import router as support_bridge_router
app.include_router(support_bridge_router)
from .support_topology import router as support_topology_router
app.include_router(support_topology_router)
app.include_router(mobile_router)
app.include_router(production_router)
app.include_router(production_launch_router)
app.include_router(tariff_router)
app.include_router(platform_router)
app.include_router(apps_router)
app.include_router(v3_router)
app.include_router(v6_router)
app.include_router(remnawave_shop_router)
app.include_router(marketplace_router)
from .partners import router as partners_router
app.include_router(partners_router)
from .e2e_v2 import router as e2e_v2_router, checkout_allowed as e2e_checkout_allowed, capture_webhook as e2e_capture_webhook
app.include_router(e2e_v2_router)
from .automation import router as automation_router
app.include_router(automation_router)
from .bot_banners import router as bot_banners_router
app.include_router(bot_banners_router)
from .app_config import router as app_config_router
app.include_router(app_config_router)
from .mobile_layout import router as mobile_layout_router
app.include_router(mobile_layout_router)
from .app_login import router as app_login_router
app.include_router(app_login_router)
from .app_growth import router as app_growth_router
app.include_router(app_growth_router)
from .fiscal import router as fiscal_router
app.include_router(fiscal_router)
from .telegram_stars import router as telegram_stars_router, TelegramStarsProvider
app.include_router(telegram_stars_router)
from .remnawave_events import router as remnawave_events_router
app.include_router(remnawave_events_router)
from .growth import router as growth_router
app.include_router(growth_router)
from .ops_alerts import router as ops_alerts_router
app.include_router(ops_alerts_router)
from .account_actions import router as account_actions_router
app.include_router(account_actions_router)
from .surveys import router as surveys_router
app.include_router(surveys_router)
from .giveaways import router as giveaways_router
app.include_router(giveaways_router)
from .passkeys import router as passkeys_router
app.include_router(passkeys_router)
from .customer_passkeys import router as customer_passkeys_router, well_known as app_association_router
app.include_router(customer_passkeys_router)
app.include_router(app_association_router)
from .referral_program import router as referral_program_router
app.include_router(referral_program_router)
from .admin_customer_operations import router as admin_customer_operations_router
app.include_router(admin_customer_operations_router)
from .content_publishing import admin_router as content_admin_router, public_router as content_public_router
app.include_router(content_admin_router)
app.include_router(content_public_router)
from .personal_offers import router as personal_offers_router
app.include_router(personal_offers_router)
from .menu_tree import emoji_router
app.include_router(emoji_router)
from .account_merge import router as account_merge_router
app.include_router(account_merge_router)

MAX_REQUEST_BYTES = 12 * 1024 * 1024
PACKAGE_UPLOAD_BYTES = 80 * 1024 * 1024
RATE_BUCKET: dict[str, list[float]] = {}
LOGIN_BUCKET: dict[str, list[float]] = {}
RATE_WINDOW = 60
MAX_RATE_KEYS = 10000
RATE_LIMITS = {
    "/api/auth/telegram": 30,
    "/api/auth/yandex": 20,
    "/api/auth/yandex/callback": 20,
    "/api/auth/vk": 20,
    "/api/auth/vk/callback": 20,
    "/api/auth/login": 12,
    "/api/auth/mobile/token": 20,
    "/api/auth/mobile/code": 20,
    "/api/mobile/events": 60,
    "/api/me/app-login": 10,
    "/api/app/open": 30,
    "/api/auth/google": 20,
    "/api/auth/google/callback": 20,
    "/api/auth/register": 8,
    "/api/auth/password/reset/request": 5,
    "/api/auth/password/reset/confirm": 5,
    "/api/auth/email/verification/confirm": 8,
    "/api/me/email/verification/request": 5,
    "/api/me/password/change": 5,
    "/api/me/account-merge/authorization": 5,
    "/api/me/account-merge/preview": 12,
    "/api/me/account-merge/confirm": 5,
    "/api/me/surveys": 30,
    "/api/me/giveaways": 30,
    "/api/auth/exchange": 20,
    "/api/payments/create": 20,
    "/api/payments/sandbox/complete": 30,
    "/api/public/servers": 30,
    "/api/app-config": 120,
    "/api/mobile/layout": 120,
    "/api/me/wallet/stars-invoice": 10,
    "/api/me/consent": 30,
    "/api/webhooks/remnawave": 600,
    "/api/me/stars-subscriptions": 20,
    "/api/me/family/join": 10,
    "/api/public/service-status": 60,
    "/api/me/servers": 30,
    "/api/tariff-constructors": 60,
    "/api/agent/heartbeat": 120,
    "/api/agent/observations": 60,
    "/api/promo/validate": 60,
    "/api/me/support/tickets": 10,
    "/api/me/referral/withdrawals": 5,
    "/api/auth/admin/login": 10,
    "/api/admin/auth/login": 8,
    "/api/auth/passkeys/login/options": 8,
    "/api/auth/passkeys/login/verify": 8,
    "/api/auth/passkeys/registration/options": 5,
    "/api/auth/passkeys/registration/verify": 5,
    "/api/admin/auth/passkeys/login/options": 8,
    "/api/admin/auth/passkeys/login/verify": 8,
    "/api/admin/auth/passkeys/registration/options": 5,
    "/api/admin/auth/passkeys/registration/verify": 5,
    "/api/admin/auth/telegram": 8,
}

try:
    from redis.asyncio import Redis
except ImportError:  # pragma: no cover
    Redis = None
redis_client = None
_BACKGROUND_TASKS: set[asyncio.Task] = set()

def _track_task(coro):
    task = asyncio.create_task(coro)
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)
    return task

async def _redis_allowed(key: str, limit: int, window: int) -> bool:
    from .runtime_security import rate_allowed
    return await rate_allowed(redis_client, key, limit, window)

def _peer_is_trusted_proxy(host: str) -> bool:
    from .runtime_security import trusted_proxy
    return trusted_proxy(host, settings.trusted_proxy_cidrs)


def _request_body_limit(method: str, path: str) -> int:
    # Buyer and administrator packages are ZIP files up to 80 MB. Every other
    # route stays on the 12 MB ceiling. A missing Content-Length still uses
    # MAX_REQUEST_BYTES so a chunked body cannot be buffered to 80 MB.
    if method == "POST" and path.startswith("/api/admin/apps/") and path.endswith("/file"):
        return PACKAGE_UPLOAD_BYTES
    return MAX_REQUEST_BYTES

def _client_ip(request: Request) -> str:
    peer = request.client.host if request.client else "unknown"
    forwarded=request.headers.get("x-forwarded-for", "")
    if forwarded and _peer_is_trusted_proxy(peer):
        candidate=forwarded.split(",",1)[0].strip()
        try:
            return str(ipaddress.ip_address(candidate))
        except ValueError as exc:
            logger.debug("Ignored invalid X-Forwarded-For address %r: %s", candidate, exc)
    return peer

def _csrf_cookie_value(request: Request) -> str:
    return request.cookies.get("rw_csrf", "")

def _require_csrf(request: Request):
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}: return
    if request.url.path in {"/api/auth/telegram", "/api/auth/yandex", "/api/auth/yandex/callback", "/api/auth/vk", "/api/auth/vk/callback", "/api/auth/google", "/api/auth/google/callback", "/api/auth/exchange", "/api/auth/login", "/api/auth/register", "/api/admin/auth/login"}: return
    if request.url.path.startswith("/api/webhooks/"): return
    if request.cookies.get("rw_admin") or request.cookies.get("rw_user"):
        supplied=request.headers.get("X-CSRF-Token", "")
        expected=_csrf_cookie_value(request)
        if not expected or not supplied or not hmac.compare_digest(supplied, expected):
            raise HTTPException(403, "CSRF validation failed")

def _set_auth_cookies(response, token: str):
    csrf=secrets.token_urlsafe(32)
    response.set_cookie("rw_csrf", csrf, httponly=False, secure=settings.cookie_secure, samesite=settings.cookie_samesite, max_age=3600)
    return csrf

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        request_id = (request.headers.get("X-Request-ID") or str(uuid.uuid4())).strip()[:64]
        if not re.fullmatch(r"[A-Za-z0-9._:-]{8,64}", request_id):
            request_id = str(uuid.uuid4())
        token = _REQUEST_ID.set(request_id)
        request.state.request_id = request_id
        try:
            return await self._dispatch(request, call_next)
        finally:
            _REQUEST_ID.reset(token)

    async def _dispatch(self, request, call_next):
        from fastapi.responses import JSONResponse
        rate_path = request.url.path
        if request.method == "POST" and rate_path.startswith("/api/me/support/tickets/"):
            rate_path = "/api/me/support/tickets"
        if request.method == 'POST' and re.fullmatch(r'/api/me/surveys/\d+/submit',rate_path):
            rate_path='/api/me/surveys'
        if request.method == 'POST' and re.fullmatch(r'/api/me/giveaways/\d+/enter', rate_path):
            rate_path = '/api/me/giveaways'
        limit = RATE_LIMITS.get(rate_path)
        if limit is None and request.url.path.startswith("/api/admin/"):
            limit = 120 if request.method == "GET" else 40
        if limit and not await _redis_allowed(f"rl:{_client_ip(request)}:{rate_path}", limit, RATE_WINDOW):
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "Too many requests"}, status_code=429, headers={"Retry-After": str(RATE_WINDOW)})
        try:
            _require_csrf(request)
        except HTTPException as exc:
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        if request.url.path in {"/api/payments/create"} and settings.maintenance_mode:
            return _maintenance_response()
        limit = _request_body_limit(request.method, request.url.path)
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                declared = int(content_length)
            except ValueError:
                return JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)
            if declared > limit:
                from fastapi.responses import JSONResponse
                return JSONResponse({"detail": "Request body too large"}, status_code=413)
        else:
            # Content-Length is optional for chunked HTTP requests. Without a streaming
            # guard an attacker could bypass the global 12 MiB limit with an unbounded
            # chunked JSON/multipart body. Consume at most MAX_REQUEST_BYTES+1 bytes and
            # replay the bounded body through Starlette's request cache.
            body_parts=[]; total=0
            try:
                async for chunk in request.stream():
                    total += len(chunk)
                    if total > MAX_REQUEST_BYTES:
                        from fastapi.responses import JSONResponse
                        return JSONResponse({"detail": "Request body too large"}, status_code=413)
                    body_parts.append(chunk)
            except RuntimeError as exc:
                # Request bodies that have already been consumed by an earlier middleware
                # are left untouched.
                logger.debug("Request body already consumed before redaction: %s", exc)
            else:
                request._body=b"".join(body_parts)
        response = await call_next(request)
        response.headers.setdefault("X-Request-ID", getattr(request.state, "request_id", _REQUEST_ID.get()))
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-site")
        if request.url.path.startswith("/api/admin") or request.url.path.startswith("/api/auth") or request.url.path.startswith("/api/me/connection") or request.url.path.startswith("/api/me/dashboard"):
            response.headers.setdefault("Cache-Control", "no-store")
        if request.url.scheme == "https":
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        logger.info("http_request request_id=%s method=%s path=%s status=%s client=%s", getattr(request.state, "request_id", ""), request.method, request.url.path, response.status_code, _client_ip(request))
        return response

app.add_middleware(SecurityHeadersMiddleware)
allowed_hosts = [x.strip() for x in [settings.api_domain, settings.admin_domain, settings.app_domain, settings.cabinet_domain] if x.strip()] + ["localhost", "127.0.0.1"]
if allowed_hosts:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)
pathlib.Path(settings.media_dir).mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=settings.media_dir), name="media")
from .runtime_security import ScopedCORSMiddleware
app.add_middleware(ScopedCORSMiddleware, settings=settings)

class LoginIn(BaseModel):
    email: str = Field(min_length=5, max_length=320)
    password: str = Field(min_length=1, max_length=256)
    otp: str|None = Field(default=None, min_length=6, max_length=10)

class OtpIn(BaseModel):
    otp: str = Field(min_length=6, max_length=8)
class PlanIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    price: Decimal = Field(gt=0, le=1000000, decimal_places=2, max_digits=12)
    duration_days: int = Field(gt=0, le=3650)
    traffic_limit_gb: int|None = Field(default=None, ge=0)
    device_limit: int|None = Field(default=None, ge=1, le=100)
    remnawave_profile_id: str|None = Field(default=None, max_length=255)
    enabled: bool = True
    family_seats: int = Field(default=0, ge=0, le=10)

class TicketIn(BaseModel):
    subject: str = Field(min_length=1, max_length=255)
    message: str = Field(min_length=1, max_length=10000)

class WithdrawalIn(BaseModel):
    amount: Decimal = Field(gt=0, decimal_places=2, max_digits=12)
    destination: str = Field(min_length=3, max_length=255)

class IncidentIn(BaseModel):
    enabled: bool
    severity: str = Field(default="high", pattern="^(low|medium|high|critical)$")
    reason: str = Field(default="", max_length=2000)

class SecretRotateIn(BaseModel):
    secret: str|None = Field(default=None, min_length=16, max_length=4096)

class RefundIn(BaseModel):
    reason: str = Field(default="", max_length=2000)


class SubscriptionActionIn(BaseModel):
    action: str = Field(pattern="^(cancel|resume)$")
    # Optional cancellation survey for the retention report.
    reason: str|None = Field(default=None, pattern="^(price|speed|stability|not_needed|other_service|other)$")
    comment: str = Field(default="", max_length=500)

class GiftRedeemIn(BaseModel):
    subscription_id: int|None = Field(default=None,gt=0)
    new_subscription: bool = False
    code: str = Field(min_length=4, max_length=64)

class GiftCreateIn(BaseModel):
    code: str = Field(min_length=4, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    plan_id: int = Field(gt=0)
    duration_days: int | None = Field(default=None, ge=1, le=3650)
    max_uses: int = Field(default=1, ge=1, le=100000)
    expires_at: datetime | None = None
    purchaser_user_id: int | None = Field(default=None, gt=0)

class AdminTicketReplyIn(BaseModel):
    reply: str = Field(min_length=1, max_length=10000)
    attachment_ids: list[int] = Field(default_factory=list,max_length=3)

class WithdrawalActionIn(BaseModel):
    note: str = Field(default="", max_length=2000)

class FraudDecisionIn(BaseModel):
    status: str = Field(pattern="^(open|resolved|blocked)$")
    note: str = Field(default="", max_length=2000)


class NotificationIn(BaseModel):
    user_id: int = Field(gt=0)
    channel: str = Field(default="in_app", pattern="^(in_app|telegram|email)$")
    kind: str = Field(min_length=2, max_length=64)
    title: str = Field(min_length=1, max_length=255)
    body: str = Field(min_length=1, max_length=10000)
    dedupe_key: str = Field(min_length=1, max_length=160)

class StatusComponentIn(BaseModel):
    slug: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=255)
    status: str = Field(default="operational", pattern="^(operational|degraded|partial_outage|major_outage|maintenance)$")
    message: str = Field(default="", max_length=2000)
    enabled: bool = True
    sort_order: int = Field(default=0, ge=-10000, le=10000)

class DeploymentIn(BaseModel):
    version: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    previous_version: str|None = Field(default=None, max_length=64)
    strategy: str = Field(default="canary", pattern="^(canary|blue_green|rolling)$")
    traffic_percent: int = Field(default=0, ge=0, le=100)

class DeploymentPromoteIn(BaseModel):
    traffic_percent: int = Field(ge=0, le=100)
    error_rate_percent: Decimal = Field(default=Decimal("0"), ge=0, le=100, decimal_places=3)


_REQUEST_ID: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="system")

def _json_ready(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")

async def audit(db, action, actor, target=None, details=None):
    db.add(AuditLog(action=action, actor=actor, target=target, request_id=_REQUEST_ID.get(), details=json.dumps(details, ensure_ascii=False, default=_json_ready) if isinstance(details,dict) else details))

async def record_financial_event(db: AsyncSession, *, operation_key: str, user_id: int|None, payment_id: int|None, kind: str, direction: str, amount: Decimal, currency: str, metadata: dict|None = None):
    """Append an immutable financial event exactly once."""
    if amount <= 0 or direction not in {"credit", "debit"}:
        raise ValueError("Invalid financial ledger entry")
    row = FinancialLedger(operation_key=operation_key, user_id=user_id, payment_id=payment_id, kind=kind, direction=direction, amount=amount, currency=currency, metadata_json=json.dumps(metadata or {}, ensure_ascii=False))
    stmt = sql_text("""INSERT INTO financial_ledger (operation_key,user_id,payment_id,kind,direction,amount,currency,metadata_json,created_at)
        VALUES (:operation_key,:user_id,:payment_id,:kind,:direction,:amount,:currency,:metadata_json,:created_at)
        ON CONFLICT (operation_key) DO NOTHING RETURNING id""").bindparams(bindparam("amount", type_=FinancialLedger.__table__.c.amount.type), bindparam("created_at", type_=FinancialLedger.__table__.c.created_at.type))
    result = await db.execute(stmt, {"operation_key": operation_key, "user_id": user_id, "payment_id": payment_id, "kind": kind, "direction": direction, "amount": amount, "currency": currency, "metadata_json": row.metadata_json, "created_at": datetime.utcnow()})
    if result.first() is not None:
        await db.flush()
        return row
    return await db.scalar(select(FinancialLedger).where(FinancialLedger.operation_key == operation_key))

async def enqueue_notification(db: AsyncSession, *, user_id: int, channel: str, kind: str, title: str, body: str, dedupe_key: str):
    existing=await db.scalar(select(Notification).where(Notification.user_id==user_id, Notification.dedupe_key==dedupe_key))
    if existing:
        return existing
    row=Notification(user_id=user_id,channel=channel,kind=kind,title=title,body=body,dedupe_key=dedupe_key,status="queued")
    db.add(row); await db.flush()
    return row

async def maintenance_enabled(db: AsyncSession) -> bool:
    if settings.maintenance_mode:
        return True
    return (await setting_value(db, "maintenance_mode", "0")) == "1"

def _maintenance_response():
    from fastapi.responses import JSONResponse
    return JSONResponse({"detail":"Service is in maintenance mode"}, status_code=503, headers={"Retry-After":"60"})

@app.on_event("startup")
async def startup():
    global redis_client
    if Redis is None: raise RuntimeError("redis package is required")
    async with AsyncSession(engine, expire_on_commit=False) as runtime_db:
        await refresh_runtime_settings(runtime_db, force=True)
    settings.validate_security()
    redis_client = Redis.from_url(settings.redis_url, decode_responses=True, **settings.redis_connection_kwargs())
    await redis_client.ping()
    # Schema changes are owned by Alembic. Only bootstrap the first admin account from env.
    if not settings.app_secret or len(settings.app_secret) < 32:
        raise RuntimeError("APP_SECRET must be at least 32 characters")
    if settings.payments_sandbox and not payments_sandbox_allowed():
        raise RuntimeError("PAYMENTS_SANDBOX is allowed only when APP_ENV is development, test, or staging")
    if settings.app_env.lower() == "production":
        if settings.app_secret == "change-me":
            raise RuntimeError("APP_SECRET must be changed before production startup")
        if settings.admin_password == "change-me":
            raise RuntimeError("ADMIN_PASSWORD must be changed before production startup")
        if settings.db_password == "change-me":
            raise RuntimeError("DB_PASSWORD must be changed before production startup")
    if not settings.admin_email or not settings.admin_password:
        return
    async with AsyncSession(engine, expire_on_commit=False) as db:
        await _advisory_lock(db, 1300000001)
        existing=(await db.execute(select(AdminUser).where(AdminUser.email==settings.admin_email.lower()))).scalar_one_or_none()
        if not existing:
            db.add(AdminUser(email=settings.admin_email.lower(), password_hash=hash_password(settings.admin_password), role="admin"))
        await seed_starter_plans(db)
        await db.commit()

async def seed_starter_plans(db: AsyncSession) -> int:
    """Create first plans when the shop has none: a test plan in sandbox, otherwise the installer prices."""
    if await db.scalar(select(func.count()).select_from(Plan)):
        return 0
    if payments_sandbox_allowed():
        db.add(Plan(name="Тестовый месяц", price=Decimal("100.00"), duration_days=30, traffic_limit_gb=100, device_limit=3, enabled=True))
        return 1
    created = 0
    # The installer asks for PRICE_1/3/6/12. They become starter plans, switched off
    # until the administrator picks a Remnawave profile for them in «Тарифы».
    for months, name, days, price in ((1, "1 месяц", 30, settings.price_1), (3, "3 месяца", 90, settings.price_3),
                                      (6, "6 месяцев", 180, settings.price_6), (12, "12 месяцев", 365, settings.price_12)):
        if price and price > 0:
            db.add(Plan(name=name, price=Decimal(price), duration_days=days, enabled=False))
            created += 1
    return created

@app.on_event("shutdown")
async def shutdown_resources():
    global redis_client
    tasks=list(_BACKGROUND_TASKS)
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    try:
        await RemnawaveClient.close_shared_client()
    except Exception as exc:
        logger.warning("Remnawave HTTP client shutdown failed: %s", exc)
    if redis_client is not None:
        try:
            await redis_client.aclose()
        except Exception as exc:
            logger.warning("Redis client shutdown failed: %s", exc)
        redis_client = None

@app.on_event("startup")
async def start_backup_scheduler():
    _track_task(runtime_settings_scheduler())
    if settings.worker_role == "api":
        return
    _track_task(backup_scheduler())
    _track_task(fulfillment_retry_scheduler())
    _track_task(expiry_notification_scheduler())
    _track_task(reconciliation_scheduler())
    _track_task(auto_renew_scheduler())
    _track_task(refund_revoke_scheduler())
    from .account_actions import mail_scheduler
    _track_task(mail_scheduler())
    from .admin_customer_operations import import_cleanup_scheduler
    _track_task(import_cleanup_scheduler())
    from .account_merge import account_merge_cleanup_scheduler
    _track_task(account_merge_cleanup_scheduler())
    _track_task(monitor_checks_scheduler())
    from .automation import automation_scheduler
    _track_task(automation_scheduler())
    from .growth import family_scheduler
    _track_task(family_scheduler())
    from .ops_alerts import ops_alert_scheduler
    _track_task(ops_alert_scheduler())
    from .backup_verify import restore_check_scheduler
    _track_task(restore_check_scheduler())

@app.get("/health/live")
async def health_live():
    return {"ok": True, "version": APP_VERSION}

@app.get("/health/ready")
async def health_ready():
    result = await health()
    if not result["ok"]:
        raise HTTPException(503, "Сервис не готов")
    return result

@app.get("/health")
async def health():
    redis_ok=False; db_ok=False
    if redis_client is not None:
        try: await redis_client.ping(); redis_ok=True
        except Exception as exc:
            logger.warning("Non-critical operation failed: %s", exc)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as db: await db.execute(sql_text("SELECT 1")); db_ok=True
    except Exception as exc:
        logger.warning("Non-critical operation failed: %s", exc)
    return {"ok":redis_ok and db_ok,"version":APP_VERSION,"redis":redis_ok,"database":db_ok,"worker_role":settings.worker_role}

def _return_url(order_id:str, base:str|None=None)->str:
    """Where the payment page sends the customer back: the cabinet (or Mini App) with ?order=<order id>,
    so the result screen can show whether the payment went through."""
    from urllib.parse import urlsplit,urlunsplit,parse_qsl,urlencode
    raw=(base if base is not None else (settings.cabinet_url or settings.mini_app_url)) or ""
    if not raw: return raw
    parts=urlsplit(raw)
    query=[(k,v) for k,v in parse_qsl(parts.query,keep_blank_values=True) if k!="order"]+[("order",order_id)]
    return urlunsplit((parts.scheme,parts.netloc,parts.path or "/",urlencode(query),parts.fragment))


@app.get("/api/me/payments/order/{order_id}")
async def my_payment_by_order(order_id:str,request:Request,db:AsyncSession=Depends(get_db)):
    """Status of the customer's own order for the after-payment screen."""
    user=await user_from_token(request,db)
    if len(order_id)>128: raise HTTPException(404,"Платёж не найден")
    p=await db.scalar(select(Payment).where(Payment.order_id==order_id,Payment.user_id==user.id))
    if not p: raise HTTPException(404,"Платёж не найден")
    state="paid" if p.status in {"paid","fulfilled"} and p.fulfillment_status=="completed" else \
          "failed" if p.status in {"failed","canceled","cancelled","expired"} else \
          "refunded" if p.status=="refunded" else "processing" if p.status in {"paid","fulfilled"} else "pending"
    return {"order_id":p.order_id,"state":state,"status":p.status,"fulfillment_status":p.fulfillment_status,"amount":str(p.amount),
            "currency":p.currency,"purpose":p.purpose or "subscription"}


async def send_alert(message:str):
    if settings.alert_telegram_chat_id and settings.bot_token:
        try:
            async with __import__("httpx").AsyncClient(timeout=10, trust_env=False) as c:
                await c.post(f"https://api.telegram.org/bot{settings.bot_token}/sendMessage",json={"chat_id":settings.alert_telegram_chat_id,"text":"⚠️ Corgi Lusi\n"+message})
        except Exception as exc:
            logger.warning("Non-critical operation failed: %s", exc)
    if settings.smtp_host and settings.alert_email:
        import smtplib
        from email.message import EmailMessage
        def _mail():
            msg=EmailMessage(); msg["Subject"]="Corgi Lusi: оповещение"; msg["From"]=settings.smtp_from or settings.smtp_user; msg["To"]=settings.alert_email; msg.set_content(message)
            with smtplib.SMTP(settings.smtp_host,settings.smtp_port,timeout=10) as smtp:
                smtp.starttls();
                if settings.smtp_user: smtp.login(settings.smtp_user,settings.smtp_password)
                smtp.send_message(msg)
        try: await asyncio.to_thread(_mail)
        except Exception as exc:
            logger.warning("Non-critical operation failed: %s", exc)
_METRICS = {"requests_total":0,"errors_total":0,"payment_fulfillment_total":0,"payment_fulfillment_failures":0,"backup_total":0,"backup_failures":0}
@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    if settings.metrics_enabled:
        _METRICS["requests_total"] += 1
    try:
        response = await call_next(request)
        if settings.metrics_enabled and response.status_code >= 500: _METRICS["errors_total"] += 1
        return response
    except Exception:
        if settings.metrics_enabled: _METRICS["errors_total"] += 1
        raise

@app.get("/metrics")
async def metrics(request:Request):
    if not settings.metrics_enabled: raise HTTPException(404,"Metrics disabled")
    if not settings.metrics_token: raise HTTPException(503,"Metrics authentication is not configured")
    if not hmac.compare_digest(request.headers.get("X-Metrics-Token", ""),settings.metrics_token): raise HTTPException(401,"Metrics authentication required")
    extra=""
    try:
        from .platform_api import prometheus_lines
        extra=await asyncio.wait_for(prometheus_lines(), timeout=3)
    except Exception:
        extra=""
    try:
        from .observability import operational_metrics
        from .db import SessionLocal
        async def snapshot():
            async with SessionLocal() as db:
                return await operational_metrics(db)
        extra += await asyncio.wait_for(snapshot(), timeout=3)
    except Exception:
        extra += "# TYPE vpnshop_database_metrics_available gauge\nvpnshop_database_metrics_available 0\n"
    body="\n".join(f"vpnshop_{k} {v}" for k,v in _METRICS.items())+"\n"+extra
    return Response(content=body, media_type="text/plain; version=0.0.4")

# ---------- Telegram auth ----------
def telegram_user_from_init_data(init_data:str):
    pairs=dict(urllib.parse.parse_qsl(init_data,keep_blank_values=True))
    received=pairs.pop("hash",None)
    if not received or not settings.bot_token: raise HTTPException(401,"Invalid Telegram initData")
    try:
        auth_date=int(pairs.get("auth_date", "0"))
    except (TypeError,ValueError):
        raise HTTPException(401,"Invalid Telegram auth date")
    if abs(int(datetime.now(timezone.utc).timestamp())-auth_date)>600: raise HTTPException(401,"Expired Telegram initData")
    secret=hmac.new(b"WebAppData",settings.bot_token.encode(),hashlib.sha256).digest()
    check=hmac.new(secret,"\n".join(f"{k}={pairs[k]}" for k in sorted(pairs)).encode(),hashlib.sha256).hexdigest()
    if not hmac.compare_digest(check,received): raise HTTPException(401,"Invalid Telegram initData")
    try:
        user=json.loads(pairs["user"])
        if not isinstance(user,dict) or not user.get("id"):
            raise ValueError("missing Telegram user id")
        int(user["id"])
        return user
    except (KeyError,TypeError,ValueError,json.JSONDecodeError):
        raise HTTPException(401,"Invalid Telegram user data")

@app.post("/api/auth/telegram")
async def telegram_auth(payload:dict, request:Request, response: Response, db:AsyncSession=Depends(get_db)):
    u=telegram_user_from_init_data(payload.get("initData",""))
    telegram_id=int(u["id"])
    await _advisory_lock(db, 1000000000 + int(hashlib.sha256(str(telegram_id).encode()).hexdigest()[:8],16) % 900000000)
    from .account_merge import identity_user
    user=await identity_user(db,"telegram",telegram_id)
    if not user:
        user=User(telegram_id=telegram_id,username=u.get("username"),referral_code=secrets.token_urlsafe(8).upper()); db.add(user)
    elif user.telegram_id == telegram_id:
        user.username=u.get("username")
    await db.commit(); await db.refresh(user)
    token=await create_user_session(db,user,request)
    await audit(db,"auth.user.login",f"user:{user.id}",None,{"method":"telegram","ip":_client_ip(request)})
    await db.commit()
    response.set_cookie("rw_user", token, httponly=True, secure=settings.cookie_secure, samesite=settings.cookie_samesite, max_age=3600)
    _set_auth_cookies(response, token)
    return {"id":user.id,"telegram_id":user.telegram_id,"username":user.username}

def issue_user_token(user:User, ttl_minutes:int=60, jti:str|None=None):
    now=datetime.now(timezone.utc)
    jti=jti or secrets.token_urlsafe(24)
    return __import__("jwt").encode({"sub":str(user.id),"type":"user","jti":jti,"iat":int(now.timestamp()),"exp":int((now+timedelta(minutes=ttl_minutes)).timestamp())},settings.app_secret,algorithm="HS256")

async def create_user_session(db:AsyncSession,user:User,request:Request,ttl_minutes:int=60):
    if user.deleted_at is not None and not getattr(user,"merged_into_user_id",None):raise HTTPException(401,"User account deleted")
    from .account_merge import canonical_user
    user=await canonical_user(db,user)
    if user.deleted_at is not None:raise HTTPException(401,"User account deleted")
    user=(await db.execute(select(User).where(User.id==user.id).execution_options(populate_existing=True).with_for_update())).scalar_one()
    from .platform_api import reject_restricted
    reject_restricted(user)
    if user.deleted_at is not None:
        raise HTTPException(401,"User account deleted")
    jti=secrets.token_urlsafe(24); now=datetime.utcnow(); expires=now+timedelta(minutes=ttl_minutes)
    db.add(UserSession(user_id=user.id,jti_hash=hashlib.sha256(jti.encode()).hexdigest(),ip=_client_ip(request),user_agent=(request.headers.get("user-agent") or "")[:512],expires_at=expires))
    await db.commit()
    return issue_user_token(user,ttl_minutes,jti)

async def user_from_token(request:Request, db:AsyncSession):
    from .mobile_auth import require_mobile_proof
    require_mobile_proof(request)
    auth=request.headers.get("Authorization","")
    token=auth[7:] if auth.startswith("Bearer ") else request.cookies.get("rw_user")
    if not token: raise HTTPException(401,"User authentication required")
    claims=decode_token(token)
    if claims.get("type")!="user": raise HTTPException(401,"Invalid user token")
    try: user_id=int(claims["sub"])
    except (KeyError,TypeError,ValueError): raise HTTPException(401,"Invalid user token")
    subject_user=await db.get(User,user_id)
    if not subject_user: raise HTTPException(401,"User not found")
    jti=claims.get("jti")
    if not jti: raise HTTPException(401,"User session is not registered")
    session=(await db.execute(select(UserSession).where(UserSession.jti_hash==hashlib.sha256(jti.encode()).hexdigest(),UserSession.revoked_at.is_(None)))).scalar_one_or_none()
    now=datetime.utcnow()
    if not session or session.expires_at<now or session.user_id!=subject_user.id: raise HTTPException(401,"User session expired or revoked")
    current_ua=(request.headers.get("user-agent") or "")[:512]
    if session.user_agent and current_ua and session.user_agent!=current_ua:
        session.revoked_at=now; await db.commit(); raise HTTPException(401,"User session device changed")
    session.last_seen_at=now
    await db.commit()
    from .account_merge import canonical_user
    user=await canonical_user(db,subject_user)
    if user.deleted_at is not None: raise HTTPException(401,"User not found")
    from .platform_api import reject_restricted
    reject_restricted(user)
    return user

@app.post("/api/auth/logout")
async def user_logout(request:Request,response: Response,db:AsyncSession=Depends(get_db)):
    token=request.headers.get("Authorization","")
    token=token[7:] if token.startswith("Bearer ") else request.cookies.get("rw_user")
    if token:
        try:
            claims=decode_token(token)
        except HTTPException as exc:
            if exc.status_code != 401: raise
            claims={}
        try:
            jti=claims.get("jti")
            if jti: await db.execute(__import__('sqlalchemy').update(UserSession).where(UserSession.jti_hash==hashlib.sha256(jti.encode()).hexdigest()).values(revoked_at=datetime.utcnow())); await db.commit()
        except Exception as exc:
            await db.rollback()
            raise HTTPException(503, "Could not revoke user session") from exc
    response.delete_cookie("rw_user"); response.delete_cookie("rw_csrf"); return {"ok":True}

@app.post("/api/me/security/revoke-all")
async def revoke_all_user_sessions(request:Request,db:AsyncSession=Depends(get_db)):
    user=await user_from_token(request,db)
    await db.execute(__import__('sqlalchemy').update(UserSession).where(UserSession.user_id==user.id,UserSession.revoked_at.is_(None)).values(revoked_at=datetime.utcnow()))
    await audit(db,"auth.user.sessions.revoked_all",f"user:{user.id}")
    await db.commit(); return {"ok":True}

@app.get("/api/auth/yandex")
async def yandex_login(request:Request, app:int=0):
    if not settings.yandex_client_id or not settings.yandex_redirect_uri: raise HTTPException(503,"Yandex ID is not configured")
    state=secrets.token_urlsafe(24)
    # State is signed so it is stateless and cannot be forged; app=1 returns to the native app.
    signed=__import__("jwt").encode({"state":state,"app":bool(app),"exp":int((datetime.now(timezone.utc)+timedelta(minutes=10)).timestamp())},settings.app_secret,algorithm="HS256")
    params=urllib.parse.urlencode({"response_type":"code","client_id":settings.yandex_client_id,"redirect_uri":settings.yandex_redirect_uri,"state":signed})
    resp=RedirectResponse("https://oauth.yandex.ru/authorize?"+params)
    resp.set_cookie("yandex_oauth_state",signed,httponly=True,secure=True,samesite="lax",max_age=600)
    return resp

@app.get("/api/auth/yandex/callback")
async def yandex_callback(code:str,state:str,request:Request,db:AsyncSession=Depends(get_db)):
    try:
        if not request.cookies.get("yandex_oauth_state") or not hmac.compare_digest(request.cookies["yandex_oauth_state"],state): raise ValueError()
        state_claims=__import__("jwt").decode(state,settings.app_secret,algorithms=["HS256"])
    except Exception: raise HTTPException(400,"Invalid OAuth state")
    if not settings.yandex_client_secret: raise HTTPException(503,"Yandex ID secret is not configured")
    import httpx
    async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
        token_r=await client.post("https://oauth.yandex.ru/token",data={"grant_type":"authorization_code","code":code,"client_id":settings.yandex_client_id,"client_secret":settings.yandex_client_secret})
        if token_r.status_code!=200: raise HTTPException(401,"Yandex authorization failed")
        access=token_r.json().get("access_token")
        me_r=await client.get("https://login.yandex.ru/info",params={"format":"json"},headers={"Authorization":f"OAuth {access}"})
    if me_r.status_code!=200: raise HTTPException(401,"Could not read Yandex profile")
    info=me_r.json(); yid=str(info.get("id"))
    if not yid or yid == "None": raise HTTPException(401,"Yandex profile has no stable identifier")
    yandex_lock_key=int(hashlib.sha256(yid.encode()).hexdigest()[:8],16) % 900000000
    await _advisory_lock(db, 1100000000 + yandex_lock_key)
    from .account_merge import identity_user
    user=await identity_user(db,"yandex",yid)
    if not user:
        user=User(yandex_id=yid,username=info.get("login") or info.get("display_name"),referral_code=secrets.token_urlsafe(8).upper()); db.add(user)
    elif user.yandex_id == yid:
        user.username=info.get("login") or info.get("display_name") or user.username
    await db.commit(); await db.refresh(user)
    raw=secrets.token_urlsafe(32); code_hash=hashlib.sha256(raw.encode()).hexdigest()
    to_app=bool(state_claims.get("app"))
    db.add(AuthExchangeCode(code_hash=code_hash,user_id=user.id,expires_at=datetime.utcnow()+timedelta(minutes=5 if to_app else 1)))
    await db.commit()
    from .app_login import deep_link
    resp=RedirectResponse(deep_link(raw) if to_app else settings.mini_app_url.rstrip("/")+"/?code="+urllib.parse.quote(raw))
    resp.delete_cookie("yandex_oauth_state")
    return resp

class ExchangeIn(BaseModel):
    code:str=Field(min_length=20,max_length=128)

@app.post("/api/auth/exchange")
async def auth_exchange(payload:ExchangeIn,request:Request,response: Response,db:AsyncSession=Depends(get_db)):
    h=hashlib.sha256(payload.code.encode()).hexdigest()
    row=(await db.execute(select(AuthExchangeCode).where(AuthExchangeCode.code_hash==h).with_for_update())).scalar_one_or_none()
    if not row or row.used_at or row.expires_at < datetime.utcnow(): raise HTTPException(400,"Invalid or expired authorization code")
    user=await db.get(User,row.user_id)
    if not user: raise HTTPException(404,"User not found")
    from .account_merge import canonical_user
    user=await canonical_user(db,user)
    row.used_at=datetime.utcnow(); await db.commit()
    token=await create_user_session(db,user,request); await audit(db,"auth.user.login",f"user:{user.id}",None,{"method":"yandex","ip":_client_ip(request)}); await db.commit(); response.set_cookie("rw_user",token,httponly=True,secure=settings.cookie_secure,samesite=settings.cookie_samesite,max_age=3600); _set_auth_cookies(response,token)
    return {"id":user.id,"telegram_id":user.telegram_id,"yandex_id":user.yandex_id,"username":user.username,"referral_code":user.referral_code,"auto_renew_enabled":user.auto_renew_enabled}

async def active_promotion(db, plan_id:int, now=None):
    now=now or datetime.utcnow()
    rows=(await db.execute(select(Promotion).where(Promotion.enabled.is_(True)).order_by(Promotion.priority.desc(),Promotion.id.desc()))).scalars().all()
    for p in rows:
        if p.starts_at and now < p.starts_at: continue
        if p.ends_at and now > p.ends_at: continue
        if p.plan_ids and plan_id not in p.plan_ids: continue
        return p
    return None

def discounted_amount(price, kind:str, value):
    price=Decimal(str(price)); value=Decimal(str(value))
    # kind=days adds subscription time and must not be treated as a cash discount.
    if kind == "days":
        return Decimal("0.00")
    discount = price * value / Decimal("100") if kind == "percent" else value
    discount=max(Decimal("0"), min(price, discount))
    return discount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

async def promo_discount(db, code:str|None, plan_id:int, price, user_id:int|None=None):
    if not code: return None, Decimal("0.00")
    promo=(await db.execute(select(PromoCode).where(PromoCode.code==code.strip().upper()))).scalar_one_or_none()
    if not promo or not promo.enabled: raise HTTPException(400,"Промокод недействителен")
    from .personal_offers import audience_allowed
    if not await audience_allowed(db,promo.id,user_id):raise HTTPException(400,"Промокод недействителен для этого аккаунта")
    now=datetime.utcnow()
    if promo.starts_at and now < promo.starts_at or promo.ends_at and now > promo.ends_at: raise HTTPException(400,"Срок действия промокода истёк")
    if promo.usage_limit is not None and promo.used_count + promo.reserved_count >= promo.usage_limit: raise HTTPException(400,"Лимит промокода исчерпан")
    if promo.plan_ids and plan_id not in promo.plan_ids: raise HTTPException(400,"Промокод не действует на этот тариф")
    if promo.min_amount is not None and price < promo.min_amount: raise HTTPException(400,"Сумма заказа ниже минимальной для этого промокода")
    if user_id is not None:
        if promo.first_purchase_only:
            paid_count=int(await db.scalar(select(func.count()).select_from(Payment).where(Payment.user_id==user_id,Payment.status.in_({"paid","fulfilled","refunded"}))) or 0)
            if paid_count: raise HTTPException(400,"Промокод доступен только для первой покупки")
        if promo.max_uses_per_user is not None:
            used=int(await db.scalar(select(func.count()).select_from(PromoRedemption).where(PromoRedemption.promo_code_id==promo.id,PromoRedemption.user_id==user_id)) or 0)
            reserved=int(await db.scalar(select(func.count()).select_from(PromoReservation).where(PromoReservation.promo_code_id==promo.id,PromoReservation.user_id==user_id,PromoReservation.status=="reserved")) or 0)
            if used + reserved >= promo.max_uses_per_user: raise HTTPException(400,"Лимит использования промокода для этого пользователя исчерпан")
        if promo.referral_only:
            referred=await db.scalar(select(User.id).where(User.id==user_id, User.referred_by_id.is_not(None)))
            if referred is None: raise HTTPException(400,"Этот промокод доступен только приглашённым пользователям")
    return promo, discounted_amount(price, promo.kind, promo.value)

@app.get("/api/me/devices")
async def my_devices(request: Request, db: AsyncSession=Depends(get_db)):
    user=await user_from_token(request,db)
    sub=await owned_subscription(db,user.id)
    rows=(await db.execute(select(UserDevice).where(UserDevice.user_id==user.id,UserDevice.subscription_id==(sub.id if sub else None)).order_by(UserDevice.created_at.desc()))).scalars().all()
    return [{"id":x.id,"subscription_id":x.subscription_id,"name":x.name,"platform":x.platform,"last_seen_at":x.last_seen_at,"status":x.status,"created_at":x.created_at} for x in rows]

class DeviceRegisterIn(BaseModel):
    device_key: str = Field(min_length=16, max_length=128)
    name: str = Field(default="Устройство", min_length=1, max_length=100)
    platform: str = Field(default="unknown", max_length=64)
    subscription_id: int|None = Field(default=None,gt=0)

@app.post("/api/me/devices")
async def register_device(payload:DeviceRegisterIn, request:Request, db:AsyncSession=Depends(get_db)):
    user=await user_from_token(request,db); now=datetime.utcnow()
    from .platform_api import blacklist_decision
    decision=await blacklist_decision(db, payload.device_key)
    if decision=="block":
        raise HTTPException(403,"Устройство в чёрном списке")
    # Serialize device-limit checks per user. Without this lock, two concurrent
    # registrations could both observe the same active_count and exceed the plan limit.
    await _advisory_lock(db, 710000000 + int(user.id))
    user=await db.scalar(select(User).where(User.id==user.id).execution_options(populate_existing=True).with_for_update())
    if not user or user.deleted_at:raise HTTPException(409,"Аккаунт недоступен")
    x=(await db.execute(select(UserDevice).where(UserDevice.device_key==payload.device_key))).scalar_one_or_none()
    if x and x.user_id!=user.id: raise HTTPException(409,"Устройство уже привязано к другому аккаунту")
    sub=await owned_subscription(db,user.id,payload.subscription_id)
    if payload.subscription_id is not None and not sub:raise HTTPException(404,"Подписка не найдена")
    if sub and sub.plan_id:
        plan=await db.get(Plan,sub.plan_id)
        device_limit=sub.device_limit_snapshot if sub.device_limit_snapshot is not None or sub.unit_price_per_day is not None else (plan.device_limit if plan else None)
        if device_limit is not None and (not x or x.status != "active" or x.subscription_id!=sub.id):
            active_count=int(await db.scalar(select(func.count()).select_from(UserDevice).where(UserDevice.user_id==user.id,UserDevice.subscription_id==sub.id,UserDevice.status=="active")) or 0)
            if active_count >= device_limit: raise HTTPException(409,"Достигнут лимит устройств тарифа")
    if not x:
        x=UserDevice(user_id=user.id,device_key=payload.device_key,name=payload.name,platform=payload.platform); db.add(x)
    else: x.name=payload.name; x.platform=payload.platform; x.status="active"; x.revoked_at=None
    x.subscription_id=sub.id if sub else None
    if decision=="alert":
        from .models import AbuseViolation
        db.add(AbuseViolation(user_id=user.id, score=40, recommendation="warn", analyzers={"hits":[{"name":"hwid","detail":"черный список alert"}]}, summary="Регистрация устройства из чёрного списка со действием alert", status="open", created_at=now))
    x.last_ip=_client_ip(request); x.last_seen_at=now; await db.commit(); await db.refresh(x)
    return {"ok":True,"id":x.id,"status":x.status}

@app.post("/api/me/devices/{device_id}/revoke")
async def revoke_device(device_id:int,request:Request,db:AsyncSession=Depends(get_db)):
    user=await user_from_token(request,db); x=await db.get(UserDevice,device_id)
    if not x or x.user_id!=user.id: raise HTTPException(404,"Устройство не найдено")
    x.status="revoked"; x.revoked_at=datetime.utcnow(); await db.commit(); return {"ok":True}

class TrialIn(BaseModel):
    plan_id: int = Field(gt=0)
    days: int = Field(gt=0, le=30)

@app.post("/api/me/trial")
async def claim_trial(payload:TrialIn,request:Request,db:AsyncSession=Depends(get_db)):
    user=await user_from_token(request,db)
    from .platform_api import reject_restricted
    reject_restricted(user)
    # Serialize trial claims per user; the UNIQUE constraint remains the final
    # database invariant, while this prevents duplicate grants under concurrency.
    await _advisory_lock(db, 720000000 + int(user.id))
    if await db.scalar(select(TrialGrant).where(TrialGrant.user_id==user.id)): raise HTTPException(409,"Пробный период уже использован")
    from .remnawave_events import trial_guard
    trial_ip_hash=await trial_guard(db,user,_client_ip(request))
    now=datetime.utcnow()
    active_sub=(await db.execute(select(Subscription).where(Subscription.user_id==user.id, Subscription.lifecycle_status.in_(["active","cancel_scheduled","grace"]), or_(Subscription.expires_at.is_(None), Subscription.expires_at>now)).limit(1).with_for_update())).scalar_one_or_none()
    if active_sub:
        raise HTTPException(409,"Пробный период недоступен при действующей подписке")
    plan=await db.get(Plan,payload.plan_id)
    if not plan or not plan.enabled: raise HTTPException(404,"Тариф не найден")
    from .tariff_api import linked_constructor_id
    if await linked_constructor_id(db, plan.id):
        raise HTTPException(400,"Пробный период для конструктора недоступен")
    max_days=max(1,min(int(settings.trial_max_days or 3),30))
    days=min(int(payload.days), max_days)
    target=await reserve_target(db,user,plan.id,{})
    now=datetime.utcnow(); grant=TrialGrant(user_id=user.id,subscription_id=target.id,plan_id=plan.id,days=days,
        traffic_limit_gb_snapshot=plan.traffic_limit_gb,device_limit_snapshot=plan.device_limit,
        remnawave_profile_id_snapshot=plan.remnawave_profile_id,expires_at=now+timedelta(days=days),ip_hash=trial_ip_hash);
    db.add(grant); await db.flush(); db.add(Job(job_key=f"trial:{grant.id}",kind="trial",status="queued",attempts=0,max_attempts=5,payload={"trial_id":grant.id})); await audit(db,"trial.granted",str(user.id),str(plan.id),{"days":days}); await db.commit()
    return {"ok":True,"status":"queued","expires_at":grant.expires_at,"plan_id":grant.plan_id,"days":grant.days}

@app.get("/api/public/config")
async def public_config(db:AsyncSession=Depends(get_db)):
    settings_rows=(await db.execute(select(AppSetting).where(AppSetting.key.in_({"app_name","bot_name","bot_start_image","miniapp_title","miniapp_subtitle","miniapp_background_color","miniapp_background_image","miniapp_image","miniapp_instructions","miniapp_buttons"})))).scalars().all()
    values={x.key:x.value for x in settings_rows}
    fields=(await db.execute(select(CustomField).where(CustomField.enabled.is_(True)).order_by(CustomField.sort_order,CustomField.id))).scalars().all()
    menus=(await db.execute(select(BotMenuItem).where(BotMenuItem.enabled.is_(True)).order_by(BotMenuItem.sort_order,BotMenuItem.id))).scalars().all()
    images=(await db.execute(select(MenuImage).where(MenuImage.enabled.is_(True)).order_by(MenuImage.sort_order,MenuImage.id))).scalars().all()
    now=datetime.utcnow(); ads=(await db.execute(select(Advertisement).where(Advertisement.enabled.is_(True)).order_by(Advertisement.sort_order,Advertisement.id))).scalars().all()
    ads=[a for a in ads if (not a.starts_at or now>=a.starts_at) and (not a.ends_at or now<=a.ends_at)]
    promos=(await db.execute(select(Promotion).where(Promotion.enabled.is_(True)).order_by(Promotion.priority.desc(),Promotion.id.desc()))).scalars().all()
    promos=[p for p in promos if (not p.starts_at or now>=p.starts_at) and (not p.ends_at or now<=p.ends_at)]
    mini_buttons=[]
    try:
        mini_buttons=json.loads(values.get("miniapp_buttons","[]"))
        if not isinstance(mini_buttons,list): mini_buttons=[]
    except Exception: mini_buttons=[]
    try:
        payment_providers=await _payment_provider_order(db,None)
    except HTTPException:
        payment_providers=[]
    return {"default_language": settings.default_language if settings.default_language in {"ru","en"} else "ru","required_channel":settings.required_telegram_channel,"app_name":values.get("app_name","Корги Люси"),"bot_name":values.get("bot_name","Корги Люси"),"bot_start_image":values.get("bot_start_image",""),"menu":[{"title":m.title,"action":m.action,"type":m.item_type,"id":m.id,"parent_id":m.parent_id,"style":m.style,"icon_custom_emoji_id":m.icon_custom_emoji_id,"icon":m.icon} for m in menus],"fields":[{"key":f.key,"label":f.label,"type":f.field_type,"value":f.value} for f in fields],"images":[{"title":i.title,"url":"/media/"+i.filename} for i in images],"yandex_enabled":bool(settings.yandex_client_id and settings.yandex_redirect_uri),"vk_enabled":bool(settings.vk_client_id and settings.vk_redirect_uri),"email_auth_enabled":True,"trial_days":max(1,min(int(settings.trial_max_days or 3),30)),"payments_sandbox":bool(settings.payments_sandbox),"cabinet_url":settings.cabinet_url or settings.mini_app_url,"bot_username":settings.bot_username,"advertisements":[{"title":a.title,"text":a.text,"image_url":a.image_url,"button_text":a.button_text,"button_url":a.button_url} for a in ads],"promotions":[{"id":p.id,"name":p.name,"kind":p.kind,"value":float(p.value),"description":p.description,"plan_ids":p.plan_ids} for p in promos],"miniapp":{"title":values.get("miniapp_title",values.get("app_name","Корги Люси")),"subtitle":values.get("miniapp_subtitle",""),"background_color":values.get("miniapp_background_color","#f5f7fb"),"background_image":values.get("miniapp_background_image",""),"image":values.get("miniapp_image",""),"instructions":values.get("miniapp_instructions",""),"buttons":mini_buttons},"payment_providers":payment_providers}

@app.get("/api/me")
async def api_me(request:Request,db:AsyncSession=Depends(get_db)):
    user=await user_from_token(request,db)
    return {"id":user.id,"telegram_id":user.telegram_id,"yandex_id":user.yandex_id,"username":user.username,"referral_code":user.referral_code,"auto_renew_enabled":user.auto_renew_enabled}

@app.get("/api/plans")
async def plans(db:AsyncSession=Depends(get_db)):
    rows=(await db.execute(select(Plan).where(Plan.enabled.is_(True)).order_by(Plan.id))).scalars().all()
    anchor_ids=set((await db.execute(select(TariffConstructor.plan_id).where(TariffConstructor.plan_id.is_not(None)))).scalars().all())
    out=[]
    for p in rows:
        if p.id in anchor_ids: continue
        price=Decimal(str(p.price)); promo=await active_promotion(db,p.id); discount=discounted_amount(price,promo.kind,promo.value) if promo else Decimal("0.00")
        final_price=(price-discount).quantize(Decimal("0.01"),rounding=ROUND_HALF_UP)
        out.append({"id":p.id,"name":p.name,"price":float(price),"final_price":float(final_price),"discount":float(discount),"discount_percent":float((discount/price*Decimal("100")).quantize(Decimal("0.01"))) if price else 0,"promotion":({"id":promo.id,"name":promo.name,"kind":promo.kind,"value":float(promo.value),"description":promo.description} if promo else None),"duration_days":p.duration_days,"traffic_limit_gb":p.traffic_limit_gb,"device_limit":p.device_limit,"family_seats":int(p.family_seats or 0)})
    return out

@app.get("/api/promo/validate")
async def validate_promo(code:str,plan_id:int,request:Request,db:AsyncSession=Depends(get_db)):
    plan=await db.get(Plan,plan_id)
    if not plan or not plan.enabled: raise HTTPException(404,"Тариф не найден")
    user=await user_from_token(request,db); promo,discount=await promo_discount(db,code,plan_id,Decimal(str(plan.price)),user.id)
    return {"code":promo.code,"discount":float(discount),"final_price":float((Decimal(str(plan.price))-discount).quantize(Decimal("0.01"),rounding=ROUND_HALF_UP))}

class CampaignIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    kind: str = Field(default="broadcast", pattern="^(broadcast|winback|retention|promotion)$")
    status: str = Field(default="draft", pattern="^(draft|scheduled|running|paused|completed)$")
    audience: dict|None = None
    content: dict = Field(default_factory=dict)
    starts_at: datetime|None = None
    ends_at: datetime|None = None

class RuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    event: str = Field(min_length=2, max_length=64)
    conditions: dict = Field(default_factory=dict)
    actions: dict = Field(default_factory=dict)
    enabled: bool = False
    priority: int = Field(default=100, ge=0, le=10000)

class MonitoringCheckIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    url: str = Field(min_length=8, max_length=2048)
    method: str = Field(default="GET", pattern="^(GET|HEAD)$")
    interval_seconds: int = Field(default=60, ge=15, le=86400)
    timeout_seconds: int = Field(default=10, ge=1, le=60)
    enabled: bool = True

# ---------- Admin authentication / MFA ----------
@app.post("/api/admin/auth/telegram")
async def admin_telegram_login(payload:dict,request:Request,response:Response,db:AsyncSession=Depends(get_db)):
    u=telegram_user_from_init_data(payload.get("initData",""))
    admin=(await db.execute(select(AdminUser).where(AdminUser.telegram_id==int(u["id"]),AdminUser.disabled.is_(False)))).scalar_one_or_none()
    if not admin: raise HTTPException(403,"Telegram ID не привязан к администратору")
    if admin.mfa_enabled: raise HTTPException(403,"Для этого администратора требуется вход по email и 2FA")
    jti=secrets.token_urlsafe(32); token=issue_token(admin,False,jti=jti)
    db.add(AdminSession(admin_id=admin.id,jti_hash=hashlib.sha256(jti.encode()).hexdigest(),ip=_client_ip(request),user_agent=request.headers.get("user-agent",""),created_at=datetime.utcnow(),last_seen_at=datetime.utcnow(),expires_at=datetime.utcnow()+timedelta(minutes=30)))
    admin.last_login_at=datetime.utcnow(); await audit(db,"admin.telegram_login",str(admin.telegram_id),admin.email); await db.commit()
    response.set_cookie("rw_admin",token,httponly=True,secure=settings.cookie_secure,samesite=settings.cookie_samesite,max_age=1800)
    _set_auth_cookies(response,token)
    return {"ok":True,"admin_id":admin.id}

@app.post("/api/admin/auth/login")
async def admin_login(payload:LoginIn, request:Request, response:Response, db:AsyncSession=Depends(get_db)):
    from .mobile_auth import require_mobile_proof
    require_mobile_proof(request)
    # Behind Caddy, request.client is the proxy container. Use the trusted
    # proxy-normalized client IP so one remote address cannot throttle every
    # administrator through the shared reverse-proxy address.
    client_ip=_client_ip(request)
    limiter_key=f"login:{client_ip}:{payload.email.lower().strip()}"
    if not await _redis_allowed(limiter_key,8,900): raise HTTPException(429,"Too many login attempts. Try again later.", headers={"Retry-After":"900"})
    admin=(await db.execute(select(AdminUser).where(AdminUser.email==payload.email.lower().strip()).with_for_update())).scalar_one_or_none()
    if not admin or admin.disabled or not verify_password(payload.password, admin.password_hash):
        raise HTTPException(401,"Invalid credentials")
    if admin.mfa_enabled:
        if not payload.otp: raise HTTPException(401,"MFA code required or invalid")
        if not verify_totp(admin,payload.otp) and not consume_recovery_code(admin,payload.otp):
            raise HTTPException(401,"MFA code required or invalid")
    admin.last_login_at=datetime.utcnow();
    from .runtime_security import reset_login_attempts
    await reset_login_attempts(redis_client, limiter_key)
    await db.commit()
    jti=secrets.token_urlsafe(32)
    expires=datetime.utcnow()+timedelta(minutes=30)
    db.add(AdminSession(admin_id=admin.id,jti_hash=hashlib.sha256(jti.encode()).hexdigest(),ip=_client_ip(request),user_agent=(request.headers.get("user-agent") or "")[:512],expires_at=expires))
    token=issue_token(admin,admin.mfa_enabled,30,jti=jti)
    await db.commit()
    from .mobile_auth import mobile_client_name, session_body
    body={"mfa_enabled":bool(admin.mfa_enabled),"role":admin.role,"email":admin.email}
    if mobile_client_name(request):
        return session_body(request, token, body)
    response.set_cookie("rw_admin",token,httponly=True,secure=settings.cookie_secure,samesite=settings.cookie_samesite,max_age=1800)
    _set_auth_cookies(response,token)
    return body

@app.post("/api/admin/auth/mfa/setup")
async def mfa_setup(db:AsyncSession=Depends(get_db), admin=Depends(require_permission("manage_own_mfa"))):
    if admin.mfa_enabled: raise HTTPException(409,"MFA is already enabled")
    secret=random_base32(); admin.totp_secret_encrypted=encrypt_secret(secret); codes=generate_recovery_codes(); set_recovery_codes(admin,codes); await db.commit()
    return {"secret":secret,"otpauth_url":provisioning_uri(secret,admin.email,"Corgi Lusi"),"recovery_codes":codes}

@app.post("/api/admin/auth/mfa/enable")
async def mfa_enable(payload:OtpIn, db:AsyncSession=Depends(get_db), admin=Depends(require_permission("manage_own_mfa"))):
    if admin.mfa_enabled: raise HTTPException(409,"MFA is already enabled")
    if not admin.totp_secret_encrypted or not verify_totp(admin,payload.otp): raise HTTPException(401,"Invalid MFA code")
    admin.mfa_enabled=True; await audit(db,"mfa.enabled",admin.email,admin.email); await db.commit()
    return {"ok":True,"mfa_enabled":True}

class PasswordConfirm(BaseModel):
    password: str = Field(min_length=8, max_length=256)

@app.post("/api/admin/auth/mfa/disable")
async def mfa_disable(payload:PasswordConfirm, db:AsyncSession=Depends(get_db), admin=Depends(require_permission("manage_own_mfa"))):
    if not admin.mfa_enabled: return {"ok":True,"mfa_enabled":False}
    if not verify_password(payload.password, admin.password_hash): raise HTTPException(401,"Invalid password")
    admin.mfa_enabled=False; admin.totp_secret_encrypted=None; admin.recovery_codes_encrypted=None; await audit(db,"mfa.disabled",admin.email,admin.email); await db.commit()
    return {"ok":True,"mfa_enabled":False}

@app.get("/api/admin/auth/mfa/status")
async def mfa_status(admin=Depends(require_permission("read"))): return {"enabled":bool(admin.mfa_enabled)}

# ---------- Feature flags ----------
async def _feature_flag(db: AsyncSession, key: str):
    return (await db.execute(select(FeatureFlag).where(FeatureFlag.key==key))).scalar_one_or_none()

async def feature_enabled(db: AsyncSession, key: str, default: bool = True) -> bool:
    row = await _feature_flag(db, key)
    return bool(row.enabled) if row is not None else default

# ---------- Payments: moved to payments_api.py (imported at the end of this file) ----------

# ---------- Reliability, sessions, analytics, referrals ----------
async def fulfillment_retry_scheduler():
    while True:
        try:
            async with AsyncSession(engine,expire_on_commit=False) as db:
                rows=(await db.execute(select(Payment).where(Payment.fulfillment_status=="failed",Payment.next_retry_at<=datetime.utcnow()).order_by(Payment.next_retry_at).limit(10))).scalars().all()
                for p in rows:
                    try: await fulfill(p.id,db)
                    except Exception as exc:
                        logger.warning("Non-critical operation failed: %s", exc)
            await asyncio.sleep(15)
        except Exception: await asyncio.sleep(15)

async def refund_revoke_scheduler():
    while True:
        try:
            async with AsyncSession(engine,expire_on_commit=False) as db:
                providers={"yookassa":YooKassaProvider(),"platega":PlategaProvider(),"rollypay":RollyPayProvider(),"stripe":StripePlatform(),"paypal":PayPalPlatform(),"telegram_stars":TelegramStarsProvider()}
                pending=(await db.execute(select(RefundRequest).where(RefundRequest.status=="processing",RefundRequest.provider_refund_id.is_not(None)).order_by(RefundRequest.updated_at).limit(50))).scalars().all()
                for r in pending:
                    p=await db.get(Payment,r.payment_id); provider=providers.get(p.provider) if p else None
                    if not p or not provider or not hasattr(provider,"get_refund_status"): continue
                    try:
                        status=await provider.get_refund_status(r.provider_refund_id)
                        if status in {"succeeded","paid","completed","refunded"}:
                            # Reconciliation is another refund side-effect entry point. It must
                            # serialize with fulfillment just like manual refund execution;
                            # otherwise a background poll can mark a payment refunded while
                            # an already-running fulfillment is still provisioning it.
                            user_lock, user_token = await _acquire_user_fulfillment_lock(p.user_id,ttl=300)
                            payment_lock = payment_token = None
                            try:
                                payment_lock, payment_token = await _acquire_payment_side_effect_lock(p.id)
                                p=(await db.execute(select(Payment).where(Payment.id==p.id).execution_options(populate_existing=True).with_for_update())).scalar_one()
                                r=(await db.execute(select(RefundRequest).where(RefundRequest.id==r.id).execution_options(populate_existing=True).with_for_update())).scalar_one()
                                if p.status == "refunded" and r.status == "refunded":
                                    continue
                                r.status="refunded"; p.status="refunded"; p.fulfillment_terminal=True; r.updated_at=datetime.utcnow()
                                await record_financial_event(db,operation_key=f"payment:{p.id}:refund:{r.id}",user_id=p.user_id,payment_id=p.id,kind="refund",direction="debit",amount=Decimal(str(p.amount)),currency=p.currency,metadata={"provider":p.provider,"refund_id":r.id,"provider_refund_id":r.provider_refund_id})
                                try:
                                    revoke_result=await _safe_revoke_for_refunded_payment(db,p,"system","subscription.revoked.refund.reconciled")
                                except Exception as exc:
                                    r.status="refunded_pending_revoke"; r.reason=(r.reason or "")+"\nRevoke pending: "+str(exc)[:500]; revoke_result={"revoked":False,"reason":"revoke_failed"}
                                reversal_result=await _reverse_referral_reward_for_refund(db,p,"system") if r.status == "refunded" else {"reversed":False}
                                await audit(db,"payment.refund.reconciled","system",str(p.id),{"provider_status":status,**revoke_result,**reversal_result})
                            finally:
                                if payment_lock and payment_token:
                                    await _release_payment_side_effect_lock(payment_lock, payment_token)
                                await _release_payment_side_effect_lock(user_lock,user_token)
                        elif status in {"canceled","cancelled","failed","rejected"}:
                            r.status="failed"; r.reason=(r.reason or "")+f"\nProvider refund status: {status}"; r.updated_at=datetime.utcnow()
                    except Exception as exc:
                        r.reason=(r.reason or "")+"\nRefund reconciliation pending: "+str(exc)[:300]
                rows=(await db.execute(select(RefundRequest).where(RefundRequest.status=="refunded_pending_revoke").order_by(RefundRequest.updated_at).limit(20))).scalars().all()
                for r in rows:
                    p=await db.get(Payment,r.payment_id)
                    if not p: continue
                    payment_lock=payment_token=None
                    user_lock=user_token=None
                    try:
                        user_lock,user_token=await _acquire_user_fulfillment_lock(p.user_id,ttl=300)
                        payment_lock,payment_token=await _acquire_payment_side_effect_lock(p.id)
                        # Re-check terminal state after acquiring the shared lock. This is the
                        # same critical section used by fulfillment and manual refund execution.
                        p=(await db.execute(select(Payment).where(Payment.id==p.id).execution_options(populate_existing=True).with_for_update())).scalar_one()
                        r=(await db.execute(select(RefundRequest).where(RefundRequest.id==r.id).execution_options(populate_existing=True).with_for_update())).scalar_one()
                        if r.status != "refunded_pending_revoke": continue
                        revoke_result=await _safe_revoke_for_refunded_payment(db,p,"system","subscription.revoked.refund.retry")
                        r.status="refunded"; r.updated_at=datetime.utcnow()
                        reversal_result=await _reverse_referral_reward_for_refund(db,p,"system")
                        await audit(db,"subscription.revoked.refund.retry","system",str(p.id),{"payment_id":p.id,**revoke_result,**reversal_result})
                    except Exception as exc:
                        r.reason=(r.reason or "")+"\nRevoke retry pending: "+str(exc)[:500]
                    finally:
                        if payment_lock and payment_token:
                            await _release_payment_side_effect_lock(payment_lock,payment_token)
                        if user_lock and user_token:
                            await _release_payment_side_effect_lock(user_lock,user_token)
                await db.commit()
        except Exception as exc:
            logger.warning("Refund scheduler failure: %s", exc)
            await send_alert("Refund scheduler failure")
        await asyncio.sleep(30)

def auto_renew_chargeable(user:User,sub:Subscription)->bool:
    """Only a live subscription of an unrestricted customer may be charged automatically."""
    return (user.restricted_at is None and sub.scheduled_cancel_at is None
            and (sub.lifecycle_status or "active") in {"active","grace"})


RECURRING_IDEMPOTENCE_WINDOW=timedelta(hours=23)


async def adopt_or_retry_recurring(payment:Payment,method:AutoRenewMethod,plan:Plan)->str:
    """Resolve a recurring intent left in «creating»: adopt / retry / unknown."""
    provider=YooKassaProvider()
    created=payment.created_at or datetime.utcnow()
    found=await provider.find_by_order_id(payment.order_id,created-timedelta(hours=1))
    if found and found.get("id"):
        payment.provider_payment_id=str(found["id"]); payment.status="pending"
        return "adopted"
    if datetime.utcnow()-created>RECURRING_IDEMPOTENCE_WINDOW:
        payment.status="creation_unknown"; payment.fulfillment_terminal=True
        payment.fulfillment_error="Recurring charge outcome unknown after the idempotence window; reconciliation required"
        return "unknown"
    token=decrypt_secret(method.external_token_encrypted)
    result=await provider.charge_recurring(Decimal(str(payment.amount)),payment.order_id,f"Auto-renew {plan.name}",token)
    payment.provider_payment_id=result["id"]; payment.status="pending"
    return "retried"


async def _record_paid(db:AsyncSession,payment:Payment):
    await record_financial_event(db, operation_key=f"payment:{payment.id}:paid", user_id=payment.user_id, payment_id=payment.id, kind="payment", direction="credit", amount=Decimal(str(payment.amount)), currency=payment.currency, metadata={"provider": payment.provider, "order_id": payment.order_id})


async def auto_renew_scheduler():
    while True:
        try:
            await asyncio.sleep(900)
            if not settings.auto_renew_enabled: continue
            async with AsyncSession(engine,expire_on_commit=False) as db:
                # Auto-renew is a real payment operation and must obey the same
                # production gate and payments feature flag as interactive checkout.
                if await maintenance_enabled(db): continue
                if await feature_enabled(db, "payments", True) is False: continue
                if not await production_payments_allowed(db): continue
                cutoff=datetime.utcnow()+timedelta(days=max(1,min(int(settings.auto_renew_lead_days or 3),14)))
                rows=(await db.execute(select(User,Subscription,Plan,AutoRenewMethod).join(Subscription,Subscription.user_id==User.id).join(Plan,Plan.id==Subscription.plan_id).join(AutoRenewMethod,AutoRenewMethod.user_id==User.id).where(User.auto_renew_enabled.is_(True),Subscription.auto_renew_enabled.is_(True),AutoRenewMethod.enabled.is_(True),AutoRenewMethod.status.in_(["active","past_due"]),Subscription.expires_at.is_not(None),Subscription.expires_at<=cutoff,Subscription.expires_at>datetime.utcnow(),((Subscription.next_renewal_at.is_(None))|(Subscription.next_renewal_at<=datetime.utcnow()))).limit(25))).all()
                for user,sub,plan,method in rows:
                    candidate_subscription_id=sub.id
                    if method.provider != "yookassa": continue
                    # Account deletion shares this user-level lock. Re-load the user after
                    # acquiring it so a row selected by the scheduler cannot become a charge
                    # after the account has been anonymized.
                    user_lock=user_token=None
                    try:
                        user_lock,user_token=await _acquire_user_fulfillment_lock(user.id,ttl=900)
                    except Exception:
                        continue
                    try:
                        user=(await db.execute(select(User).where(User.id==user.id).execution_options(populate_existing=True).with_for_update())).scalar_one_or_none()
                        if not user or user.deleted_at is not None or not user.auto_renew_enabled:
                            continue
                        method=(await db.execute(select(AutoRenewMethod).where(AutoRenewMethod.user_id==user.id).with_for_update())).scalar_one_or_none()
                        sub=(await db.execute(select(Subscription).where(Subscription.user_id==user.id,Subscription.id==candidate_subscription_id).execution_options(populate_existing=True).with_for_update())).scalar_one_or_none()
                        plan=await db.get(Plan,sub.plan_id) if sub else None
                        if not method or not sub or not sub.auto_renew_enabled or not plan or not method.enabled or method.status not in {"active","past_due"} or method.provider != "yookassa":
                            continue
                        if not sub.expires_at or sub.expires_at <= datetime.utcnow() or sub.expires_at > cutoff:
                            continue
                        # A cancelled, suspended or restricted subscription is never charged:
                        # cancellation keeps auto_renew_enabled so «undo» restores it, and an
                        # abuse restriction must not be reversed by a renewal's fulfill().
                        if not auto_renew_chargeable(user,sub):
                            continue
                        from .subscriptions import ensure_no_pending_gift
                        try:await ensure_no_pending_gift(db,sub.id)
                        except HTTPException:continue
                        date_key=(sub.expires_at or datetime.utcnow()).strftime("%Y%m%d")
                        order_id=f"auto-renew-{user.id}-sub-{sub.id}-{plan.id}-{date_key}"
                        renew_lock=renew_token=None
                        try:
                            renew_lock,renew_token=await _acquire_redis_lock(f"lock:auto-renew:user:{user.id}:{date_key}",ttl=900,conflict_message="Auto-renew is already in progress")
                        except RuntimeError:
                            continue
                        prefix=f"auto-renew-{user.id}-sub-{sub.id}-{plan.id}-{date_key}"
                        attempts=(await db.execute(select(Payment).where(Payment.user_id==user.id,Payment.subscription_id==sub.id,or_(Payment.order_id.like(prefix+"%"),Payment.order_id.like(f"auto-renew-{user.id}-{plan.id}-{date_key}%")),Payment.provider=="yookassa").order_by(Payment.id.desc()))).scalars().all()
                        existing=attempts[0] if attempts else None
                        if existing:
                            if existing.currency!=settings.default_currency:
                                method.last_error='Recurring payment currency changed; operator reconciliation required'
                                await db.commit();continue
                            if existing.status=="creating" and existing.provider_payment_id is None:
                                # The previous run may have died after YooKassa accepted the
                                # charge. Adopt that payment first; YooKassa keeps idempotence
                                # keys for 24 hours only, so an older intent is never re-sent —
                                # it goes to reconciliation (creation_unknown) instead.
                                adopted=await adopt_or_retry_recurring(existing,method,plan)
                                await db.commit()
                                if adopted=="unknown": continue
                            if existing.status=="pending":
                                try:
                                    provider=YooKassaProvider()
                                    verified=await provider.verify_succeeded(existing.provider_payment_id,Decimal(str(existing.amount)),existing.currency,existing.order_id)
                                    if verified:
                                        payment_lock, payment_token = await _acquire_payment_side_effect_lock(existing.id)
                                        try:
                                            existing=(await db.execute(select(Payment).where(Payment.id==existing.id).execution_options(populate_existing=True).with_for_update())).scalar_one()
                                            if existing.status in {"refunded", "refunded_pending_revoke"}:
                                                continue
                                            existing.status="paid"; existing.paid_at=existing.paid_at or datetime.utcnow()
                                            await _record_paid(db,existing); await db.commit()
                                        finally:
                                            await _release_payment_side_effect_lock(payment_lock, payment_token)
                                        try:
                                            await fulfill(existing.id,db,existing_user_lock_token=user_token)
                                            await db.refresh(existing)
                                            if existing.fulfillment_status!='completed':continue
                                            method.last_success_at=datetime.utcnow(); method.failure_count=0; method.status="active"; method.last_error=None; method.next_attempt_at=datetime.utcnow()+timedelta(days=20); sub.next_renewal_at=method.next_attempt_at; sub.lifecycle_status="active"; sub.grace_until=None; sub.last_renewal_failure_at=None; await db.commit()
                                        except Exception as exc:
                                            method.last_error=str(exc)[:1000]; await db.commit()
                                    else:
                                        provider_status=await provider.get_payment_status(existing.provider_payment_id)
                                        if provider_status in {"canceled","cancelled","failed","rejected"}:
                                            existing.status="failed"; existing.fulfillment_terminal=True; method.failure_count=(method.failure_count or 0)+1; method.status="past_due"; method.last_error=f"Recurring payment {provider_status}"; method.next_attempt_at=datetime.utcnow()+timedelta(hours=min(72,2**min(method.failure_count,6))); sub.next_renewal_at=method.next_attempt_at; sub.lifecycle_status="grace"; sub.grace_until=(sub.expires_at or datetime.utcnow())+timedelta(hours=72); sub.last_renewal_failure_at=datetime.utcnow()
                                            if method.failure_count>=3: method.status="payment_failed"; method.enabled=False; user.auto_renew_enabled=False
                                            await db.commit()
                                except Exception as exc:
                                    logger.warning("Non-critical operation failed: %s", exc)
                            # Never create a second charge while the newest provider attempt
                            # is unresolved or already succeeded. Failed/cancelled attempts are
                            # the only safe state from which a new idempotency key may be used.
                            if existing.status not in {"failed","canceled","cancelled"}:
                                continue
                            failed_count=sum(1 for item in attempts if item.status in {"failed","canceled","cancelled"})
                            order_id=f"{prefix}-retry-{failed_count+1}"
                        token=decrypt_secret(method.external_token_encrypted)
                        from .subscriptions import ensure_no_pending_purchase,renewal_terms
                        try:await ensure_no_pending_purchase(db,sub.id)
                        except HTTPException:continue
                        terms=await renewal_terms(db,sub,plan)
                        if not terms:
                            method.last_error='Constructor renewal terms unavailable; buy or change this subscription explicitly'
                            await db.commit();continue
                        if terms.get('currency')!=settings.default_currency:
                            method.last_error='Renewal currency differs from configured currency; explicit purchase required'
                            await db.commit();continue
                        renewal_amount=Decimal(terms['amount'])
                        if renewal_amount<=0 or int(terms['days'])<=0:continue
                        # Persist the payment intent BEFORE the external charge. If the
                        # process dies after YooKassa accepts the charge but before the
                        # response/DB commit, the next run can safely retry the SAME
                        # idempotency key instead of issuing a second charge.
                        payment=(await db.execute(select(Payment).where(Payment.order_id==order_id).execution_options(populate_existing=True).with_for_update())).scalar_one_or_none()
                        if not payment:
                            from .partners import renewal_terms as partner_renewal_terms
                            renewal_partner=await partner_renewal_terms(db,sub.id)
                            payment=Payment(**renewal_partner,user_id=user.id,subscription_id=sub.id,plan_id=plan.id,provider="yookassa",provider_payment_id=None,order_id=order_id,amount=renewal_amount,original_amount=renewal_amount,discount_amount=Decimal("0"),duration_days_snapshot=int(terms['days']),traffic_limit_gb_snapshot=terms['traffic_gb'],device_limit_snapshot=terms['devices'],remnawave_profile_id_snapshot=terms['profile_id'],referrer_id_snapshot=user.referred_by_id,referral_terms_snapshot=await referral_snapshot(db,user),currency=settings.default_currency,status="creating",fulfillment_status="pending",paid_at=None)
                            db.add(payment); await db.flush()
                        method.last_attempt_at=datetime.utcnow(); method.next_attempt_at=datetime.utcnow()+timedelta(hours=24); sub.next_renewal_at=method.next_attempt_at; await db.commit()
                        result=await YooKassaProvider().charge_recurring(Decimal(str(payment.amount)),order_id,f"Auto-renew {plan.name}",token)
                        payment=(await db.execute(select(Payment).where(Payment.order_id==order_id).execution_options(populate_existing=True).with_for_update())).scalar_one()
                        payment.provider_payment_id=result["id"]; payment.status="pending"; payment.fulfillment_status="pending"; await db.commit()
                        # Never fulfill until YooKassa confirms succeeded + amount/currency.
                        if await YooKassaProvider().verify_succeeded(result["id"],Decimal(str(payment.amount)),payment.currency,payment.order_id):
                            payment_lock, payment_token = await _acquire_payment_side_effect_lock(payment.id)
                            try:
                                p=(await db.execute(select(Payment).where(Payment.provider_payment_id==result["id"]).execution_options(populate_existing=True).with_for_update())).scalar_one()
                                if p.status in {"refunded", "refunded_pending_revoke"}:
                                    continue
                                p.status="paid"; p.paid_at=p.paid_at or datetime.utcnow()
                                await _record_paid(db,p); await db.commit()
                            finally:
                                await _release_payment_side_effect_lock(payment_lock, payment_token)
                            try:
                                await fulfill(p.id,db,existing_user_lock_token=user_token)
                                await db.refresh(p)
                                if p.fulfillment_status!='completed':continue
                                method.last_success_at=datetime.utcnow(); method.failure_count=0; method.status="active"; method.last_error=None; method.next_attempt_at=datetime.utcnow()+timedelta(days=20); sub.next_renewal_at=method.next_attempt_at; sub.lifecycle_status="active"; sub.grace_until=None; sub.last_renewal_failure_at=None; await db.commit()
                            except Exception as exc:
                                method.last_error=str(exc)[:1000]; await db.commit()
                        else:
                            method.failure_count=(method.failure_count or 0)+1; method.status="past_due"; method.last_error="Recurring payment not confirmed as succeeded"
                            method.next_attempt_at=datetime.utcnow()+timedelta(hours=min(72,2**min(method.failure_count,6))); sub.next_renewal_at=method.next_attempt_at
                            if method.failure_count>=3: method.status="payment_failed"; user.auto_renew_enabled=False; method.enabled=False
                            await db.commit()
                    except Exception as exc:
                        await db.rollback()
                        method=(await db.execute(select(AutoRenewMethod).where(AutoRenewMethod.user_id==user.id))).scalar_one_or_none()
                        if method:
                            method.last_attempt_at=datetime.utcnow(); method.failure_count=(method.failure_count or 0)+1; method.status="past_due"; method.last_error=str(exc)[:1000]
                            method.next_attempt_at=datetime.utcnow()+timedelta(hours=min(72,2**min(method.failure_count,6))); sub.next_renewal_at=method.next_attempt_at
                            if method.failure_count>=3: method.status="payment_failed"; method.enabled=False; user.auto_renew_enabled=False
                            await db.commit()
                    finally:
                        if renew_lock and renew_token:
                            await _release_payment_side_effect_lock(renew_lock,renew_token)
                        if user_lock and user_token:
                            await _release_payment_side_effect_lock(user_lock,user_token)
        except Exception: await asyncio.sleep(60)

async def cleanup_expired_promo_reservations(db,now):
    stale=(await db.execute(select(PromoReservation).outerjoin(Payment,Payment.id==PromoReservation.payment_id).where(
        PromoReservation.status=="reserved",PromoReservation.expires_at<=now,
        or_(Payment.id.is_(None),Payment.status.notin_(["paid","fulfilled"]))).with_for_update(skip_locked=True,of=PromoReservation).limit(200))).scalars().all()
    for reservation in stale:await release_promo_reservation(db,reservation.id)
    return len(stale)


async def reconciliation_scheduler():
    while True:
        try:
            await asyncio.sleep(600)
            async with AsyncSession(engine,expire_on_commit=False) as db:
                now=datetime.utcnow()
                await cleanup_expired_promo_reservations(db,now)
                cutoff=now-timedelta(hours=24)
                rows=(await db.execute(select(Payment).where(Payment.created_at>=cutoff,Payment.status.in_(["pending","creation_unknown"])).order_by(Payment.id).limit(50))).scalars().all()
                providers={"yookassa":YooKassaProvider(),"platega":PlategaProvider(),"rollypay":RollyPayProvider(),"stripe":StripePlatform(),"paypal":PayPalPlatform(),"crypto":CryptoGatewayPlatform()}
                for p in rows:
                    provider=providers.get(p.provider)
                    if not provider or not hasattr(provider,"verify_succeeded"): continue
                    try:
                        if p.status=="creation_unknown" and p.provider=="yookassa" and not p.provider_payment_id:
                            found=await provider.find_by_order_id(p.order_id, p.created_at)
                            if not found or not found.get("id"):
                                continue
                            p.provider_payment_id=str(found["id"]); p.checkout_url=(found.get("confirmation") or {}).get("confirmation_url") or p.checkout_url; p.status="pending"; p.fulfillment_terminal=False
                        if not p.provider_payment_id:
                            continue
                        if await provider.verify_succeeded(p.provider_payment_id,Decimal(str(p.amount)),p.currency,p.order_id):
                            try:
                                result=await _confirm_and_fulfill_payment(p.id,db)
                                if not result.get("ignored"):
                                    _METRICS["payment_fulfillment_total"] += 1
                            except Exception as exc:
                                logger.warning("Non-critical operation failed: %s", exc)
                    except Exception as exc:
                        logger.warning("Non-critical operation failed: %s", exc)
                await db.commit()
        except Exception: await asyncio.sleep(30)

async def subscription_lifecycle_scheduler():
    while True:
        try:
            async with AsyncSession(engine,expire_on_commit=False) as db:
                now=datetime.utcnow()
                ids=(await db.execute(select(Subscription.id).where(Subscription.expires_at.is_not(None),or_(Subscription.expires_at<=now,Subscription.scheduled_cancel_at<=now),Subscription.lifecycle_status.not_in(["expired","cancelled"])).limit(100).with_for_update(skip_locked=True))).scalars().all()
                for sub_id in ids:
                    sub=await db.get(Subscription,sub_id)
                    if not sub: continue
                    if sub.grace_until and sub.grace_until>now and sub.lifecycle_status=="grace": continue
                    user_lock,user_token=await _acquire_user_fulfillment_lock(sub.user_id,ttl=300)
                    try:
                        user=(await db.execute(select(User).where(User.id==sub.user_id).execution_options(populate_existing=True).with_for_update())).scalar_one_or_none()
                        sub=(await db.execute(select(Subscription).where(Subscription.id==sub_id).execution_options(populate_existing=True).with_for_update())).scalar_one_or_none()
                        if not user or not sub or user.deleted_at is not None: continue
                        now=datetime.utcnow()
                        if sub.grace_until and sub.grace_until>now and sub.lifecycle_status=="grace": continue
                        if sub.scheduled_cancel_at and sub.scheduled_cancel_at<=now:
                            if sub.remnawave_uuid:
                                sub.lifecycle_status="revoke_pending"; await db.commit()
                                try:
                                    await RemnawaveClient().disable_user(sub.remnawave_uuid)
                                    sub.lifecycle_status="cancelled"; sub.cancelled_at=now; await audit(db,"subscription.lifecycle.cancelled","system",str(sub.id))
                                except Exception as exc:
                                    await db.rollback(); sub=await db.get(Subscription,sub_id); sub.lifecycle_status="revoke_pending"; await audit(db,"subscription.lifecycle.revoke_pending","system",str(sub.id),{"error":str(exc)[:500]}); await db.commit(); continue
                            else:
                                sub.lifecycle_status="cancelled"; sub.cancelled_at=now; await audit(db,"subscription.lifecycle.cancelled","system",str(sub.id))
                        elif sub.expires_at and sub.expires_at<=now and sub.grace_until and sub.grace_until<=now and sub.remnawave_uuid:
                            sub.lifecycle_status="revoke_pending"; await db.commit()
                            try:
                                await RemnawaveClient().disable_user(sub.remnawave_uuid)
                                sub.lifecycle_status="expired"; await audit(db,"subscription.lifecycle.expired","system",str(sub.id))
                            except Exception as exc:
                                await db.rollback(); sub=await db.get(Subscription,sub_id); sub.lifecycle_status="revoke_pending"; await audit(db,"subscription.lifecycle.revoke_pending","system",str(sub.id),{"error":str(exc)[:500]}); await db.commit(); continue
                        elif sub.expires_at and sub.expires_at<=now:
                            sub.lifecycle_status="expired"; await audit(db,"subscription.lifecycle.expired","system",str(sub.id))
                        await db.commit()
                    finally:
                        await _release_payment_side_effect_lock(user_lock,user_token)
        except Exception as exc:
            logger.warning("Subscription lifecycle scheduler failed: %s", exc)
        await asyncio.sleep(300)

async def notify_user_telegram(chat_id, text: str) -> None:
    if not chat_id or not settings.bot_token:
        return
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
            response = await client.post(
                f"https://api.telegram.org/bot{settings.bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": text[:1000]},
            )
            if response.status_code >= 400:
                logger.warning("Telegram notify failed: HTTP %s", response.status_code)
    except Exception as exc:
        logger.warning("Telegram notify failed: %s", exc)

async def expiry_notification_scheduler():
    # Notifications are sent at most once per day via Redis markers.
    while True:
        try:
            if settings.bot_token and redis_client is not None:
                async with AsyncSession(engine,expire_on_commit=False) as db:
                    until=datetime.utcnow()+timedelta(days=settings.notification_expiry_days)
                    rows=(await db.execute(select(User,Subscription).join(Subscription,Subscription.user_id==User.id).where(User.telegram_id.is_not(None),Subscription.expires_at>datetime.utcnow(),Subscription.expires_at<=until).limit(500))).all()
                    import httpx
                    async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
                        for u,sub in rows:
                            key=f"expiry-notify:{u.id}:sub:{sub.id}:{sub.expires_at.date()}"
                            sending_key=key+":sending"
                            if not await redis_client.set(sending_key,"1",nx=True,ex=300):
                                continue
                            try:
                                resp=await client.post(
                                    f"https://api.telegram.org/bot{settings.bot_token}/sendMessage",
                                    json={"chat_id":u.telegram_id,"text":f"⚠️ Ваша VPN-подписка истекает {sub.expires_at:%d.%m.%Y}. Откройте магазин для продления.\nYour VPN subscription expires on {sub.expires_at:%d.%m.%Y}. Open the shop to renew."},
                                )
                                if resp.status_code >= 400:
                                    raise RuntimeError(f"Telegram notification failed: HTTP {resp.status_code}")
                                await redis_client.set(key,"1",ex=86400*7)
                            except Exception as exc:
                                try: await redis_client.delete(sending_key)
                                except Exception as cleanup_exc:
                                    logger.warning("Failed to clear notification delivery lock: %s", cleanup_exc)
                                logger.warning("Expiry notification failed for user %s: %s",u.id,exc)
            await asyncio.sleep(3600)
        except Exception: await asyncio.sleep(3600)

@app.get("/api/me/subscription")
async def my_subscription(request:Request,db:AsyncSession=Depends(get_db)):
    user=await user_from_token(request,db); sub=(await db.execute(select(Subscription).where(Subscription.user_id==user.id,Subscription.is_primary.is_(True)))).scalar_one_or_none()
    return {"subscription":None if not sub else {"id":sub.id,"plan_id":sub.plan_id,"expires_at":sub.expires_at,"subscription_url":sub.subscription_url,"remnawave_uuid":sub.remnawave_uuid},"auto_renew_enabled":user.auto_renew_enabled}

@app.get("/api/me/billing-center")
async def billing_center(request:Request,db:AsyncSession=Depends(get_db)):
    user=await user_from_token(request,db)
    sub=(await db.execute(select(Subscription).where(Subscription.user_id==user.id,Subscription.is_primary.is_(True)))).scalar_one_or_none()
    payments=(await db.execute(select(Payment).where(Payment.user_id==user.id).order_by(Payment.id.desc()).limit(50))).scalars().all()
    return {"subscription": None if not sub else {"id":sub.id,"plan_id":sub.plan_id,"status":sub.lifecycle_status,"expires_at":sub.expires_at,"grace_until":sub.grace_until,"scheduled_cancel_at":sub.scheduled_cancel_at,"auto_renew":user.auto_renew_enabled},"payments":[{"id":p.id,"order_id":p.order_id,"amount":str(p.amount),"currency":p.currency,"status":p.status,"fulfillment_status":p.fulfillment_status,"created_at":p.created_at,"paid_at":p.paid_at} for p in payments],"imported_payments":await customer_imported_payments(db,user.id)}

@app.get("/api/me/security-center")
async def security_center(request:Request,db:AsyncSession=Depends(get_db)):
    user=await user_from_token(request,db)
    devices=(await db.execute(select(UserDevice).where(UserDevice.user_id==user.id).order_by(UserDevice.last_seen_at.desc().nullslast()))).scalars().all()
    events=(await db.execute(select(AuditLog).where(AuditLog.actor==f"user:{user.id}").order_by(AuditLog.id.desc()).limit(20))).scalars().all()
    sessions=(await db.execute(select(UserSession).where(UserSession.user_id==user.id).order_by(UserSession.id.desc()).limit(20))).scalars().all()
    return {"user_id":user.id,"sessions":[{"id":x.id,"ip":x.ip,"user_agent":x.user_agent,"created_at":x.created_at,"last_seen_at":x.last_seen_at,"expires_at":x.expires_at,"revoked_at":x.revoked_at} for x in sessions],"devices":[{"id":d.id,"name":d.name,"platform":d.platform,"last_ip":d.last_ip,"last_seen_at":d.last_seen_at,"status":d.status,"revoked_at":d.revoked_at} for d in devices],"events":[{"action":e.action,"target":e.target,"created_at":e.created_at} for e in events]}

@app.post("/api/me/subscription/lifecycle")
async def subscription_lifecycle(payload:SubscriptionActionIn,request:Request,db:AsyncSession=Depends(get_db)):
    user=await user_from_token(request,db)
    lock,token=await _acquire_user_fulfillment_lock(user.id,ttl=300)
    try:
        user=(await db.execute(select(User).where(User.id==user.id).with_for_update())).scalar_one()
        sub=(await db.execute(select(Subscription).where(Subscription.user_id==user.id,Subscription.is_primary.is_(True)).with_for_update())).scalar_one_or_none()
        if not sub: raise HTTPException(404,"Subscription not found")
        now=datetime.utcnow()
        if payload.action=="cancel":
            if sub.lifecycle_status in {"expired","cancelled"}: raise HTTPException(409,"Subscription is already inactive")
            sub.scheduled_cancel_at=sub.expires_at or now; sub.lifecycle_status="cancel_scheduled"
            if payload.reason:
                from .models import CancellationFeedback
                db.add(CancellationFeedback(user_id=user.id,subscription_id=sub.id,reason=payload.reason,comment=payload.comment.strip()))
        else:
            if sub.lifecycle_status not in {"cancel_scheduled","grace"}: raise HTTPException(409,"Subscription cannot be resumed from its current state")
            sub.scheduled_cancel_at=None; sub.cancelled_at=None; sub.lifecycle_status="active" if (sub.expires_at and sub.expires_at>now) else "grace"
        await audit(db,f"subscription.{payload.action}",f"user:{user.id}",str(sub.id)); await db.commit()
        return {"ok":True,"status":sub.lifecycle_status,"scheduled_cancel_at":sub.scheduled_cancel_at,"grace_until":sub.grace_until}
    finally:
        await _release_payment_side_effect_lock(lock,token)

YOOKASSA_METHODS={"bank_card","sbp","yoo_money","sberbank","tinkoff_bank"}

def _money(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

@app.post("/api/me/wallet/topup")
async def wallet_topup(payload:dict, request:Request, db:AsyncSession=Depends(get_db)):
    if await maintenance_enabled(db): raise HTTPException(503,"Service is in maintenance mode")
    if not await feature_enabled(db, "payments", True): raise HTTPException(503,"Платежи отключены администратором")
    requested_provider=str(payload.get("provider") or "").lower()
    sandbox_requested=sandbox_checkout_requested(requested_provider)
    if not sandbox_requested and not await production_payments_allowed(db):
        raise HTTPException(503,"Приём платежей временно остановлен администратором")
    user=await user_from_token(request,db)
    from .app_config import require_consent
    await require_consent(db,user)
    idem=request.headers.get("Idempotency-Key")
    if not idem or len(idem)>128: raise HTTPException(400,"Idempotency-Key is required")
    method=str(payload.get("method") or "")
    if method and method not in YOOKASSA_METHODS: raise HTTPException(400,"Unsupported payment method")
    try:
        amount=_money(payload.get("amount"))
    except Exception:
        raise HTTPException(400,"Invalid amount")
    if amount < Decimal("50") or amount > Decimal("100000"):
        raise HTTPException(400,"Amount is outside the allowed top-up range")
    existing=(await db.execute(select(Payment).where(Payment.user_id==user.id,Payment.idempotency_key==idem).order_by(Payment.id.desc()))).scalar_one_or_none()
    if existing:
        if (existing.purpose or "subscription") != "topup":
            raise HTTPException(409,"Idempotency-Key уже использован для другого платежа")
        return {"id":existing.provider_payment_id,"url":existing.checkout_url,"provider":existing.provider,"status":existing.status,"purpose":"topup"}
    await ensure_required_channel(user)
    provider_order=await _payment_provider_order(db,payload.get("provider"))
    if not provider_order: raise HTTPException(503,"Нет доступных платёжных провайдеров")
    candidate=provider_order[0]
    provider={"yookassa":YooKassaProvider(),"platega":PlategaProvider(),"rollypay":RollyPayProvider(),"sandbox":SandboxProvider()}[candidate]
    order_id=f"topup-{user.id}-{hashlib.sha256(idem.encode()).hexdigest()[:24]}"
    row=Payment(user_id=user.id,plan_id=0,provider=candidate,order_id=order_id,amount=amount,original_amount=amount,discount_amount=Decimal("0.00"),currency=settings.default_currency,status="creating",fulfillment_status="pending",idempotency_key=idem,purpose="topup",bonus_days=0)
    db.add(row); await db.commit(); await db.refresh(row)
    try:
        back=_return_url(order_id)
        meta={"order_id":order_id,"user_id":user.id,"email":user.email,"return_url":back,"cancel_url":back}
        if candidate in {"stripe","paypal","crypto"}: result=await provider.create(amount,settings.default_currency,"Wallet top-up",meta)
        elif candidate=="yookassa" and method: result=await provider.create(amount,order_id,"Wallet top-up",_return_url(order_id,settings.mini_app_url),method=method)
        else: result=await provider.create(amount,order_id,"Wallet top-up",_return_url(order_id,settings.mini_app_url))
        if not result.get("id"): raise RuntimeError("Payment provider returned no payment ID")
        row=(await db.execute(select(Payment).where(Payment.id==row.id).with_for_update())).scalar_one()
        row.provider_payment_id=result["id"]; row.checkout_url=result.get("url")
        if candidate=="sandbox" and result.get("status")=="succeeded":
            row.status="paid"; row.paid_at=datetime.utcnow(); await db.commit()
            try:
                await fulfill(row.id, db)
            except Exception:
                logger.exception("Sandbox wallet top-up fulfillment failed for payment %s", row.id)
            fresh=await db.get(Payment, row.id)
            return {"id":result.get("id"),"url":result.get("url"),"provider":candidate,"status": None if fresh is None else fresh.status,"fulfillment_status": None if fresh is None else fresh.fulfillment_status,"purpose":"topup"}
        row.status="pending"
        await db.commit()
        return {"id":result.get("id"),"url":result.get("url"),"provider":candidate,"status":"pending","purpose":"topup"}
    except Exception as exc:
        row=(await db.execute(select(Payment).where(Payment.id==row.id).with_for_update())).scalar_one()
        row.status="creation_unknown"; row.fulfillment_terminal=True; row.fulfillment_error=str(exc)[:1000]
        await db.commit()
        raise HTTPException(503,"Результат создания платежа не определён. Повторное списание заблокировано; операция будет сверена.")

@app.post("/api/me/wallet/spend")
async def wallet_spend(payload:dict, request:Request, db:AsyncSession=Depends(get_db)):
    if await maintenance_enabled(db): raise HTTPException(503,"Service is in maintenance mode")
    user=await user_from_token(request,db)
    from .platform_api import reject_restricted
    reject_restricted(user)
    from .app_config import require_consent
    await require_consent(db,user)
    constructor_requested=payload.get("constructor_id") not in (None, "", 0, "0")
    constructor_quote=None
    quote_error=None
    plan_id=None
    if constructor_requested:
        from .tariff_api import quote_constructor
        try:
            constructor_quote=await quote_constructor(db, payload)
            plan_id=int(constructor_quote["plan_id"])
        except HTTPException as exc:
            quote_error=exc
    else:
        try:
            plan_id=int(payload.get("plan_id"))
        except (TypeError, ValueError):
            raise HTTPException(400,"Invalid plan_id")
    idem=request.headers.get("Idempotency-Key")
    if not idem or len(idem)>128: raise HTTPException(400,"Idempotency-Key is required")
    existing=(await db.execute(select(Payment).where(Payment.user_id==user.id,Payment.idempotency_key==idem))).scalar_one_or_none()
    if existing:
        check_retry(existing,payload)
        from .partners import check_retry as check_partner_retry
        check_partner_retry(existing,payload)
        if existing.provider != "wallet":
            raise HTTPException(409,"Idempotency-Key уже использован для другого платежа")
        if constructor_quote and (existing.plan_id != plan_id or existing.duration_days_snapshot != constructor_quote["days"] or existing.traffic_limit_gb_snapshot != constructor_quote["traffic_gb"] or existing.device_limit_snapshot != constructor_quote["devices"]):
            raise HTTPException(409,"Idempotency-Key уже использован для другой конфигурации тарифа")
        elif plan_id is not None and existing.plan_id != plan_id:
            raise HTTPException(409,"Idempotency-Key уже использован для другого платежа")
        return {"ok":True,"payment_id":existing.id,"status":existing.status,"fulfillment_status":existing.fulfillment_status}
    if quote_error:
        raise quote_error
    if plan_id is None:
        raise HTTPException(400,"Invalid plan_id")
    await ensure_required_channel(user)
    plan=await db.get(Plan,plan_id)
    if not plan or not plan.enabled: raise HTTPException(404,"Not found")
    from .partners import checkout_terms
    partner_terms=await checkout_terms(db,payload.get("reseller_slug"),plan.id,user.id)
    from .tariff_api import linked_constructor_id
    linked=await linked_constructor_id(db, plan.id)
    if linked and (not constructor_quote or int(constructor_quote["constructor_id"]) != int(linked)):
        raise HTTPException(400,"Этот тариф собирается в конструкторе")
    if constructor_quote:
        base_amount=Decimal(str(constructor_quote["amount"]))
        snap_days=int(constructor_quote["days"])
        snap_traffic=constructor_quote["traffic_gb"]
        snap_devices=int(constructor_quote["devices"])
        snap_profile=constructor_quote["profile_id"]
    else:
        base_amount=Decimal(str(plan.price))
        snap_days=plan.duration_days
        snap_traffic=plan.traffic_limit_gb
        snap_devices=plan.device_limit
        snap_profile=plan.remnawave_profile_id
    promo, promo_discount_amount=await promo_discount(db,payload.get("promo_code"),plan.id,base_amount,user.id)
    if promo is None:
        promotion=await active_promotion(db,plan.id)
        discount_amount=discounted_amount(base_amount,promotion.kind,promotion.value) if promotion else Decimal("0.00")
    else:
        promotion=None; discount_amount=promo_discount_amount
    final_amount=_money(base_amount-discount_amount)
    bonus_days=int(Decimal(str(promo.value))) if promo is not None and promo.kind=="days" else (int(Decimal(str(promotion.value))) if promotion is not None and promotion.kind=="days" else 0)
    if final_amount <= 0: raise HTTPException(400,"Amount must be positive")
    lock,token=await _acquire_user_fulfillment_lock(user.id,ttl=900)
    try:
        user=(await db.execute(select(User).where(User.id==user.id).execution_options(populate_existing=True).with_for_update())).scalar_one()
        reject_restricted(user)
        existing=(await db.execute(select(Payment).where(Payment.user_id==user.id,Payment.idempotency_key==idem).with_for_update())).scalar_one_or_none()
        if existing:
            check_retry(existing,payload)
            from .partners import check_retry as check_partner_retry
            check_partner_retry(existing,payload)
            return {"ok":True,"payment_id":existing.id,"status":existing.status,"fulfillment_status":existing.fulfillment_status}
        target=await reserve_target(db,user,plan.id,payload)
        cutoff=datetime.utcnow()-timedelta(seconds=30)
        duplicate_filters=[Payment.user_id==user.id,Payment.subscription_id==target.id,Payment.provider=="wallet",Payment.purpose=="subscription",Payment.plan_id==plan.id,Payment.amount==final_amount,Payment.duration_days_snapshot==snap_days,Payment.traffic_limit_gb_snapshot==snap_traffic,Payment.device_limit_snapshot==snap_devices,Payment.created_at>=cutoff,Payment.status.notin_(["failed","canceled","cancelled","refunded","refunded_pending_revoke"])]
        duplicate_filters.append(Payment.promo_code==promo.code if promo is not None else Payment.promo_code.is_(None))
        duplicate=(await db.execute(select(Payment).where(*duplicate_filters).order_by(Payment.id.desc()))).scalars().first()
        if duplicate:
            raise HTTPException(409,"Повторное списание с баланса заблокировано. Подождите полминуты и повторите покупку.")
        balance=_money(user.wallet_balance or 0)
        if balance < final_amount: raise HTTPException(402,"Недостаточно средств на балансе")
        order_id=f"wallet-{user.id}-{plan.id}-{hashlib.sha256(idem.encode()).hexdigest()[:24]}"
        reservation=await reserve_promo(db,promo,user.id,order_id)
        row=Payment(user_id=user.id,subscription_id=target.id,new_subscription=bool(payload.get("new_subscription",False)),plan_id=plan.id,provider="wallet",order_id=order_id,amount=final_amount,original_amount=base_amount,discount_amount=discount_amount,duration_days_snapshot=snap_days,traffic_limit_gb_snapshot=snap_traffic,device_limit_snapshot=snap_devices,remnawave_profile_id_snapshot=snap_profile,referrer_id_snapshot=user.referred_by_id,referral_terms_snapshot=await referral_snapshot(db,user),promo_code=(promo.code if promo else None),currency=settings.default_currency,status="paid",fulfillment_status="pending",idempotency_key=idem,purpose="subscription",bonus_days=bonus_days,paid_at=datetime.utcnow(),**partner_terms)
        user.wallet_balance=_money(balance-final_amount)
        db.add(row); await db.flush()
        if reservation:reservation.payment_id=row.id
        await record_financial_event(db,operation_key=f"wallet-spend:{row.id}",user_id=user.id,payment_id=row.id,kind="wallet_spend",direction="debit",amount=final_amount,currency=row.currency,metadata={"plan_id":plan.id})
        await db.commit()
        try:
            await fulfill(row.id, db, existing_user_lock_token=token)
        except Exception:
            return {"ok":True,"payment_id":row.id,"fulfillment":"queued","wallet_balance":str(user.wallet_balance)}
        return {"ok":True,"payment_id":row.id,"wallet_balance":str(user.wallet_balance)}
    finally:
        await _release_payment_side_effect_lock(lock,token)

@app.post("/api/me/gifts/purchase")
async def purchase_gift(payload:dict,request:Request,db:AsyncSession=Depends(get_db)):
    from .gift_orders import purchase_gift as purchase
    return await purchase(payload,request,db)

@app.post("/api/me/gifts/redeem")
async def redeem_gift(payload:GiftRedeemIn,request:Request,db:AsyncSession=Depends(get_db)):
    from .gift_orders import redeem_gift as redeem
    return await redeem(payload,request,db)

@app.post("/api/me/referral/apply")
async def apply_referral(payload:dict,request:Request,db:AsyncSession=Depends(get_db)):
    user=await user_from_token(request,db)
    user=(await db.execute(select(User).where(User.id==user.id).with_for_update())).scalar_one()
    from .referrals import bind_referrer
    referrer_id=await bind_referrer(db,user,str(payload.get("code") or ""))
    await db.commit(); return {"ok":True,"referrer_id":referrer_id}


@app.get("/api/me/auto-renew")
async def auto_renew_status(request:Request,db:AsyncSession=Depends(get_db)):
    user=await user_from_token(request,db); method=(await db.execute(select(AutoRenewMethod).where(AutoRenewMethod.user_id==user.id))).scalar_one_or_none()
    last_error="Автопродление не выполнено" if method and method.last_error else None
    sub=await owned_subscription(db,user.id)
    from .subscriptions import renewal_terms
    plan=await db.get(Plan,sub.plan_id) if sub else None
    terms=await renewal_terms(db,sub,plan) if sub and plan else None
    return {"enabled":bool(sub and sub.auto_renew_enabled),"configured":bool(method and method.enabled and method.provider == "yookassa"),"provider":method.provider if method else None,"last_attempt_at":method.last_attempt_at if method else None,"last_success_at":method.last_success_at if method else None,"last_error":last_error,"supported_providers":["yookassa"],
        "renewal_terms":{k:v for k,v in terms.items() if k!='profile_id'} if terms else None}

@app.get("/api/me/connection-qr")
async def connection_qr(request:Request,db:AsyncSession=Depends(get_db)):
    user=await user_from_token(request,db); sub=(await db.execute(select(Subscription).where(Subscription.user_id==user.id,Subscription.is_primary.is_(True)))).scalar_one_or_none()
    url=(sub.subscription_url or "").strip() if sub else ""
    if not url or any(ch in url for ch in "\r\n\x00"): raise HTTPException(404,"Subscription is not available")
    import io, qrcode
    img=qrcode.make(url); buf=io.BytesIO(); img.save(buf,format="PNG")
    return Response(content=buf.getvalue(),media_type="image/png",headers={"Cache-Control":"private, no-store"})

@app.get("/api/me/subscription-file")
async def subscription_file(request:Request,db:AsyncSession=Depends(get_db)):
    user=await user_from_token(request,db); sub=(await db.execute(select(Subscription).where(Subscription.user_id==user.id,Subscription.is_primary.is_(True)))).scalar_one_or_none()
    url=(sub.subscription_url or "").strip() if sub else ""
    if not url or any(ch in url for ch in "\r\n\x00"): raise HTTPException(404,"Subscription is not available")
    return Response(content=(url+"\n").encode(),media_type="text/plain; charset=utf-8",headers={"Cache-Control":"private, no-store","Content-Disposition":'attachment; filename="remnawave-subscription.txt"'})

@app.get("/api/me/connection-info")
async def connection_info(request:Request,db:AsyncSession=Depends(get_db)):
    user=await user_from_token(request,db); sub=(await db.execute(select(Subscription).where(Subscription.user_id==user.id,Subscription.is_primary.is_(True)))).scalar_one_or_none()
    guides={}
    accept=(request.headers.get("accept-language") or "").lower()
    guide_lang="en" if accept.startswith("en") else "ru"
    defaults={
        "ru":{
            "android":"Android: установите v2RayTun / Happ / Streisand, вставьте ссылку подписки и подключитесь.",
            "ios":"iOS: установите Streisand или Happ из App Store, импортируйте ссылку подписки и включите VPN.",
            "tv":"TV: откройте VPN-клиент на телевизоре, добавьте подписку по ссылке или через QR с телефона.",
            "windows":"Windows: установите Hiddify / v2rayN, импортируйте ссылку подписки и запустите соединение.",
            "macos":"macOS: установите Hiddify / Streisand, импортируйте ссылку подписки и подключитесь.",
            "linux":"Linux: используйте Hiddify / Nekoray, импортируйте URI подписки и активируйте профиль.",
        },
        "en":{
            "android":"Android: install v2RayTun, Happ or Streisand, import the subscription link and connect.",
            "ios":"iOS: install Streisand or Happ from the App Store, import the subscription link and turn the VPN on.",
            "tv":"TV: open the VPN client on the television, add the subscription by link or by a phone QR code.",
            "windows":"Windows: install Hiddify or v2rayN, import the subscription link and start the connection.",
            "macos":"macOS: install Hiddify or Streisand, import the subscription link and connect.",
            "linux":"Linux: use Hiddify or Nekoray, import the subscription URI and enable the profile.",
        },
    }[guide_lang]
    for key in ("android","ios","tv","windows","macos","linux"):
        row=(await db.execute(select(AppSetting).where(AppSetting.key==f"guide_{key}"))).scalar_one_or_none()
        guides[key]=row.value if row and row.value else defaults[key]
    raw=(sub.subscription_url or "").strip() if sub else ""
    safe_url=raw if raw and not any(ch in raw for ch in "\r\n\x00") else None
    return Response(content=json.dumps({"subscription_url":safe_url,"expires_at":sub.expires_at.isoformat() if sub and sub.expires_at else None,"platforms":guides},ensure_ascii=False),media_type="application/json",headers={"Cache-Control":"private, no-store"})

@app.put("/api/me/auto-renew")
async def set_auto_renew(payload:dict,request:Request,db:AsyncSession=Depends(get_db)):
    user=await user_from_token(request,db)
    if not isinstance(payload.get('enabled'),bool):raise HTTPException(400,'enabled must be boolean')
    enabled=payload['enabled']
    user=await db.scalar(select(User).where(User.id==user.id).execution_options(populate_existing=True).with_for_update())
    if not user or user.deleted_at:raise HTTPException(409,'Аккаунт недоступен')
    method=(await db.execute(select(AutoRenewMethod).where(AutoRenewMethod.user_id==user.id).execution_options(populate_existing=True).with_for_update())).scalar_one_or_none()
    if enabled and (not method or not method.enabled or method.provider != "yookassa"): raise HTTPException(409,"No supported recurring payment method is configured")
    sub=await owned_subscription(db,user.id,lock=True)
    if not sub:raise HTTPException(404,"Подписка не найдена")
    if enabled:
        from .subscriptions import FAMILY_TARGET,is_family_subscription
        if await is_family_subscription(db,sub.id):raise HTTPException(409,FAMILY_TARGET)
        from .subscriptions import renewal_terms
        plan=await db.get(Plan,sub.plan_id)
        terms=await renewal_terms(db,sub,plan) if plan else None
        if not terms or terms.get('currency')!=settings.default_currency:
            raise HTTPException(409,'Условия продления недоступны. Сначала явно купите или измените эту подписку.')
    sub.auto_renew_enabled=enabled
    if enabled:sub.next_renewal_at=None
    await db.flush()
    user.auto_renew_enabled=bool(await db.scalar(select(func.count()).select_from(Subscription).where(Subscription.user_id==user.id,Subscription.auto_renew_enabled.is_(True))))
    await db.commit();return {"enabled":enabled,"configured":bool(method and method.enabled)}

@app.delete("/api/me/auto-renew/method")
async def remove_auto_renew_method(request:Request,db:AsyncSession=Depends(get_db)):
    user=await user_from_token(request,db)
    user=await db.scalar(select(User).where(User.id==user.id).execution_options(populate_existing=True).with_for_update())
    if not user or user.deleted_at:raise HTTPException(409,'Аккаунт недоступен')
    method=(await db.execute(select(AutoRenewMethod).where(AutoRenewMethod.user_id==user.id).execution_options(populate_existing=True).with_for_update())).scalar_one_or_none()
    if method: await db.delete(method)
    await db.execute(__import__("sqlalchemy").update(Subscription).where(Subscription.user_id==user.id).values(auto_renew_enabled=False))
    user.auto_renew_enabled=False; await db.commit(); return {"ok":True,"enabled":False}

@app.get("/api/me/payments")
async def my_payments(request:Request,db:AsyncSession=Depends(get_db)):
    user=await user_from_token(request,db); rows=(await db.execute(select(Payment).where(Payment.user_id==user.id).order_by(Payment.id.desc()).limit(100))).scalars().all()
    return [{"id":p.id,"provider":p.provider,"amount":float(p.amount),"currency":p.currency,"status":p.status,"fulfillment_status":p.fulfillment_status,"created_at":p.created_at,"paid_at":p.paid_at} for p in rows]

@app.get("/api/me/referral/ledger")
async def my_referral_ledger(request:Request,db:AsyncSession=Depends(get_db)):
    from .models import ReferralLevelReward
    user=await user_from_token(request,db)
    rows=(await db.execute(select(ReferralLedger, ReferralLevelReward.payment_id).outerjoin(
        ReferralLevelReward, ReferralLedger.referral_level_reward_id==ReferralLevelReward.id).where(
        ReferralLedger.user_id==user.id).order_by(ReferralLedger.id.desc()).limit(100))).all()
    return [{"id":x.id,"amount":float(x.amount),"kind":x.kind,"payment_id":x.payment_id or extra_payment_id,"created_at":x.created_at} for x,extra_payment_id in rows]


@app.get("/api/me/referral")
async def my_referral(request:Request,db:AsyncSession=Depends(get_db)):
    from .referral_program import percentages
    from .models import ReferralLevelReward
    user=await user_from_token(request,db)
    count=int(await db.scalar(select(func.count(func.distinct(ReferralReward.referred_user_id))).where(ReferralReward.referrer_id==user.id, ReferralReward.status=="credited")) or 0)
    direct=await db.scalar(select(func.coalesce(func.sum(ReferralReward.amount),0)).where(ReferralReward.referrer_id==user.id, ReferralReward.status=="credited")) or Decimal("0")
    extra=await db.scalar(select(func.coalesce(func.sum(ReferralLevelReward.amount),0)).where(ReferralLevelReward.referrer_id==user.id, ReferralLevelReward.status=="credited")) or Decimal("0")
    rates=[str(x) for x in await percentages(db)]
    return {"code":user.referral_code,"referred_count":count,"reward_total":float(direct+extra),"balance":float(user.referral_balance or 0),"reward_percent":float(rates[0]),"level_percentages":rates}



# ---------- V24-V28 customer/support/security operations: moved to customer_ops_api.py (imported at the end of this file) ----------

# ---------- Уведомления, статус и управление развёртываниями: moved to notifications_status_api.py (imported at the end of this file) ----------

# ---------- Admin Recovery / Reconciliation: moved to recovery_api.py (imported at the end of this file) ----------

# ---------- V32 Operations / Monitoring / Fraud / Privacy: moved to operations_api.py (imported at the end of this file) ----------

# ---------- Admin API: moved to admin_api.py (imported at the end of this file) ----------

# ---------- Staging E2E: moved to staging_e2e_api.py (imported at the end of this file) ----------

# ---------- Backups: moved to backups_api.py (imported at the end of this file) ----------

# ---------- Admin content / branding: moved to content_branding_api.py (imported at the end of this file) ----------

# ---------- Marketing / promotions / broadcasts: moved to marketing_api.py (imported at the end of this file) ----------

# ---------- Enterprise suite V44 / V41 operations: moved to enterprise_api.py (imported at the end of this file) ----------

# ---------- Corgi Payment Platform v20: moved to payment_platform_api.py (imported at the end of this file) ----------



# Sections moved out of this file; imported last so they can read every name above.
from .staging_e2e_api import *  # noqa: E402,F401,F403
from .backups_api import *  # noqa: E402,F401,F403
from .content_branding_api import *  # noqa: E402,F401,F403
from .marketing_api import *  # noqa: E402,F401,F403
from .enterprise_api import *  # noqa: E402,F401,F403
from .customer_ops_api import *  # noqa: E402,F401,F403
from .notifications_status_api import *  # noqa: E402,F401,F403
from .operations_api import *  # noqa: E402,F401,F403
from .admin_api import *  # noqa: E402,F401,F403
from .payment_platform_api import *  # noqa: E402,F401,F403
from .recovery_api import *  # noqa: E402,F401,F403
from .payments_api import *  # noqa: E402,F401,F403
