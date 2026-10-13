"""Account recovery: no plaintext tokens in storage, no OAuth account takeover."""
import asyncio
import hashlib
import hmac
import secrets
import smtplib
import ssl
from datetime import datetime,timedelta
from email.message import EmailMessage
from urllib.parse import urlsplit,quote
from fastapi import APIRouter,Depends,HTTPException,Request,Response
from pydantic import BaseModel,Field
from sqlalchemy import select,update,delete
from sqlalchemy.ext.asyncio import AsyncSession
from .config import settings
from .db import get_db
from .models import User,UserSession,AuthExchangeCode,AccountAction,AccountMail,AccountMergeAlias
from .security import hash_password,verify_password,encrypt_secret,decrypt_secret
router=APIRouter()

class EmailIn(BaseModel):
    email:str=Field(min_length=5,max_length=320)
class TokenIn(BaseModel):
    token:str=Field(min_length=40,max_length=128)
class ResetIn(TokenIn):
    password:str=Field(min_length=8,max_length=128)
class PasswordIn(BaseModel):
    current_password:str=Field(min_length=8,max_length=128)
    password:str=Field(min_length=8,max_length=128)

def fingerprint(value):
    return hmac.new(settings.app_secret.encode(),(value or '').encode(),hashlib.sha256).hexdigest()

def mail_origin():
    origin=(settings.cabinet_url or settings.mini_app_url).rstrip('/')
    parsed=urlsplit(origin)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise HTTPException(503,'Настройте HTTPS адрес кабинета для писем')
    return origin

def require_mail():
    if not settings.smtp_host or not (settings.smtp_from or settings.smtp_user):
        raise HTTPException(503,'Email недоступен: настройте SMTP')
    mail_origin()

async def owner_lock(db,user_id):
    user=await db.scalar(select(User).where(User.id==user_id).execution_options(populate_existing=True).with_for_update())
    if not user or user.deleted_at:raise HTTPException(400,'Ссылка недействительна или устарела')
    return user

async def enqueue(db,user,purpose,email=None,password_hash=None):
    now=datetime.utcnow()
    action_email=email or user.email
    credential_hash=password_hash if email else user.email_password_hash
    recent=await db.scalar(select(AccountAction.id).where(AccountAction.user_id==user.id,AccountAction.purpose==purpose,
        AccountAction.created_at>now-timedelta(minutes=2)).limit(1))
    if recent:return
    # The owner's lock serializes issuance with reset/deletion and the mail worker.
    await db.execute(update(AccountAction).where(AccountAction.user_id==user.id,AccountAction.purpose==purpose,
        AccountAction.used_at.is_(None)).values(used_at=now))
    raw=secrets.token_urlsafe(48)
    row=AccountAction(user_id=user.id,token_hash=hashlib.sha256(raw.encode()).hexdigest(),purpose=purpose,email=action_email,
        password_fingerprint=fingerprint(credential_hash) if purpose=='password_reset' else None,
        expires_at=now+timedelta(minutes=30 if purpose=='password_reset' else 1440))
    db.add(row);await db.flush()
    db.add(AccountMail(action_id=row.id,token_encrypted=encrypt_secret(raw)))

@router.post('/api/auth/password/reset/request')
async def request_reset(payload:EmailIn,request:Request,response:Response,db:AsyncSession=Depends(get_db)):
    require_mail()
    from .cabinet_api import _normalize_email
    email=_normalize_email(payload.email)
    from .account_merge import email_identity
    user,password_hash,_=await email_identity(db,email)
    if user and not user.deleted_at and password_hash:
        user=await owner_lock(db,user.id)
        await enqueue(db,user,'password_reset',email=email,password_hash=password_hash);await db.commit()
    response.headers['Cache-Control']='private, no-store'
    return {'ok':True,'message':'Если для этой почты есть пароль, письмо отправлено. Проверьте также папку «Спам».'}

