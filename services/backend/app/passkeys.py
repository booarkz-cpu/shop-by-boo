"""Admin WebAuthn ceremonies with database-backed, single-use challenges."""
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from webauthn import (base64url_to_bytes, generate_authentication_options,
    generate_registration_options, options_to_json, verify_authentication_response,
    verify_registration_response)
from webauthn.helpers import bytes_to_base64url
from webauthn.helpers.structs import (AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor, ResidentKeyRequirement, UserVerificationRequirement)

from .config import settings
from .db import get_db
from .models import AdminSession, AdminUser, FeatureFlag, WebAuthnChallenge, WebAuthnCredential
from .security import (PERMISSIONS, consume_recovery_code, issue_token, require_permission,
    verify_password, verify_totp)

router = APIRouter(prefix='/api/admin/auth/passkeys', tags=['admin-passkeys'])
TTL_SECONDS = 300
COOKIE = 'rw_passkey'


class RegisterIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    password: str = Field(min_length=1, max_length=256)
    otp: str | None = Field(default=None, max_length=20)
    name: str = Field(default='Passkey', min_length=1, max_length=100)


class VerifyIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    ticket: str = Field(min_length=40, max_length=64)
    credential: dict


async def ensure_enabled(db):
    enabled = await db.scalar(select(FeatureFlag.enabled).where(FeatureFlag.key == 'passkeys'))
    if enabled is not True:
        raise HTTPException(503, 'Passkeys are disabled in feature flags')


def rp_config(configured_origin=None):
    origin = settings.webauthn_origin if configured_origin is None else configured_origin
    parsed = urlsplit(origin)
    local = parsed.hostname == 'localhost' and settings.app_env in {'test', 'development'}
    if (not origin or parsed.username or parsed.password or parsed.path or parsed.query or
            parsed.fragment or not parsed.hostname or
            not (parsed.scheme == 'https' or (parsed.scheme == 'http' and local))):
        raise HTTPException(503, 'Configure an exact HTTPS WEBAUTHN_ORIGIN without a path')
    try:
        parsed.port
    except ValueError:
        raise HTTPException(503, 'Invalid WEBAUTHN_ORIGIN port')
    return parsed.hostname, origin


def ceremony_origin(request):
    from .mobile_auth import require_mobile_proof
    require_mobile_proof(request)
    rp_id, origin = rp_config()
    if request.headers.get('origin') != origin:
        raise HTTPException(403, 'WebAuthn origin denied')
    return rp_id, origin


def reject_cross_origin(credential):
    try:
        raw = credential['response']['clientDataJSON']
        if not isinstance(raw, str) or len(raw) > 64000:
            raise ValueError('Client data too large')
        data = json.loads(base64url_to_bytes(raw))
        if data.get('crossOrigin', False) is not False or data.get('topOrigin'):
            raise ValueError('Cross-origin ceremony')
    except Exception:
        raise HTTPException(401, 'Invalid or cross-origin WebAuthn client data')


def auth_state(admin):
    return hashlib.sha256(json.dumps([admin.password_hash, admin.mfa_enabled,
        admin.totp_secret_encrypted, admin.disabled, admin.role, admin.email], separators=(',', ':')).encode()).hexdigest()


async def challenge(db, response, options, purpose, admin=None, metadata=None):
    # Expired challenges carry neither assertions nor private keys. Bound the
    # lifetime and remove them during new ceremonies, without a separate daemon.
    await db.execute(delete(WebAuthnChallenge).where(WebAuthnChallenge.expires_at < datetime.utcnow()))
    ticket, binding = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    db.add(WebAuthnChallenge(ticket_hash=hashlib.sha256(ticket.encode()).hexdigest(),
        binding_hash=hashlib.sha256(binding.encode()).hexdigest(), purpose=purpose,
        admin_id=admin.id if admin else None, challenge=bytes_to_base64url(options.challenge),
        context=metadata or {}, expires_at=datetime.utcnow()+timedelta(seconds=TTL_SECONDS)))
    await db.commit()
    response.headers['Cache-Control'] = 'no-store'
    response.set_cookie(COOKIE, binding, httponly=True, secure=settings.cookie_secure,
        samesite=settings.cookie_samesite, max_age=TTL_SECONDS, path='/api/admin/auth/passkeys')
    return {'ticket': ticket, 'options': json.loads(options_to_json(options))}


