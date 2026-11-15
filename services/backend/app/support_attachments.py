"""Private ticket attachments; never expose them through the public media mount."""
import base64,binascii,hashlib,re
from fastapi import APIRouter,Depends,HTTPException,Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel,Field
from sqlalchemy import select,func
from sqlalchemy.ext.asyncio import AsyncSession
from .db import get_db
from .models import SupportTicket,SupportAttachment,User
from .security import require_permission
router=APIRouter()
MAX_BYTES=2*1024*1024

class AttachmentIn(BaseModel):
    name:str=Field(min_length=1,max_length=180)
    content_base64:str=Field(min_length=1,max_length=4*((MAX_BYTES+2)//3))

def decode(payload):
    name=re.split(r'[/\\]',payload.name)[-1].strip()
    name=''.join(c for c in name if ord(c)>=32 and c not in '\u202e\u202d\u2066\u2067\u2068\u2069')
    if not name or name in ('.','..'):raise HTTPException(400,'Укажите имя файла')
    try:data=base64.b64decode(payload.content_base64,validate=True)
    except (ValueError,binascii.Error):raise HTTPException(400,'Некорректное содержимое файла')
    if not data or len(data)>MAX_BYTES:raise HTTPException(413,'Файл должен быть не более 2 МБ')
    ext=name.rsplit('.',1)[-1].lower()
    if ext=='png' and data.startswith(b'\x89PNG\r\n\x1a\n'):mime='image/png'
    elif ext in ('jpg','jpeg') and data.startswith(b'\xff\xd8\xff'):mime='image/jpeg'
    elif ext=='pdf' and data.startswith(b'%PDF-'):mime='application/pdf'
    elif ext=='txt':
        try:data.decode('utf-8')
        except UnicodeDecodeError:raise HTTPException(400,'Текстовый файл должен быть UTF-8')
        if b'\x00' in data:raise HTTPException(400,'Некорректный текстовый файл')
        mime='text/plain'
    else:raise HTTPException(400,'Допустимы PNG, JPEG, PDF и TXT')
    return name,data,mime

async def upload(db,ticket,payload,actor,key):
    if ticket.merged_into_id:raise HTTPException(409,"Обращение объединено; откройте итоговое обращение")
    if not key or not 1<=len(key)<=128:raise HTTPException(400,'Idempotency-Key обязателен')
    name,data,mime=decode(payload);digest=hashlib.sha256(data).hexdigest()
    previous=await db.scalar(select(SupportAttachment).where(SupportAttachment.ticket_id==ticket.id,SupportAttachment.actor==actor,SupportAttachment.idempotency_key==key))
    if previous:
        if (previous.name,previous.sha256)!=(name,digest):raise HTTPException(409,'Ключ использован для другого файла')
        return metadata(previous)
    count=await db.scalar(select(func.count()).select_from(SupportAttachment).where(SupportAttachment.ticket_id==ticket.id))
    if count>=20:raise HTTPException(409,'В обращении достигнут лимит 20 вложений')
    item=SupportAttachment(ticket_id=ticket.id,actor=actor,idempotency_key=key,name=name,mime=mime,data=data,size=len(data),sha256=digest)
    db.add(item);await db.flush();await db.commit();return metadata(item)

def metadata(item):return {'id':item.id,'name':item.name,'mime':item.mime,'size':item.size,'sha256':item.sha256}

async def bind(db,ticket,message,ids,actor):
    if len(ids)>3 or len(set(ids))!=len(ids):raise HTTPException(400,'К сообщению можно прикрепить до трёх разных файлов')
    for file_id in ids:
        item=await db.scalar(select(SupportAttachment).where(SupportAttachment.id==file_id,SupportAttachment.ticket_id==ticket.id,SupportAttachment.actor==actor).with_for_update())
        if not item or item.message_id not in (None,message.id):raise HTTPException(404,'Вложение недоступно для этого сообщения')
        item.message_id=message.id

async def customer(request,db):
    from .main import user_from_token
    from .platform_api import reject_restricted
    user=await user_from_token(request,db);reject_restricted(user);return user

@router.post('/api/me/support/tickets/{ticket_id}/attachments')
async def customer_upload(ticket_id:int,payload:AttachmentIn,request:Request,db:AsyncSession=Depends(get_db)):
    user=await customer(request,db)
    user=await db.scalar(select(User).where(User.id==user.id).execution_options(populate_existing=True).with_for_update())
    if not user or user.deleted_at:raise HTTPException(409,"Аккаунт недоступен")
    ticket=await db.scalar(select(SupportTicket).where(SupportTicket.id==ticket_id,SupportTicket.user_id==user.id).with_for_update())
    if not ticket:raise HTTPException(404,'Обращение не найдено')
    return await upload(db,ticket,payload,f'customer:{user.id}',request.headers.get('Idempotency-Key'))

@router.get('/api/me/support/attachments/{attachment_id}')
async def customer_download(attachment_id:int,request:Request,db:AsyncSession=Depends(get_db)):
    user=await customer(request,db)
    item=await db.scalar(select(SupportAttachment).join(SupportTicket,SupportTicket.id==SupportAttachment.ticket_id).where(
        SupportAttachment.id==attachment_id,SupportTicket.user_id==user.id))
    if not item or (item.message_id is None and item.actor!=f'customer:{user.id}'):raise HTTPException(404,'Вложение не найдено')
    return JSONResponse({**metadata(item),'content_base64':base64.b64encode(item.data).decode()},headers={'Cache-Control':'private, no-store'})

@router.post('/api/admin/support/tickets/{ticket_id}/attachments')
async def admin_upload(ticket_id:int,payload:AttachmentIn,request:Request,db:AsyncSession=Depends(get_db),admin=Depends(require_permission('support.write'))):
    ticket=await db.scalar(select(SupportTicket).where(SupportTicket.id==ticket_id).with_for_update())
    if not ticket:raise HTTPException(404,'Обращение не найдено')
    return await upload(db,ticket,payload,f'admin:{admin.email}',request.headers.get('Idempotency-Key'))

@router.get('/api/admin/support/attachments/{attachment_id}')
async def admin_download(attachment_id:int,db:AsyncSession=Depends(get_db),admin=Depends(require_permission('support.read'))):
    item=await db.get(SupportAttachment,attachment_id)
    if not item:raise HTTPException(404,'Вложение не найдено')
    return JSONResponse({**metadata(item),'content_base64':base64.b64encode(item.data).decode()},headers={'Cache-Control':'private, no-store'})

async def remove_draft(db,attachment_id,actor,ticket_user=None):
    item=await db.get(SupportAttachment,attachment_id)
    if not item or item.actor!=actor:raise HTTPException(404,'Вложение не найдено')
    ticket=await db.scalar(select(SupportTicket).where(SupportTicket.id==item.ticket_id).with_for_update())
    if not ticket or (ticket_user is not None and ticket.user_id!=ticket_user):raise HTTPException(404,'Вложение не найдено')
    item=await db.scalar(select(SupportAttachment).where(SupportAttachment.id==attachment_id).execution_options(populate_existing=True).with_for_update())
    if not item:raise HTTPException(404,'Вложение не найдено')
    if item.message_id is not None:raise HTTPException(409,'Файл уже прикреплён к отправленному сообщению')
    await db.delete(item);await db.commit();return {'ok':True}

@router.delete('/api/me/support/attachments/{attachment_id}')
async def customer_remove(attachment_id:int,request:Request,db:AsyncSession=Depends(get_db)):
    user=await customer(request,db)
    return await remove_draft(db,attachment_id,f'customer:{user.id}',user.id)

@router.delete('/api/admin/support/attachments/{attachment_id}')
async def admin_remove(attachment_id:int,db:AsyncSession=Depends(get_db),admin=Depends(require_permission('support.write'))):
    return await remove_draft(db,attachment_id,f'admin:{admin.email}')

async def drafts(db,ticket_id,actor):
    rows=(await db.execute(select(SupportAttachment).where(
        SupportAttachment.ticket_id==ticket_id,SupportAttachment.actor==actor,
        SupportAttachment.message_id.is_(None)).order_by(SupportAttachment.id))).scalars().all()
    return [metadata(item) for item in rows]

@router.get('/api/me/support/tickets/{ticket_id}/attachments/drafts')
async def customer_drafts(ticket_id:int,request:Request,db:AsyncSession=Depends(get_db)):
    user=await customer(request,db)
    ticket=await db.scalar(select(SupportTicket).where(SupportTicket.id==ticket_id,SupportTicket.user_id==user.id))
    if not ticket:raise HTTPException(404,'Обращение не найдено')
    return await drafts(db,ticket_id,f'customer:{user.id}')

@router.get('/api/admin/support/tickets/{ticket_id}/attachments/drafts')
async def admin_drafts(ticket_id:int,db:AsyncSession=Depends(get_db),admin=Depends(require_permission('support.write'))):
    if not await db.get(SupportTicket,ticket_id):raise HTTPException(404,'Обращение не найдено')
    return await drafts(db,ticket_id,f'admin:{admin.email}')
