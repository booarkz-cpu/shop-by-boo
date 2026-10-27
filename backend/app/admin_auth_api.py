"""Admin sign-in (Telegram, password + TOTP) and the admin's own MFA settings.

Names that belong to main are read through ``shop.<name>`` at call time, so tests and
operators that patch ``app.main`` keep affecting this code exactly as before."""
from . import main as shop

# ---------- Admin authentication / MFA ----------
@shop.app.post("/api/admin/auth/telegram")
async def admin_telegram_login(payload:dict,request:shop.Request,response:shop.Response,db:shop.AsyncSession=shop.Depends(shop.get_db)):
    u=shop.telegram_user_from_init_data(payload.get("initData",""))
    admin=(await db.execute(shop.select(shop.AdminUser).where(shop.AdminUser.telegram_id==int(u["id"]),shop.AdminUser.disabled.is_(False)))).scalar_one_or_none()
    if not admin: raise shop.HTTPException(403,"Telegram ID не привязан к администратору")
    if admin.mfa_enabled: raise shop.HTTPException(403,"Для этого администратора требуется вход по email и 2FA")
    jti=shop.secrets.token_urlsafe(32); token=shop.issue_token(admin,False,jti=jti)
    db.add(shop.AdminSession(admin_id=admin.id,jti_hash=shop.hashlib.sha256(jti.encode()).hexdigest(),ip=shop._client_ip(request),user_agent=request.headers.get("user-agent",""),created_at=shop.datetime.utcnow(),last_seen_at=shop.datetime.utcnow(),expires_at=shop.datetime.utcnow()+shop.timedelta(minutes=30)))
    admin.last_login_at=shop.datetime.utcnow(); await shop.audit(db,"admin.telegram_login",str(admin.telegram_id),admin.email); await db.commit()
    response.set_cookie("rw_admin",token,httponly=True,secure=shop.settings.cookie_secure,samesite=shop.settings.cookie_samesite,max_age=1800)
    shop._set_auth_cookies(response,token)
    return {"ok":True,"admin_id":admin.id}

@shop.app.post("/api/admin/auth/login")
async def admin_login(payload:shop.LoginIn, request:shop.Request, response:shop.Response, db:shop.AsyncSession=shop.Depends(shop.get_db)):
    from .mobile_auth import require_mobile_proof
    require_mobile_proof(request)
    # Behind Caddy, request.client is the proxy container. Use the trusted
    # proxy-normalized client IP so one remote address cannot throttle every
    # administrator through the shared reverse-proxy address.
    client_ip=shop._client_ip(request)
    limiter_key=f"login:{client_ip}:{payload.email.lower().strip()}"
    if not await shop._redis_allowed(limiter_key,8,900): raise shop.HTTPException(429,"Too many login attempts. Try again later.", headers={"Retry-After":"900"})
    admin=(await db.execute(shop.select(shop.AdminUser).where(shop.AdminUser.email==payload.email.lower().strip()).with_for_update())).scalar_one_or_none()
    if not admin or admin.disabled or not shop.verify_password(payload.password, admin.password_hash):
        raise shop.HTTPException(401,"Invalid credentials")
    if admin.mfa_enabled:
        if not payload.otp: raise shop.HTTPException(401,"MFA code required or invalid")
        if not shop.verify_totp(admin,payload.otp) and not shop.consume_recovery_code(admin,payload.otp):
            raise shop.HTTPException(401,"MFA code required or invalid")
    admin.last_login_at=shop.datetime.utcnow();
    from .runtime_security import reset_login_attempts
    await reset_login_attempts(shop.redis_client, limiter_key)
    await db.commit()
    jti=shop.secrets.token_urlsafe(32)
    expires=shop.datetime.utcnow()+shop.timedelta(minutes=30)
    db.add(shop.AdminSession(admin_id=admin.id,jti_hash=shop.hashlib.sha256(jti.encode()).hexdigest(),ip=shop._client_ip(request),user_agent=(request.headers.get("user-agent") or "")[:512],expires_at=expires))
    token=shop.issue_token(admin,admin.mfa_enabled,30,jti=jti)
    await db.commit()
    from .mobile_auth import mobile_client_name, session_body
    body={"mfa_enabled":bool(admin.mfa_enabled),"role":admin.role,"email":admin.email}
    if mobile_client_name(request):
        return session_body(request, token, body)
    response.set_cookie("rw_admin",token,httponly=True,secure=shop.settings.cookie_secure,samesite=shop.settings.cookie_samesite,max_age=1800)
    shop._set_auth_cookies(response,token)
    return body

@shop.app.post("/api/admin/auth/mfa/setup")
async def mfa_setup(db:shop.AsyncSession=shop.Depends(shop.get_db), admin=shop.Depends(shop.require_permission("manage_own_mfa"))):
    if admin.mfa_enabled: raise shop.HTTPException(409,"MFA is already enabled")
    secret=shop.random_base32(); admin.totp_secret_encrypted=shop.encrypt_secret(secret); codes=shop.generate_recovery_codes(); shop.set_recovery_codes(admin,codes); await db.commit()
    return {"secret":secret,"otpauth_url":shop.provisioning_uri(secret,admin.email,"Corgi Lusi"),"recovery_codes":codes}

@shop.app.post("/api/admin/auth/mfa/enable")
async def mfa_enable(payload:shop.OtpIn, db:shop.AsyncSession=shop.Depends(shop.get_db), admin=shop.Depends(shop.require_permission("manage_own_mfa"))):
    if admin.mfa_enabled: raise shop.HTTPException(409,"MFA is already enabled")
    if not admin.totp_secret_encrypted or not shop.verify_totp(admin,payload.otp): raise shop.HTTPException(401,"Invalid MFA code")
    admin.mfa_enabled=True; await shop.audit(db,"mfa.enabled",admin.email,admin.email); await db.commit()
    return {"ok":True,"mfa_enabled":True}

class PasswordConfirm(shop.BaseModel):
    password: str = shop.Field(min_length=8, max_length=256)

@shop.app.post("/api/admin/auth/mfa/disable")
async def mfa_disable(payload:PasswordConfirm, db:shop.AsyncSession=shop.Depends(shop.get_db), admin=shop.Depends(shop.require_permission("manage_own_mfa"))):
    if not admin.mfa_enabled: return {"ok":True,"mfa_enabled":False}
    if not shop.verify_password(payload.password, admin.password_hash): raise shop.HTTPException(401,"Invalid password")
    admin.mfa_enabled=False; admin.totp_secret_encrypted=None; admin.recovery_codes_encrypted=None; await shop.audit(db,"mfa.disabled",admin.email,admin.email); await db.commit()
    return {"ok":True,"mfa_enabled":False}

@shop.app.get("/api/admin/auth/mfa/status")
async def mfa_status(admin=shop.Depends(shop.require_permission("read"))): return {"enabled":bool(admin.mfa_enabled)}


__all__ = ['PasswordConfirm', 'admin_login', 'admin_telegram_login', 'mfa_disable', 'mfa_enable', 'mfa_setup', 'mfa_status']
# Imported before main finished (``from app import admin_auth_api`` first)? Then main's star
# import saw a half-loaded module; hand the names over now that they exist.
shop.__dict__.update({_n: globals()[_n] for _n in __all__})