async def consume(db,raw,purpose):
    digest=hashlib.sha256(raw.encode()).hexdigest()
    seed=await db.scalar(select(AccountAction).where(AccountAction.token_hash==digest,AccountAction.purpose==purpose))
    if not seed:raise HTTPException(400,'Ссылка недействительна или устарела')
    user=await owner_lock(db,seed.user_id)
    action=await db.scalar(select(AccountAction).where(AccountAction.id==seed.id).execution_options(populate_existing=True).with_for_update())
    if not action or action.used_at or action.expires_at<=datetime.utcnow():
        raise HTTPException(400,'Ссылка недействительна или устарела')
    alias=None if action.email==user.email else await db.scalar(select(AccountMergeAlias).where(
        AccountMergeAlias.target_user_id==user.id,AccountMergeAlias.email==action.email))
    if action.email!=user.email and not alias:
        raise HTTPException(400,'Ссылка недействительна или устарела')
    credential_hash=user.email_password_hash if action.email==user.email else alias.email_password_hash
    if purpose=='password_reset' and (not credential_hash or not hmac.compare_digest(action.password_fingerprint or '',fingerprint(credential_hash))):
        raise HTTPException(400,'Ссылка недействительна или устарела')
    action.used_at=datetime.utcnow()
    return user,action

async def revoke_access(db,user):
    now=datetime.utcnow()
    await db.execute(update(UserSession).where(UserSession.user_id==user.id,UserSession.revoked_at.is_(None)).values(revoked_at=now))
    await db.execute(update(AuthExchangeCode).where(AuthExchangeCode.user_id==user.id,AuthExchangeCode.used_at.is_(None)).values(used_at=now))
    await db.execute(update(AccountAction).where(AccountAction.user_id==user.id,AccountAction.purpose=='password_reset',AccountAction.used_at.is_(None)).values(used_at=now))

def clear_cookies(response):
    response.delete_cookie('rw_user');response.delete_cookie('rw_csrf');response.headers['Cache-Control']='private, no-store'

@router.post('/api/auth/password/reset/confirm')
async def confirm_reset(payload:ResetIn,response:Response,db:AsyncSession=Depends(get_db)):
    from .main import audit
    user,action=await consume(db,payload.token,'password_reset')
    user.email_password_hash=hash_password(payload.password)
    from .account_merge import update_account_password
    await update_account_password(db,user.id,user.email_password_hash)
    await revoke_access(db,user)
    await audit(db,'auth.user.password_reset',f'user:{user.id}');await db.commit()
    clear_cookies(response)
    return {'ok':True,'message':'Пароль изменён. Войдите снова на всех устройствах.'}

@router.get('/api/me/email')
async def email_status(request:Request,response:Response,db:AsyncSession=Depends(get_db)):
    from .main import user_from_token
    user=await user_from_token(request,db)
    response.headers['Cache-Control']='private, no-store'
    return {'email':user.email,'verified':bool(user.email_verified_at),'password_enabled':bool(user.email_password_hash),
        'mail_enabled':bool(settings.smtp_host and (settings.smtp_from or settings.smtp_user))}

@router.post('/api/me/email/verification/request')
async def request_verification(request:Request,db:AsyncSession=Depends(get_db)):
    require_mail()
    from .main import user_from_token
    user=await user_from_token(request,db);user=await owner_lock(db,user.id)
    if not user.email:raise HTTPException(409,'У аккаунта нет email')
    if user.email_verified_at:return {'ok':True,'message':'Почта уже подтверждена'}
    await enqueue(db,user,'email_verification');await db.commit()
    return {'ok':True,'message':'Письмо с подтверждением отправлено'}

@router.post('/api/auth/email/verification/confirm')
async def confirm_verification(payload:TokenIn,response:Response,db:AsyncSession=Depends(get_db)):
    from .main import audit
    user,action=await consume(db,payload.token,'email_verification')
    user.email_verified_at=datetime.utcnow()
    await audit(db,'auth.user.email_verified',f'user:{user.id}');await db.commit()
    response.headers['Cache-Control']='private, no-store'
    return {'ok':True,'message':'Email подтверждён'}