async def consume(db, request, payload, purpose, admin_id=None):
    binding = request.cookies.get(COOKIE, '')
    statement = delete(WebAuthnChallenge).where(
        WebAuthnChallenge.ticket_hash == hashlib.sha256(payload.ticket.encode()).hexdigest(),
        WebAuthnChallenge.binding_hash == hashlib.sha256(binding.encode()).hexdigest(),
        WebAuthnChallenge.purpose == purpose, WebAuthnChallenge.expires_at > datetime.utcnow())
    statement = statement.where(WebAuthnChallenge.admin_id == admin_id)
    row = (await db.execute(statement.returning(WebAuthnChallenge))).scalar_one_or_none()
    # Consume before verification: malformed/failed assertions cannot reuse a
    # challenge, even after the request's surrounding transaction rolls back.
    await db.commit()
    if not row or not binding:
        raise HTTPException(401, 'Challenge expired, used, or belongs to another browser')
    return row


@router.post('/registration/options')
async def registration_options(payload: RegisterIn, request: Request, response: Response,
        db: AsyncSession = Depends(get_db), admin=Depends(require_permission('security.passkeys'))):
    rp_id, _ = ceremony_origin(request)
    await ensure_enabled(db)
    admin = (await db.execute(select(AdminUser).where(AdminUser.id == admin.id).with_for_update().execution_options(populate_existing=True))).scalar_one()
    if 'security.passkeys' not in PERMISSIONS.get(admin.role, set()):
        raise HTTPException(403, 'Passkey registration permission required')
    if admin.disabled or not verify_password(payload.password, admin.password_hash):
        raise HTTPException(401, 'Invalid credentials')
    if admin.mfa_enabled and (not payload.otp or not
            (verify_totp(admin, payload.otp) or consume_recovery_code(admin, payload.otp))):
        raise HTTPException(401, 'MFA code required or invalid')
    rows = (await db.execute(select(WebAuthnCredential).where(WebAuthnCredential.admin_id == admin.id))).scalars().all()
    if len(rows) >= 10:
        raise HTTPException(409, 'At most ten passkeys per administrator')
    name = payload.name.strip()
    if not name:
        raise HTTPException(422, 'Passkey name required')
    if not admin.passkey_user_handle:
        admin.passkey_user_handle = bytes_to_base64url(secrets.token_bytes(32))
    options = generate_registration_options(rp_id=rp_id, rp_name='VPN Shop by Corgi',
        user_name=admin.email, user_id=base64url_to_bytes(admin.passkey_user_handle),
        authenticator_selection=AuthenticatorSelectionCriteria(resident_key=ResidentKeyRequirement.REQUIRED,
            require_resident_key=True, user_verification=UserVerificationRequirement.REQUIRED),
        exclude_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(x.credential_id)) for x in rows])
    return await challenge(db, response, options, 'registration', admin, {'name': name, 'auth_state': auth_state(admin)})


@router.post('/registration/verify')
async def registration_verify(payload: VerifyIn, request: Request, response: Response,
        db: AsyncSession = Depends(get_db), admin=Depends(require_permission('security.passkeys'))):
    from .main import audit
    rp_id, origin = ceremony_origin(request)
    await ensure_enabled(db)
    saved = await consume(db, request, payload, 'registration', admin.id)
    admin = (await db.execute(select(AdminUser).where(AdminUser.id == admin.id).with_for_update().execution_options(populate_existing=True))).scalar_one()
    if admin.disabled or saved.context.get('auth_state') != auth_state(admin):
        raise HTTPException(401, 'Administrator credentials changed; begin again')
    reject_cross_origin(payload.credential)
    try:
        verified = verify_registration_response(credential=payload.credential,
            expected_challenge=base64url_to_bytes(saved.challenge), expected_rp_id=rp_id,
            expected_origin=origin, require_user_verification=True)
    except Exception:
        raise HTTPException(401, 'Passkey registration verification failed')
    if (await db.scalar(select(func.count()).select_from(WebAuthnCredential).where(WebAuthnCredential.admin_id == admin.id))) >= 10:
        raise HTTPException(409, 'At most ten passkeys per administrator')
    credential = WebAuthnCredential(admin_id=admin.id, name=saved.context['name'],
        credential_id=bytes_to_base64url(verified.credential_id),
        public_key=bytes_to_base64url(verified.credential_public_key), sign_count=verified.sign_count)
    db.add(credential)
    try:
        await db.flush()
        await audit(db, 'passkey.registered', admin.email, str(credential.id))
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, 'Passkey already registered')
    response.headers['Cache-Control'] = 'no-store'
    response.delete_cookie(COOKIE, path='/api/admin/auth/passkeys')
    return {'ok': True, 'id': credential.id}


