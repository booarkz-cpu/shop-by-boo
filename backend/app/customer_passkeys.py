"""Customer WebAuthn: exact cabinet origin, UV and single-use DB challenges."""
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta

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
from .models import CustomerPasskey, CustomerPasskeyChallenge, User, UserSession
from .passkeys import VerifyIn, ensure_enabled, reject_cross_origin, rp_config
from .security import decode_token, verify_password

router = APIRouter(prefix='/api/auth/passkeys', tags=['customer-passkeys'])
COOKIE = 'rw_customer_passkey'
PATH = '/api/auth/passkeys'
TTL = 300


class RegisterIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    password: str | None = Field(default=None, max_length=256)
    name: str = Field(default='Мой ключ', min_length=1, max_length=100)


def origin(request):
    from .mobile_auth import require_mobile_proof
    require_mobile_proof(request)
    rp_id, value = rp_config(settings.customer_webauthn_origin)
    if request.headers.get('origin') != value:
        raise HTTPException(403, 'Customer WebAuthn origin denied')
    return rp_id, value


def auth_state(user):
    return hashlib.sha256(json.dumps([user.email, user.email_password_hash,
        str(user.deleted_at), str(user.restricted_at), user.telegram_id,
        user.yandex_id, user.vk_id], separators=(',', ':')).encode()).hexdigest()


async def owner(db, request):
    from .main import user_from_token
    user = await user_from_token(request, db)
    user = await db.scalar(select(User).where(User.id == user.id).with_for_update()
        .execution_options(populate_existing=True))
    if not user or user.deleted_at or user.restricted_at:
        raise HTTPException(403, 'Account unavailable')
    return user


async def reauthenticate(db, request, user, password):
    if user.email_password_hash:
        if not password or not verify_password(password, user.email_password_hash):
            raise HTTPException(401, 'Current password required')
    else:
        # OAuth/Telegram-only owners must have just signed in. Never assign a
        # password to an OAuth account merely to register a credential.
        auth = request.headers.get('authorization', '')
        token = auth[7:] if auth.startswith('Bearer ') else request.cookies.get('rw_user', '')
        claims = decode_token(token)
        session = await db.scalar(select(UserSession).where(
            UserSession.user_id == user.id,
            UserSession.jti_hash == hashlib.sha256(str(claims.get('jti', '')).encode()).hexdigest(),
            UserSession.revoked_at.is_(None)))
        if not session or session.created_at < datetime.utcnow()-timedelta(seconds=TTL):
            raise HTTPException(401, 'Sign in again before registering or deleting a passkey')


async def challenge(db, response, options, purpose, user=None, context=None):
    await db.execute(delete(CustomerPasskeyChallenge).where(CustomerPasskeyChallenge.expires_at < datetime.utcnow()))
    ticket, binding = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    db.add(CustomerPasskeyChallenge(ticket_hash=hashlib.sha256(ticket.encode()).hexdigest(),
        binding_hash=hashlib.sha256(binding.encode()).hexdigest(), purpose=purpose,
        user_id=user.id if user else None, challenge=bytes_to_base64url(options.challenge),
        context=context or {}, expires_at=datetime.utcnow()+timedelta(seconds=TTL)))
    await db.commit()
    response.headers['Cache-Control'] = 'no-store'
    response.set_cookie(COOKIE, binding, httponly=True, secure=settings.cookie_secure,
        samesite=settings.cookie_samesite, max_age=TTL, path=PATH)
    return {'ticket': ticket, 'options': json.loads(options_to_json(options))}


async def consume(db, request, payload, purpose, user_id=None):
    binding = request.cookies.get(COOKIE, '')
    saved = (await db.execute(delete(CustomerPasskeyChallenge).where(
        CustomerPasskeyChallenge.ticket_hash == hashlib.sha256(payload.ticket.encode()).hexdigest(),
        CustomerPasskeyChallenge.binding_hash == hashlib.sha256(binding.encode()).hexdigest(),
        CustomerPasskeyChallenge.purpose == purpose,
        CustomerPasskeyChallenge.user_id == user_id,
        CustomerPasskeyChallenge.expires_at > datetime.utcnow()
    ).returning(CustomerPasskeyChallenge))).scalar_one_or_none()
    await db.commit()
    if not binding or not saved:
        raise HTTPException(401, 'Challenge expired, used or belongs to another browser')
    return saved


@router.post('/registration/options')
async def registration_options(payload: RegisterIn, request: Request, response: Response,
        db: AsyncSession = Depends(get_db)):
    rp_id, _ = origin(request)
    await ensure_enabled(db)
    user = await owner(db, request)
    await reauthenticate(db, request, user, payload.password)
    rows = (await db.scalars(select(CustomerPasskey).where(CustomerPasskey.user_id == user.id))).all()
    if len(rows) >= 10:
        raise HTTPException(409, 'At most ten passkeys per account')
    name = payload.name.strip()
    if not name:
        raise HTTPException(422, 'Passkey name required')
    if not user.passkey_user_handle:
        user.passkey_user_handle = bytes_to_base64url(secrets.token_bytes(32))
    options = generate_registration_options(rp_id=rp_id, rp_name='VPN Shop by Corgi',
        user_name=user.email or user.username or 'VPN Shop account',
        user_id=base64url_to_bytes(user.passkey_user_handle),
        authenticator_selection=AuthenticatorSelectionCriteria(resident_key=ResidentKeyRequirement.REQUIRED,
            require_resident_key=True, user_verification=UserVerificationRequirement.REQUIRED),
        exclude_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(x.credential_id)) for x in rows])
    return await challenge(db, response, options, 'registration', user,
        {'name': name, 'auth_state': auth_state(user)})


