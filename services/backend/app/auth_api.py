"""Customer sign-in: Telegram initData, Yandex OAuth, the session token, logout and the cabinet exchange code.

Names that belong to main are read through ``shop.<name>`` at call time, so tests and
operators that patch ``app.main`` keep affecting this code exactly as before."""
from . import main as shop

# ---------- Telegram auth ----------
def telegram_user_from_init_data(init_data:str):
    pairs=dict(shop.urllib.parse.parse_qsl(init_data,keep_blank_values=True))
    received=pairs.pop("hash",None)
    if not received or not shop.settings.bot_token: raise shop.HTTPException(401,"Invalid Telegram initData")
    try:
        auth_date=int(pairs.get("auth_date", "0"))
    except (TypeError,ValueError):
        raise shop.HTTPException(401,"Invalid Telegram auth date")
    if abs(int(shop.datetime.now(shop.timezone.utc).timestamp())-auth_date)>600: raise shop.HTTPException(401,"Expired Telegram initData")
    secret=shop.hmac.new(b"WebAppData",shop.settings.bot_token.encode(),shop.hashlib.sha256).digest()
    check=shop.hmac.new(secret,"\n".join(f"{k}={pairs[k]}" for k in sorted(pairs)).encode(),shop.hashlib.sha256).hexdigest()
    if not shop.hmac.compare_digest(check,received): raise shop.HTTPException(401,"Invalid Telegram initData")
    try:
        user=shop.json.loads(pairs["user"])
        if not isinstance(user,dict) or not user.get("id"):
            raise ValueError("missing Telegram user id")
        int(user["id"])
        return user
    except (KeyError,TypeError,ValueError,shop.json.JSONDecodeError):
        raise shop.HTTPException(401,"Invalid Telegram user data")

@shop.app.post("/api/auth/telegram")
async def telegram_auth(payload:dict, request:shop.Request, response: shop.Response, db:shop.AsyncSession=shop.Depends(shop.get_db)):
    u=shop.telegram_user_from_init_data(payload.get("initData",""))
    telegram_id=int(u["id"])
    await shop._advisory_lock(db, 1000000000 + int(shop.hashlib.sha256(str(telegram_id).encode()).hexdigest()[:8],16) % 900000000)
    from .account_merge import identity_user
    user=await identity_user(db,"telegram",telegram_id)
    if not user:
        from .moderation import registration_check
        await registration_check(db, telegram_id=telegram_id, invite=payload.get("invite"))
        user=shop.User(telegram_id=telegram_id,username=u.get("username"),referral_code=shop.secrets.token_urlsafe(8).upper()); db.add(user)
    elif user.telegram_id == telegram_id:
        user.username=u.get("username")
    await db.commit(); await db.refresh(user)
    token=await shop.create_user_session(db,user,request)
    await shop.audit(db,"auth.user.login",f"user:{user.id}",None,{"method":"telegram","ip":shop._client_ip(request)})
    await db.commit()
    response.set_cookie("rw_user", token, httponly=True, secure=shop.settings.cookie_secure, samesite=shop.settings.cookie_samesite, max_age=3600)
    shop._set_auth_cookies(response, token)
    return {"id":user.id,"telegram_id":user.telegram_id,"username":user.username}

def issue_user_token(user:shop.User, ttl_minutes:int=60, jti:str|None=None):
    now=shop.datetime.now(shop.timezone.utc)
    jti=jti or shop.secrets.token_urlsafe(24)
    return __import__("jwt").encode({"sub":str(user.id),"type":"user","jti":jti,"iat":int(now.timestamp()),"exp":int((now+shop.timedelta(minutes=ttl_minutes)).timestamp())},shop.settings.app_secret,algorithm="HS256")

async def create_user_session(db:shop.AsyncSession,user:shop.User,request:shop.Request,ttl_minutes:int=60):
    if user.deleted_at is not None and not getattr(user,"merged_into_user_id",None):raise shop.HTTPException(401,"User account deleted")
    from .account_merge import canonical_user
    user=await canonical_user(db,user)
    if user.deleted_at is not None:raise shop.HTTPException(401,"User account deleted")
    user=(await db.execute(shop.select(shop.User).where(shop.User.id==user.id).execution_options(populate_existing=True).with_for_update())).scalar_one()
    from .platform_api import reject_restricted
    reject_restricted(user)
    if user.deleted_at is not None:
        raise shop.HTTPException(401,"User account deleted")
    jti=shop.secrets.token_urlsafe(24); now=shop.datetime.utcnow(); expires=now+shop.timedelta(minutes=ttl_minutes)
    db.add(shop.UserSession(user_id=user.id,jti_hash=shop.hashlib.sha256(jti.encode()).hexdigest(),ip=shop._client_ip(request),user_agent=(request.headers.get("user-agent") or "")[:512],expires_at=expires))
    await db.commit()
    return shop.issue_user_token(user,ttl_minutes,jti)