@router.post('/api/me/password/change')
async def change_password(payload:PasswordIn,request:Request,response:Response,db:AsyncSession=Depends(get_db)):
    from .main import user_from_token,audit
    user=await user_from_token(request,db);user=await owner_lock(db,user.id)
    if not user.email_password_hash or not verify_password(payload.current_password,user.email_password_hash):
        raise HTTPException(400,'Текущий пароль неверен')
    user.email_password_hash=hash_password(payload.password)
    from .account_merge import update_account_password
    await update_account_password(db,user.id,user.email_password_hash)
    await revoke_access(db,user);await audit(db,'auth.user.password_changed',f'user:{user.id}');await db.commit()
    clear_cookies(response)
    return {'ok':True,'message':'Пароль изменён. Войдите снова.'}

def send_mail(email,purpose,raw):
    route='password-reset' if purpose=='password_reset' else 'verify-email'
    link=mail_origin()+'#'+route+'?token='+quote(raw,safe='')
    msg=EmailMessage();msg['From']=settings.smtp_from or settings.smtp_user;msg['To']=email
    msg['Subject']='Восстановление пароля' if purpose=='password_reset' else 'Подтверждение email'
    msg.set_content(('Изменить пароль' if purpose=='password_reset' else 'Подтвердить почту')+':\n'+link+
        '\n\nЕсли вы не запрашивали это действие, проигнорируйте письмо. Ссылка действует '+('30 минут.' if purpose=='password_reset' else '24 часа.'))
    context=ssl.create_default_context()
    cls=smtplib.SMTP_SSL if settings.smtp_port==465 else smtplib.SMTP
    kwargs={'context':context} if settings.smtp_port==465 else {}
    with cls(settings.smtp_host,settings.smtp_port,timeout=15,**kwargs) as smtp:
        if settings.smtp_port!=465:smtp.starttls(context=context)
        if settings.smtp_user:smtp.login(settings.smtp_user,settings.smtp_password)
        smtp.send_message(msg)

async def deliver_one(db,mail_id):
    seed=await db.get(AccountMail,mail_id)
    action=await db.get(AccountAction,seed.action_id) if seed else None
    if not action:return
    user=await db.scalar(select(User).where(User.id==action.user_id).execution_options(populate_existing=True).with_for_update())
    mail=await db.scalar(select(AccountMail).where(AccountMail.id==mail_id).execution_options(populate_existing=True).with_for_update(skip_locked=True))
    if not mail or mail.status!='queued' or mail.next_retry_at>datetime.utcnow():return
    await db.refresh(action)
    alias=None if not user or user.email==action.email else await db.scalar(select(AccountMergeAlias).where(
        AccountMergeAlias.target_user_id==user.id,AccountMergeAlias.email==action.email))
    if not user or user.deleted_at or (user.email!=action.email and not alias) or action.used_at or action.expires_at<=datetime.utcnow():
        mail.status='cancelled';mail.token_encrypted='';await db.commit();return
    mail.attempts+=1
    try:
        await asyncio.to_thread(send_mail,action.email,action.purpose,decrypt_secret(mail.token_encrypted))
        mail.status='sent';mail.token_encrypted='';mail.error=None
    except Exception as exc:
        mail.error=type(exc).__name__[:40]
        mail.status='failed' if mail.attempts>=8 else 'queued'
        mail.next_retry_at=datetime.utcnow()+timedelta(seconds=min(3600,30*2**mail.attempts))
        if mail.status=='failed':mail.token_encrypted=''
    await db.commit()

async def mail_scheduler():
    from .db import engine
    while True:
        try:
            async with AsyncSession(engine,expire_on_commit=False) as db:
                ids=(await db.scalars(select(AccountMail.id).where(AccountMail.status=='queued',AccountMail.next_retry_at<=datetime.utcnow()).limit(20))).all()
                for mail_id in ids:await deliver_one(db,mail_id)
                await db.execute(delete(AccountAction).where(AccountAction.expires_at<datetime.utcnow()-timedelta(days=7)))
                await db.commit()
        except Exception:
            from .main import logger
            logger.warning('Account mail queue unavailable; retrying')
        await asyncio.sleep(10)
