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
from .payments import YooKassaProvider, PlategaProvider, RollyPayProvider, CryptoBotProvider, PLATEGA_REFUNDED, ROLLYPAY_REFUNDED, SandboxProvider, verify_rollypay, verify_platega_headers, staging_create_payment, staging_read_payment, staging_refund_payment, staging_refund_read
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
from .push_campaigns import router as push_campaigns_router
app.include_router(push_campaigns_router)
from .auto_update_api import router as auto_update_router
app.include_router(auto_update_router)
from .node_health import router as node_health_router
app.include_router(node_health_router)
from .bonus_days import router as bonus_days_router
app.include_router(bonus_days_router)
from .promo_generator import router as promo_generator_router
app.include_router(promo_generator_router)
from .telegram_backup import router as telegram_backup_router
app.include_router(telegram_backup_router)
from .anti_sharing import router as anti_sharing_router
app.include_router(anti_sharing_router)
from .fiscal import router as fiscal_router
app.include_router(fiscal_router)
from .push_style import router as push_style_router
app.include_router(push_style_router)
from .mobile_integrity import router as mobile_integrity_router
app.include_router(mobile_integrity_router)
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
    "/api/mobile/push-style": 60,
    "/api/mobile/integrity/challenge": 30,
    "/api/me/app-login": 10,
    "/api/app/open": 30,
    "/api/app/paid": 30,
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
    inserted = result.first()
    if inserted is not None:
        row.id = inserted[0]  # the caller gets the stored id, as on a replay
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
    from .node_health import node_monitor_scheduler
    _track_task(node_monitor_scheduler())
    from .telegram_backup import telegram_backup_scheduler
    _track_task(telegram_backup_scheduler())
    from .anti_sharing import anti_sharing_scheduler
    _track_task(anti_sharing_scheduler())

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

def _return_url(order_id:str, base:str|None=None, request:Request|None=None)->str:
    """Where the payment page sends the customer back: the cabinet (or Mini App) with ?order=<order id>,
    so the result screen can show whether the payment went through; the Android/iOS app when it paid."""
    from urllib.parse import urlsplit,urlunsplit,parse_qsl,urlencode
    from .mobile_auth import mobile_client_name
    if request is not None and mobile_client_name(request) in ("android-user","ios-user"):
        from .app_login import payment_return_url
        return payment_return_url(order_id)
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

# ---------- Telegram auth: moved to auth_api.py (imported at the end of this file) ----------

# ---------- Promotions, devices, trial, catalog ----------
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

# ---------- Admin authentication / MFA: moved to admin_auth_api.py (imported at the end of this file) ----------

# ---------- Feature flags ----------
async def _feature_flag(db: AsyncSession, key: str):
    return (await db.execute(select(FeatureFlag).where(FeatureFlag.key==key))).scalar_one_or_none()

async def feature_enabled(db: AsyncSession, key: str, default: bool = True) -> bool:
    row = await _feature_flag(db, key)
    return bool(row.enabled) if row is not None else default

# ---------- Payments: moved to payments_api.py (imported at the end of this file) ----------

# ---------- Reliability, sessions, analytics, referrals ----------
# ---------- Background schedulers: retries, refunds, auto-renew, reconciliation, lifecycle, reminders: moved to schedulers.py (imported at the end of this file) ----------

# ---------- Customer account: subscription, wallet, gifts, referral, auto-renew: moved to customer_api.py (imported at the end of this file) ----------

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
from .auth_api import *  # noqa: E402,F401,F403
from .admin_auth_api import *  # noqa: E402,F401,F403
from .schedulers import *  # noqa: E402,F401,F403
from .customer_api import *  # noqa: E402,F401,F403