async def user_from_token(request:shop.Request, db:shop.AsyncSession):
    from .mobile_auth import require_mobile_proof
    require_mobile_proof(request)
    auth=request.headers.get("Authorization","")
    token=auth[7:] if auth.startswith("Bearer ") else request.cookies.get("rw_user")
    if not token: raise shop.HTTPException(401,"User authentication required")
    claims=shop.decode_token(token)
    if claims.get("type")!="user": raise shop.HTTPException(401,"Invalid user token")
    try: user_id=int(claims["sub"])
    except (KeyError,TypeError,ValueError): raise shop.HTTPException(401,"Invalid user token")
    subject_user=await db.get(shop.User,user_id)
    if not subject_user: raise shop.HTTPException(401,"User not found")
    jti=claims.get("jti")
    if not jti: raise shop.HTTPException(401,"User session is not registered")
    session=(await db.execute(shop.select(shop.UserSession).where(shop.UserSession.jti_hash==shop.hashlib.sha256(jti.encode()).hexdigest(),shop.UserSession.revoked_at.is_(None)))).scalar_one_or_none()
    now=shop.datetime.utcnow()
    if not session or session.expires_at<now or session.user_id!=subject_user.id: raise shop.HTTPException(401,"User session expired or revoked")
    current_ua=(request.headers.get("user-agent") or "")[:512]
    if session.user_agent and current_ua and session.user_agent!=current_ua:
        session.revoked_at=now; await db.commit(); raise shop.HTTPException(401,"User session device changed")
    session.last_seen_at=now
    await db.commit()
    from .account_merge import canonical_user
    user=await canonical_user(db,subject_user)
    if user.deleted_at is not None: raise shop.HTTPException(401,"User not found")
    from .platform_api import reject_restricted
    reject_restricted(user)
    return user

@shop.app.post("/api/auth/logout")
async def user_logout(request:shop.Request,response: shop.Response,db:shop.AsyncSession=shop.Depends(shop.get_db)):
    token=request.headers.get("Authorization","")
    token=token[7:] if token.startswith("Bearer ") else request.cookies.get("rw_user")
    if token:
        try:
            claims=shop.decode_token(token)
        except shop.HTTPException as exc:
            if exc.status_code != 401: raise
            claims={}
        try:
            jti=claims.get("jti")
            if jti: await db.execute(__import__('sqlalchemy').update(shop.UserSession).where(shop.UserSession.jti_hash==shop.hashlib.sha256(jti.encode()).hexdigest()).values(revoked_at=shop.datetime.utcnow())); await db.commit()
        except Exception as exc:
            await db.rollback()
            raise shop.HTTPException(503, "Could not revoke user session") from exc
    response.delete_cookie("rw_user"); response.delete_cookie("rw_csrf"); return {"ok":True}

@shop.app.post("/api/me/security/revoke-all")
async def revoke_all_user_sessions(request:shop.Request,db:shop.AsyncSession=shop.Depends(shop.get_db)):
    user=await shop.user_from_token(request,db)
    await db.execute(__import__('sqlalchemy').update(shop.UserSession).where(shop.UserSession.user_id==user.id,shop.UserSession.revoked_at.is_(None)).values(revoked_at=shop.datetime.utcnow()))
    await shop.audit(db,"auth.user.sessions.revoked_all",f"user:{user.id}")
    await db.commit(); return {"ok":True}

@shop.app.get("/api/auth/yandex")
async def yandex_login(request:shop.Request, app:int=0):
    if not shop.settings.yandex_client_id or not shop.settings.yandex_redirect_uri: raise shop.HTTPException(503,"Yandex ID is not configured")
    state=shop.secrets.token_urlsafe(24)
    # State is signed so it is stateless and cannot be forged; app=1 returns to the native app.
    signed=__import__("jwt").encode({"state":state,"app":bool(app),"exp":int((shop.datetime.now(shop.timezone.utc)+shop.timedelta(minutes=10)).timestamp())},shop.settings.app_secret,algorithm="HS256")
    params=shop.urllib.parse.urlencode({"response_type":"code","client_id":shop.settings.yandex_client_id,"redirect_uri":shop.settings.yandex_redirect_uri,"state":signed})
    resp=shop.RedirectResponse("https://oauth.yandex.ru/authorize?"+params)
    resp.set_cookie("yandex_oauth_state",signed,httponly=True,secure=True,samesite="lax",max_age=600)
    return resp