@router.post('/registration/verify')
async def registration_verify(payload: VerifyIn, request: Request, response: Response,
        db: AsyncSession = Depends(get_db)):
    from .main import audit
    rp_id, expected_origin = origin(request)
    await ensure_enabled(db)
    user = await owner(db, request)
    saved = await consume(db, request, payload, 'registration', user.id)
    user = await owner(db, request)
    if saved.context.get('auth_state') != auth_state(user):
        raise HTTPException(401, 'Account changed; begin registration again')
    reject_cross_origin(payload.credential)
    try:
        verified = verify_registration_response(credential=payload.credential,
            expected_challenge=base64url_to_bytes(saved.challenge), expected_rp_id=rp_id,
            expected_origin=expected_origin, require_user_verification=True)
    except Exception:
        raise HTTPException(401, 'Passkey registration verification failed')
    if await db.scalar(select(func.count()).select_from(CustomerPasskey).where(CustomerPasskey.user_id == user.id)) >= 10:
        raise HTTPException(409, 'At most ten passkeys per account')
    row = CustomerPasskey(user_id=user.id, name=saved.context['name'],
        credential_id=bytes_to_base64url(verified.credential_id),
        public_key=bytes_to_base64url(verified.credential_public_key), user_handle=user.passkey_user_handle,
        sign_count=verified.sign_count)
    db.add(row)
    try:
        await db.flush()
        await audit(db, 'customer.passkey_registered', f'user:{user.id}', str(row.id))
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, 'Passkey already registered')
    response.delete_cookie(COOKIE, path=PATH)
    response.headers['Cache-Control'] = 'no-store'
    return {'ok': True, 'id': row.id}


@router.post('/login/options')
async def login_options(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    rp_id, _ = origin(request)
    await ensure_enabled(db)
    options = generate_authentication_options(rp_id=rp_id, user_verification=UserVerificationRequirement.REQUIRED)
    return await challenge(db, response, options, 'authentication')


@router.post('/login/verify')
async def login_verify(payload: VerifyIn, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    from .main import audit, create_user_session, _set_auth_cookies
    rp_id, expected_origin = origin(request)
    await ensure_enabled(db)
    saved = await consume(db, request, payload, 'authentication')
    identifier = payload.credential.get('id')
    if not isinstance(identifier, str) or len(identifier) > 1024:
        raise HTTPException(401, 'Invalid passkey')
    seed = await db.scalar(select(CustomerPasskey).where(CustomerPasskey.credential_id == identifier))
    if not seed:
        raise HTTPException(401, 'Invalid passkey')
    user = await db.scalar(select(User).where(User.id == seed.user_id).with_for_update().execution_options(populate_existing=True))
    row = await db.scalar(select(CustomerPasskey).where(CustomerPasskey.id == seed.id).with_for_update().execution_options(populate_existing=True))
    credential_handle = (row.user_handle if row else None) or (user.passkey_user_handle if user else None)
    if not row or not user or user.deleted_at or user.restricted_at or not credential_handle:
        raise HTTPException(401, 'Invalid passkey')
    reject_cross_origin(payload.credential)
    try:
        handle = payload.credential['response']['userHandle']
        if not isinstance(handle, str) or not hmac.compare_digest(base64url_to_bytes(handle), base64url_to_bytes(credential_handle)):
            raise ValueError('Wrong user handle')
        verified = verify_authentication_response(credential=payload.credential,
            expected_challenge=base64url_to_bytes(saved.challenge), expected_rp_id=rp_id,
            expected_origin=expected_origin, credential_public_key=base64url_to_bytes(row.public_key),
            credential_current_sign_count=row.sign_count, require_user_verification=True)
    except Exception:
        raise HTTPException(401, 'Passkey authentication verification failed')
    row.sign_count = verified.new_sign_count
    row.last_used_at = datetime.utcnow()
    await audit(db, 'customer.passkey_login', f'user:{user.id}', str(row.id))
    token = await create_user_session(db, user, request)
    response.set_cookie('rw_user', token, httponly=True, secure=settings.cookie_secure,
        samesite=settings.cookie_samesite, max_age=3600)
    response.delete_cookie(COOKIE, path=PATH)
    _set_auth_cookies(response, token)
    response.headers['Cache-Control'] = 'no-store'
    return {'ok': True, 'auth_method': 'passkey'}


@router.get('')
async def inventory(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    user = await owner(db, request)
    rows = (await db.scalars(select(CustomerPasskey).where(CustomerPasskey.user_id == user.id).order_by(CustomerPasskey.id))).all()
    response.headers['Cache-Control'] = 'no-store'
    return [{'id': x.id, 'name': x.name, 'created_at': x.created_at, 'last_used_at': x.last_used_at} for x in rows]


@router.post('/{credential_id}/delete')
async def remove(credential_id: int, payload: RegisterIn, request: Request,
        db: AsyncSession = Depends(get_db)):
    from .main import audit
    user = await owner(db, request)
    await reauthenticate(db, request, user, payload.password)
    row = await db.scalar(select(CustomerPasskey).where(CustomerPasskey.id == credential_id, CustomerPasskey.user_id == user.id).with_for_update())
    if not row:
        raise HTTPException(404, 'Passkey not found')
    await db.delete(row)
    await audit(db, 'customer.passkey_deleted', f'user:{user.id}', str(row.id))
    await db.commit()
    return {'ok': True}
