"""Native mobile push for the Corgi Android/iOS apps.

Design:

* A device (``PushDevice``) is one app installation's provider token, bound to the
  user session that registered it. Only a SHA-256 of the token is indexed; the token
  itself is stored AES-GCM encrypted.
* Push mirrors the in-app notification center. The worker fans every new
  ``Notification`` out to ``PushDelivery`` rows and delivers them with retry. The
  notification center stays the source of truth: push is a best-effort signal.
* Signing out (session revoked or expired), an invalid provider token, an account
  merge or deletion all stop delivery: the device is revoked lazily before every send.
* Provider credentials live only in the server environment (``FCM_*``/``APNS_*``).
  Without them the feature reports "not configured" and nothing is sent.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Literal

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import get_db
from .models import Notification, PushDelivery, PushDevice, User, UserSession
from .security import decode_token, decrypt_secret, encrypt_secret, require_permission

logger = logging.getLogger("vpnshop.push")

MAX_ACTIVE_DEVICES = 10
MAX_ATTEMPTS = 5
FANOUT_WINDOW = timedelta(hours=1)
DELIVERY_TTL = timedelta(hours=24)
RETENTION = timedelta(days=30)
TITLE_LIMIT = 80
BODY_LIMIT = 180
# Message text that should not appear on a lock screen.
PRIVATE_KINDS = {"support.reply": "Откройте приложение, чтобы прочитать ответ поддержки."}
ANDROID_CHANNEL = "corgi_default"


def private(response: Response):
    response.headers["Cache-Control"] = "private, no-store"


router = APIRouter(dependencies=[Depends(private)])


# ---------------------------------------------------------------- helpers

def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _clip(value: str, limit: int) -> str:
    value = " ".join((value or "").split())
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def push_content(row: Notification) -> tuple[str, str]:
    title = _clip(row.title, TITLE_LIMIT)
    body = PRIVATE_KINDS.get(row.kind) or _clip(row.body, BODY_LIMIT)
    return title, body


def fcm_configured() -> bool:
    return bool(settings.fcm_project_id.strip() and settings.fcm_service_account_json.strip())


def apns_configured() -> bool:
    return bool(settings.apns_key_id.strip() and settings.apns_team_id.strip() and settings.apns_bundle_id.strip() and settings.apns_private_key.strip())


def provider_ready(provider: str) -> bool:
    return fcm_configured() if provider == "fcm" else apns_configured() if provider == "apns" else False


def _service_account() -> dict:
    raw = settings.fcm_service_account_json.strip()
    if not raw.startswith("{"):
        try:
            raw = base64.b64decode(raw, validate=True).decode()
        except (binascii.Error, UnicodeDecodeError) as exc:
            raise PushConfigError("FCM_SERVICE_ACCOUNT_JSON is neither JSON nor base64 JSON") from exc
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise PushConfigError("FCM_SERVICE_ACCOUNT_JSON is not valid JSON") from exc
    if not data.get("client_email") or not data.get("private_key"):
        raise PushConfigError("FCM service account lacks client_email/private_key")
    return data


def _apns_key() -> str:
    key = settings.apns_private_key.strip().replace("\\n", "\n")
    if "BEGIN PRIVATE KEY" not in key:
        raise PushConfigError("APNS_PRIVATE_KEY must be the PEM content of the .p8 key")
    return key


class PushConfigError(RuntimeError):
    """Provider credentials are missing or malformed (never a reason to drop a device)."""


# ---------------------------------------------------------------- providers

Outcome = Literal["sent", "invalid_token", "retry", "config_error"]


@dataclass
class SendResult:
    outcome: Outcome
    error: str = ""


# Tests replace this factory with one that returns an httpx client on a MockTransport.
def _default_client(http2: bool) -> httpx.AsyncClient:
    return httpx.AsyncClient(http2=http2, timeout=httpx.Timeout(10.0, connect=5.0))


client_factory: Callable[[bool], httpx.AsyncClient] = _default_client

_fcm_token: dict = {"value": "", "expires": 0.0, "key": ""}
_apns_token: dict = {"value": "", "issued": 0.0, "key": ""}


def reset_provider_cache():
    _fcm_token.update(value="", expires=0.0, key="")
    _apns_token.update(value="", issued=0.0, key="")


async def _fcm_access_token(client: httpx.AsyncClient) -> str:
    account = _service_account()
    cache_key = hashlib.sha256(settings.fcm_service_account_json.encode()).hexdigest()
    if _fcm_token["key"] == cache_key and _fcm_token["expires"] > time.time() + 60:
        return _fcm_token["value"]
    token_uri = account.get("token_uri") or "https://oauth2.googleapis.com/token"
    now = int(time.time())
    assertion = jwt.encode(
        {"iss": account["client_email"], "scope": "https://www.googleapis.com/auth/firebase.messaging", "aud": token_uri, "iat": now, "exp": now + 3600},
        account["private_key"],
        algorithm="RS256",
        headers={"kid": account.get("private_key_id")} if account.get("private_key_id") else None,
    )
    response = await client.post(token_uri, data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion})
    if response.status_code != 200:
        raise PushConfigError(f"FCM OAuth rejected service account: HTTP {response.status_code}")
    data = response.json()
    _fcm_token.update(value=data["access_token"], expires=time.time() + int(data.get("expires_in", 3600)), key=cache_key)
    return _fcm_token["value"]


def _fcm_error_code(response: httpx.Response) -> str:
    try:
        error = response.json().get("error") or {}
    except ValueError:
        return ""
    for detail in error.get("details") or []:
        if isinstance(detail, dict) and detail.get("errorCode"):
            return str(detail["errorCode"])
    return str(error.get("status") or "")


async def send_fcm(token: str, title: str, body: str, data: dict[str, str], collapse: str) -> SendResult:
    async with client_factory(False) as client:
        try:
            access = await _fcm_access_token(client)
        except PushConfigError as exc:
            return SendResult("config_error", str(exc))
        message = {
            "message": {
                "token": token,
                "notification": {"title": title, "body": body},
                "data": data,
                "android": {"priority": "HIGH", "collapse_key": collapse, "notification": {"channel_id": ANDROID_CHANNEL, "tag": collapse}},
            }
        }
        response = await client.post(
            f"https://fcm.googleapis.com/v1/projects/{settings.fcm_project_id.strip()}/messages:send",
            json=message,
            headers={"Authorization": f"Bearer {access}"},
        )
    if response.status_code == 200:
        return SendResult("sent")
    code = _fcm_error_code(response)
    if code in {"UNREGISTERED", "INVALID_ARGUMENT", "NOT_FOUND"} or response.status_code == 404:
        return SendResult("invalid_token", f"FCM {code or response.status_code}")
    if response.status_code in {401, 403} or code in {"SENDER_ID_MISMATCH", "THIRD_PARTY_AUTH_ERROR", "PERMISSION_DENIED"}:
        if response.status_code == 401:
            reset_provider_cache()
        return SendResult("config_error", f"FCM {code or response.status_code}")
    return SendResult("retry", f"FCM {code or response.status_code}")


def _apns_bearer() -> str:
    key = _apns_key()
    cache_key = hashlib.sha256(f"{settings.apns_key_id}:{settings.apns_team_id}:{key}".encode()).hexdigest()
    # Apple rejects tokens older than an hour and throttles refreshes faster than 20 minutes.
    if _apns_token["key"] == cache_key and time.time() - _apns_token["issued"] < 45 * 60:
        return _apns_token["value"]
    now = int(time.time())
    value = jwt.encode({"iss": settings.apns_team_id.strip(), "iat": now}, key, algorithm="ES256", headers={"kid": settings.apns_key_id.strip()})
    _apns_token.update(value=value, issued=now, key=cache_key)
    return value


def apns_host() -> str:
    return "api.sandbox.push.apple.com" if settings.apns_environment.strip().lower() == "sandbox" else "api.push.apple.com"


async def send_apns(token: str, title: str, body: str, data: dict[str, str], collapse: str) -> SendResult:
    try:
        bearer = _apns_bearer()
    except (PushConfigError, ValueError, TypeError) as exc:
        return SendResult("config_error", f"APNs key: {exc}"[:200])
    payload = {"aps": {"alert": {"title": title, "body": body}, "sound": "default"}, **data}
    headers = {
        "authorization": f"bearer {bearer}",
        "apns-topic": settings.apns_bundle_id.strip(),
        "apns-push-type": "alert",
        "apns-priority": "10",
        "apns-expiration": str(int(time.time() + DELIVERY_TTL.total_seconds())),
        "apns-collapse-id": collapse,
    }
    async with client_factory(True) as client:
        response = await client.post(f"https://{apns_host()}/3/device/{token}", json=payload, headers=headers)
    if response.status_code == 200:
        return SendResult("sent")
    try:
        reason = str(response.json().get("reason") or "")
    except ValueError:
        reason = ""
    if response.status_code == 410 or reason in {"BadDeviceToken", "Unregistered", "DeviceTokenNotForTopic"}:
        return SendResult("invalid_token", f"APNs {reason or response.status_code}")
    if response.status_code == 403 or reason in {"BadCertificateEnvironment", "BadTopic", "TopicDisallowed"}:
        if reason in {"ExpiredProviderToken", "InvalidProviderToken"}:
            reset_provider_cache()
        return SendResult("config_error", f"APNs {reason or response.status_code}")
    return SendResult("retry", f"APNs {reason or response.status_code}")


async def send(device: PushDevice, row: Notification) -> SendResult:
    title, body = push_content(row)
    data = {"notification_id": str(row.id), "kind": row.kind}
    collapse = f"n{row.id}"
    token = decrypt_secret(device.token_encrypted)
    if device.provider == "fcm":
        return await send_fcm(token, title, body, data, collapse)
    if device.provider == "apns":
        return await send_apns(token, title, body, data, collapse)
    return SendResult("config_error", "unknown provider")


# ---------------------------------------------------------------- worker

def _backoff(attempts: int) -> timedelta:
    return timedelta(seconds=min(3600, 30 * 2 ** max(0, attempts - 1)))


async def session_active(db: AsyncSession, device: PushDevice, now: datetime) -> bool:
    if device.session_id is None:
        return False
    row = await db.get(UserSession, device.session_id)
    return bool(row and row.revoked_at is None and row.expires_at > now and row.user_id == device.user_id)


async def revoke_device(db: AsyncSession, device: PushDevice, reason: str, now: datetime | None = None):
    if device.revoked_at is None:
        device.revoked_at = now or datetime.utcnow()
        device.revoke_reason = reason
    await db.execute(
        update(PushDelivery)
        .where(PushDelivery.device_id == device.id, PushDelivery.status.in_(("queued", "sending")))
        .values(status="skipped", last_error=f"device {reason}")
    )


async def fanout(db: AsyncSession, now: datetime | None = None, limit: int = 200) -> int:
    """Create deliveries for notifications that have not been fanned out yet."""
    now = now or datetime.utcnow()
    rows = (
        await db.execute(
            select(Notification).where(Notification.push_fanout_at.is_(None)).order_by(Notification.id).limit(limit).with_for_update(skip_locked=True)
        )
    ).scalars().all()
    created = 0
    ready = {provider for provider in ("fcm", "apns") if provider_ready(provider)}
    for row in rows:
        row.push_fanout_at = now
        if not ready or row.read_at is not None or row.created_at < now - FANOUT_WINDOW:
            continue
        devices = (
            await db.execute(select(PushDevice).where(PushDevice.user_id == row.user_id, PushDevice.revoked_at.is_(None), PushDevice.provider.in_(ready)))
        ).scalars().all()
        for device in devices:
            db.add(PushDelivery(notification_id=row.id, device_id=device.id, status="queued", next_attempt_at=now, created_at=now))
            created += 1
    await db.commit()
    return created


async def deliver_due(db: AsyncSession, now: datetime | None = None, limit: int = 50) -> dict[str, int]:
    """Claim due deliveries with a short lease, send them, record the outcome."""
    now = now or datetime.utcnow()
    claimed = (
        await db.execute(
            select(PushDelivery)
            .where(PushDelivery.status.in_(("queued", "sending")), PushDelivery.next_attempt_at <= now)
            .order_by(PushDelivery.next_attempt_at, PushDelivery.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    ).scalars().all()
    ids = [row.id for row in claimed]
    for row in claimed:
        row.status = "sending"
        row.attempts += 1
        row.next_attempt_at = now + timedelta(minutes=2)
    await db.commit()
    stats: dict[str, int] = {}
    for delivery_id in ids:
        outcome = await _deliver_one(db, delivery_id, now)
        stats[outcome] = stats.get(outcome, 0) + 1
    return stats


async def _deliver_one(db: AsyncSession, delivery_id: int, now: datetime) -> str:
    delivery = await db.get(PushDelivery, delivery_id, populate_existing=True)
    if not delivery or delivery.status != "sending":
        return "lost"
    device = await db.get(PushDevice, delivery.device_id, populate_existing=True)
    row = await db.get(Notification, delivery.notification_id, populate_existing=True)
    owner = await db.get(User, device.user_id) if device else None

    def finish(status: str, error: str = "") -> str:
        delivery.status = status
        delivery.last_error = error[:255] or None
        return status

    if not device or not row or device.revoked_at is not None:
        outcome = finish("skipped", "device revoked")
    elif owner is None or owner.deleted_at is not None or owner.merged_into_user_id is not None or row.user_id != device.user_id:
        await revoke_device(db, device, "account_closed", now)
        outcome = finish("skipped", "account closed")
    elif not await session_active(db, device, now):
        await revoke_device(db, device, "session_ended", now)
        outcome = finish("skipped", "session ended")
    elif row.read_at is not None:
        outcome = finish("skipped", "already read")
    elif row.created_at < now - DELIVERY_TTL:
        outcome = finish("expired", "older than 24h")
    else:
        try:
            result = await send(device, row)
        except (httpx.HTTPError, asyncio.TimeoutError) as exc:
            result = SendResult("retry", f"{type(exc).__name__}")
        except Exception as exc:  # malformed key material, decrypt failure
            logger.warning("Push delivery %s failed: %s", delivery_id, type(exc).__name__)
            result = SendResult("config_error", type(exc).__name__)
        if result.outcome == "sent":
            delivery.sent_at = now
            device.failures = 0
            outcome = finish("sent")
        elif result.outcome == "invalid_token":
            await revoke_device(db, device, "invalid_token", now)
            outcome = finish("failed", result.error)
        elif delivery.attempts >= MAX_ATTEMPTS:
            device.failures += 1
            outcome = finish("failed", result.error)
        else:
            delivery.status = "queued"
            delivery.last_error = result.error[:255]
            delivery.next_attempt_at = now + _backoff(delivery.attempts)
            outcome = "retry"
    await db.commit()
    return outcome


async def cleanup(db: AsyncSession, now: datetime | None = None):
    cutoff = (now or datetime.utcnow()) - RETENTION
    await db.execute(delete(PushDelivery).where(PushDelivery.created_at < cutoff))
    stale = select(PushDevice.id).where(PushDevice.revoked_at.is_not(None), PushDevice.revoked_at < cutoff)
    await db.execute(delete(PushDelivery).where(PushDelivery.device_id.in_(stale)))
    await db.execute(delete(PushDevice).where(PushDevice.revoked_at.is_not(None), PushDevice.revoked_at < cutoff))
    await db.commit()


async def push_scheduler():
    from .db import engine

    last_cleanup = 0.0
    while True:
        try:
            async with AsyncSession(engine, expire_on_commit=False) as db:
                await fanout(db)
                await deliver_due(db)
                if time.time() - last_cleanup > 3600:
                    await cleanup(db)
                    from .app_growth import cleanup as cleanup_app_events
                    await cleanup_app_events(db)
                    last_cleanup = time.time()
        except Exception as exc:
            logger.warning("Push queue unavailable; retrying: %s", type(exc).__name__)
        await asyncio.sleep(5)


# ---------------------------------------------------------------- customer API

class DeviceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    platform: Literal["android", "ios"]
    token: str = Field(min_length=16, max_length=4096)
    app_version: str | None = Field(default=None, max_length=32)
    locale: str | None = Field(default=None, max_length=8)
    replaces: str | None = Field(default=None, max_length=4096)


class TokenIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=16, max_length=4096)


def _validate_token(platform: str, token: str) -> str:
    token = token.strip()
    if any(ch.isspace() for ch in token):
        raise HTTPException(422, "Push token must not contain whitespace")
    if platform == "ios":
        if len(token) < 64 or len(token) > 200 or any(ch not in "0123456789abcdefABCDEF" for ch in token):
            raise HTTPException(422, "APNs device token must be hexadecimal")
        token = token.lower()
    return token


async def _session(request: Request, db: AsyncSession) -> tuple[User, UserSession]:
    from .main import user_from_token

    user = await user_from_token(request, db)
    auth = request.headers.get("Authorization", "")
    raw = auth[7:] if auth.startswith("Bearer ") else request.cookies.get("rw_user")
    jti = decode_token(raw or "").get("jti") or ""
    session = await db.scalar(select(UserSession).where(UserSession.jti_hash == hashlib.sha256(jti.encode()).hexdigest()))
    if session is None:
        raise HTTPException(401, "User session is not registered")
    return user, session


def _public(device: PushDevice, session_id: int | None) -> dict:
    return {
        "id": device.id,
        "platform": device.platform,
        "app_version": device.app_version,
        "locale": device.locale,
        "created_at": device.created_at.isoformat() if device.created_at else None,
        "last_seen_at": device.last_seen_at.isoformat() if device.last_seen_at else None,
        "current": device.session_id == session_id,
        "provider_ready": provider_ready(device.provider),
    }


@router.post("/api/me/push/devices")
async def register_device(body: DeviceIn, request: Request, db: AsyncSession = Depends(get_db)):
    user, session = await _session(request, db)
    token = _validate_token(body.platform, body.token)
    provider = "fcm" if body.platform == "android" else "apns"
    digest = token_hash(token)
    now = datetime.utcnow()
    if body.replaces:
        old = await db.scalar(select(PushDevice).where(PushDevice.token_hash == token_hash(_validate_token(body.platform, body.replaces)), PushDevice.user_id == user.id))
        if old and old.token_hash != digest:
            await revoke_device(db, old, "replaced", now)
    device = await db.scalar(select(PushDevice).where(PushDevice.token_hash == digest).with_for_update())
    if device is None:
        device = PushDevice(user_id=user.id, platform=body.platform, provider=provider, token_hash=digest, token_encrypted=encrypt_secret(token), created_at=now)
        db.add(device)
    elif device.user_id != user.id:
        # The same installation signed into another account: the previous owner loses it.
        await revoke_device(db, device, "reassigned", now)
        device.user_id = user.id
        device.created_at = now
    device.session_id = session.id
    device.platform = body.platform
    device.provider = provider
    device.app_version = (body.app_version or "").strip() or None
    device.locale = (body.locale or "").strip()[:8] or None
    device.last_seen_at = now
    device.revoked_at = None
    device.revoke_reason = None
    device.failures = 0
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "Push token is being registered concurrently; retry")
    active = (
        await db.execute(
            select(PushDevice).where(PushDevice.user_id == user.id, PushDevice.revoked_at.is_(None)).order_by(PushDevice.last_seen_at.desc(), PushDevice.id.desc())
        )
    ).scalars().all()
    for extra in active[MAX_ACTIVE_DEVICES:]:
        await revoke_device(db, extra, "limit", now)
    await db.commit()
    return {"device": _public(device, session.id), "push_available": provider_ready(provider)}


@router.get("/api/me/push/devices")
async def list_devices(request: Request, db: AsyncSession = Depends(get_db)):
    user, session = await _session(request, db)
    rows = (
        await db.execute(select(PushDevice).where(PushDevice.user_id == user.id, PushDevice.revoked_at.is_(None)).order_by(PushDevice.last_seen_at.desc()))
    ).scalars().all()
    return {
        "items": [_public(row, session.id) for row in rows],
        "providers": {"android": fcm_configured(), "ios": apns_configured()},
    }


@router.post("/api/me/push/devices/unregister")
async def unregister_device(body: TokenIn, request: Request, db: AsyncSession = Depends(get_db)):
    user, _ = await _session(request, db)
    token = body.token.strip()
    candidates = {token_hash(token), token_hash(token.lower())}
    rows = (await db.execute(select(PushDevice).where(PushDevice.token_hash.in_(candidates), PushDevice.user_id == user.id))).scalars().all()
    for row in rows:
        await revoke_device(db, row, "unregistered")
    await db.commit()
    return {"ok": True, "revoked": len(rows)}


@router.delete("/api/me/push/devices/{device_id}")
async def delete_device(device_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    user, _ = await _session(request, db)
    row = await db.scalar(select(PushDevice).where(PushDevice.id == device_id, PushDevice.user_id == user.id))
    if row is None:
        raise HTTPException(404, "Push device not found")
    await revoke_device(db, row, "removed")
    await db.commit()
    return {"ok": True}


@router.post("/api/me/push/test")
async def test_push(request: Request, db: AsyncSession = Depends(get_db)):
    user, session = await _session(request, db)
    device = await db.scalar(select(PushDevice).where(PushDevice.user_id == user.id, PushDevice.session_id == session.id, PushDevice.revoked_at.is_(None)))
    if device is None:
        raise HTTPException(409, "Push is not enabled on this device")
    if not provider_ready(device.provider):
        raise HTTPException(503, "Push provider is not configured on the server")
    minute = datetime.utcnow().strftime("%Y%m%d%H%M")
    key = f"push-test:{session.id}:{minute}"
    existing = await db.scalar(select(Notification).where(Notification.user_id == user.id, Notification.dedupe_key == key))
    if existing:
        raise HTTPException(429, "Test push was already sent this minute")
    db.add(Notification(user_id=user.id, channel="in_app", kind="push.test", title="Проверка уведомлений", body="Push-уведомления на этом устройстве работают.", status="sent", sent_at=datetime.utcnow(), dedupe_key=key))
    await db.commit()
    return {"queued": True}


# ---------------------------------------------------------------- admin

@router.get("/api/admin/push/status")
async def admin_push_status(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("ops.diagnostics"))):
    now = datetime.utcnow()
    devices = dict(
        (await db.execute(select(PushDevice.platform, func.count(PushDevice.id)).where(PushDevice.revoked_at.is_(None)).group_by(PushDevice.platform))).all()
    )
    revoked = dict(
        (
            await db.execute(
                select(PushDevice.revoke_reason, func.count(PushDevice.id)).where(PushDevice.revoked_at.is_not(None), PushDevice.revoked_at >= now - timedelta(days=7)).group_by(PushDevice.revoke_reason)
            )
        ).all()
    )
    deliveries = dict(
        (await db.execute(select(PushDelivery.status, func.count(PushDelivery.id)).where(PushDelivery.created_at >= now - timedelta(hours=24)).group_by(PushDelivery.status))).all()
    )
    errors = (
        await db.execute(
            select(PushDelivery.last_error, func.count(PushDelivery.id))
            .where(PushDelivery.created_at >= now - timedelta(hours=24), PushDelivery.status.in_(("failed", "queued")), PushDelivery.last_error.is_not(None))
            .group_by(PushDelivery.last_error)
            .order_by(func.count(PushDelivery.id).desc())
            .limit(5)
        )
    ).all()
    return {
        "providers": {
            "fcm": {"configured": fcm_configured(), "project_id": settings.fcm_project_id.strip() or None},
            "apns": {"configured": apns_configured(), "environment": "sandbox" if settings.apns_environment.strip().lower() == "sandbox" else "production", "bundle_id": settings.apns_bundle_id.strip() or None},
        },
        "devices": {"android": int(devices.get("android", 0)), "ios": int(devices.get("ios", 0))},
        "revoked_7d": {str(key or "unknown"): int(value) for key, value in revoked.items()},
        "deliveries_24h": {str(key): int(value) for key, value in deliveries.items()},
        "top_errors_24h": [{"error": str(error), "count": int(count)} for error, count in errors],
    }