@shop.app.get("/api/auth/yandex/callback")
async def yandex_callback(code:str,state:str,request:shop.Request,db:shop.AsyncSession=shop.Depends(shop.get_db)):
    try:
        if not request.cookies.get("yandex_oauth_state") or not shop.hmac.compare_digest(request.cookies["yandex_oauth_state"],state): raise ValueError()
        state_claims=__import__("jwt").decode(state,shop.settings.app_secret,algorithms=["HS256"])
    except Exception: raise shop.HTTPException(400,"Invalid OAuth state")
    if not shop.settings.yandex_client_secret: raise shop.HTTPException(503,"Yandex ID secret is not configured")
    import httpx
    async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
        token_r=await client.post("https://oauth.yandex.ru/token",data={"grant_type":"authorization_code","code":code,"client_id":shop.settings.yandex_client_id,"client_secret":shop.settings.yandex_client_secret})
        if token_r.status_code!=200: raise shop.HTTPException(401,"Yandex authorization failed")
        access=token_r.json().get("access_token")
        me_r=await client.get("https://login.yandex.ru/info",params={"format":"json"},headers={"Authorization":f"OAuth {access}"})
    if me_r.status_code!=200: raise shop.HTTPException(401,"Could not read Yandex profile")
    info=me_r.json(); yid=str(info.get("id"))
    if not yid or yid == "None": raise shop.HTTPException(401,"Yandex profile has no stable identifier")
    yandex_lock_key=int(shop.hashlib.sha256(yid.encode()).hexdigest()[:8],16) % 900000000
    await shop._advisory_lock(db, 1100000000 + yandex_lock_key)
    from .account_merge import identity_user
    user=await identity_user(db,"yandex",yid)
    if not user:
        from .moderation import registration_check
        await registration_check(db, email=info.get("default_email"))
        user=shop.User(yandex_id=yid,username=info.get("login") or info.get("display_name"),referral_code=shop.secrets.token_urlsafe(8).upper()); db.add(user)
    elif user.yandex_id == yid:
        user.username=info.get("login") or info.get("display_name") or user.username
    await db.commit(); await db.refresh(user)
    raw=shop.secrets.token_urlsafe(32); code_hash=shop.hashlib.sha256(raw.encode()).hexdigest()
    to_app=bool(state_claims.get("app"))
    db.add(shop.AuthExchangeCode(code_hash=code_hash,user_id=user.id,expires_at=shop.datetime.utcnow()+shop.timedelta(minutes=5 if to_app else 1)))
    await db.commit()
    from .app_login import deep_link
    resp=shop.RedirectResponse(deep_link(raw) if to_app else shop.settings.mini_app_url.rstrip("/")+"/?code="+shop.urllib.parse.quote(raw))
    resp.delete_cookie("yandex_oauth_state")
    return resp

class ExchangeIn(shop.BaseModel):
    code:str=shop.Field(min_length=20,max_length=128)

@shop.app.post("/api/auth/exchange")
async def auth_exchange(payload:ExchangeIn,request:shop.Request,response: shop.Response,db:shop.AsyncSession=shop.Depends(shop.get_db)):
    h=shop.hashlib.sha256(payload.code.encode()).hexdigest()
    row=(await db.execute(shop.select(shop.AuthExchangeCode).where(shop.AuthExchangeCode.code_hash==h).with_for_update())).scalar_one_or_none()
    if not row or row.used_at or row.expires_at < shop.datetime.utcnow(): raise shop.HTTPException(400,"Invalid or expired authorization code")
    user=await db.get(shop.User,row.user_id)
    if not user: raise shop.HTTPException(404,"User not found")
    from .account_merge import canonical_user
    user=await canonical_user(db,user)
    row.used_at=shop.datetime.utcnow(); await db.commit()
    token=await shop.create_user_session(db,user,request); await shop.audit(db,"auth.user.login",f"user:{user.id}",None,{"method":"yandex","ip":shop._client_ip(request)}); await db.commit(); response.set_cookie("rw_user",token,httponly=True,secure=shop.settings.cookie_secure,samesite=shop.settings.cookie_samesite,max_age=3600); shop._set_auth_cookies(response,token)
    return {"id":user.id,"telegram_id":user.telegram_id,"yandex_id":user.yandex_id,"username":user.username,"referral_code":user.referral_code,"auto_renew_enabled":user.auto_renew_enabled}


__all__ = ['ExchangeIn', 'auth_exchange', 'create_user_session', 'issue_user_token', 'revoke_all_user_sessions', 'telegram_auth', 'telegram_user_from_init_data', 'user_from_token', 'user_logout', 'yandex_callback', 'yandex_login']
# Imported before main finished (``from app import auth_api`` first)? Then main's star
# import saw a half-loaded module; hand the names over now that they exist.
shop.__dict__.update({_n: globals()[_n] for _n in __all__})