@router.post('/login/options')
async def login_options(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    rp_id, _ = ceremony_origin(request)
    await ensure_enabled(db)
    # Discoverable credentials do not require an email probe or reveal accounts.
    options = generate_authentication_options(rp_id=rp_id, user_verification=UserVerificationRequirement.REQUIRED)
    return await challenge(db, response, options, 'authentication')


@router.post('/login/verify')
async def login_verify(payload: VerifyIn, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    from .main import _client_ip, _set_auth_cookies, audit
    rp_id, origin = ceremony_origin(request)
    await ensure_enabled(db)
    saved = await consume(db, request, payload, 'authentication')
    identifier = payload.credential.get('id')
    if not isinstance(identifier, str) or len(identifier) > 1024:
        raise HTTPException(401, 'Invalid passkey')
    existing = (await db.execute(select(WebAuthnCredential).where(WebAuthnCredential.credential_id == identifier))).scalar_one_or_none()
    if not existing:
        raise HTTPException(401, 'Invalid passkey')
    # All registration/assertion ceremonies lock administrator before credential.
    admin = (await db.execute(select(AdminUser).where(AdminUser.id == existing.admin_id).with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
    if not admin or admin.disabled or not admin.passkey_user_handle:
        raise HTTPException(401, 'Invalid passkey')
    credential = (await db.execute(select(WebAuthnCredential).where(WebAuthnCredential.id == existing.id).with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
    if not credential:
        raise HTTPException(401, 'Invalid passkey')
    reject_cross_origin(payload.credential)
    try:
        user_handle = payload.credential['response']['userHandle']
        if not isinstance(user_handle, str) or not hmac.compare_digest(
                base64url_to_bytes(user_handle), base64url_to_bytes(admin.passkey_user_handle)):
            raise ValueError('Wrong user handle')
        verified = verify_authentication_response(credential=payload.credential,
            expected_challenge=base64url_to_bytes(saved.challenge), expected_rp_id=rp_id,
            expected_origin=origin, credential_public_key=base64url_to_bytes(credential.public_key),
            credential_current_sign_count=credential.sign_count, require_user_verification=True)
    except Exception:
        raise HTTPException(401, 'Passkey authentication verification failed')
    credential.sign_count = verified.new_sign_count
    credential.last_used_at = admin.last_login_at = datetime.utcnow()
    jti = secrets.token_urlsafe(32)
    db.add(AdminSession(admin_id=admin.id, jti_hash=hashlib.sha256(jti.encode()).hexdigest(),
        ip=_client_ip(request), user_agent=(request.headers.get('user-agent') or '')[:512],
        expires_at=datetime.utcnow()+timedelta(minutes=30)))
    await audit(db, 'admin.passkey_login', admin.email, str(credential.id))
    token = issue_token(admin, True, 30, jti=jti)
    await db.commit()
    response.headers['Cache-Control'] = 'no-store'
    response.delete_cookie(COOKIE, path='/api/admin/auth/passkeys')
    response.set_cookie('rw_admin', token, httponly=True, secure=settings.cookie_secure,
        samesite=settings.cookie_samesite, max_age=1800)
    _set_auth_cookies(response, token)
    return {'mfa_enabled': bool(admin.mfa_enabled), 'role': admin.role, 'email': admin.email, 'auth_method': 'passkey'}
