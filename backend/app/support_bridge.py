"""Scoped machine API for the operator component; shop remains the source of truth."""
import base64
import hmac
import re
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession
from .config import settings
from .db import get_db
from .models import User, SupportTicket, SupportMessage, SupportAttachment, SupportImportLink, Notification
from .support_threads import append_message, read_thread, preserve_previous_reply
from .support_attachments import AttachmentIn, upload, metadata

def private_response(response:Response):response.headers['Cache-Control']='private, no-store'

router=APIRouter(prefix='/api/internal/support-bridge',dependencies=[Depends(private_response)])

def identity(request:Request):
    token=settings.support_bridge_token
    if len(token)<32:raise HTTPException(503,'Интеграция поддержки отключена')
    supplied=request.headers.get('Authorization','')
    if not hmac.compare_digest(supplied.encode(),('Bearer '+token).encode()):raise HTTPException(401,'Недействительный ключ интеграции')
    instance=request.headers.get('X-Support-Instance','')
    if not re.fullmatch(r'[A-Za-z0-9_-]{8,40}',instance):raise HTTPException(400,'Укажите стабильный идентификатор интеграции')
    return instance

async def ticket_for_write(db,ticket_id,importing=False):
    seed=await db.get(SupportTicket,ticket_id)
    if not seed:raise HTTPException(404,'Обращение не найдено')
    owner=await db.scalar(select(User).where(User.id==seed.user_id).execution_options(populate_existing=True).with_for_update())
    if not owner or owner.deleted_at:raise HTTPException(409,'Аккаунт недоступен')
    if not importing and await db.scalar(select(SupportImportLink.source_key).where(SupportImportLink.ticket_id==ticket_id,SupportImportLink.completed.is_(False))):raise HTTPException(409,'Перенос истории ещё не завершён')
    return await db.scalar(select(SupportTicket).where(SupportTicket.id==ticket_id).execution_options(populate_existing=True).with_for_update())

def ticket_output(t,u):
    return {'id':t.id,'user_id':t.user_id,'telegram_id':u.telegram_id if u and not u.deleted_at else None,
        'username':u.username if u and not u.deleted_at else '', 'subject':t.subject if u and not u.deleted_at else 'Удалённый аккаунт',
        'status':t.status,'created_at':t.created_at,'merged_into_id':t.merged_into_id,'history_version':str(t.topology_version),'deleted':not u or bool(u.deleted_at)}

def visible_tickets():
    return select(SupportTicket,User).outerjoin(User,User.id==SupportTicket.user_id).where(
        SupportTicket.id.not_in(select(SupportImportLink.ticket_id).where(SupportImportLink.completed.is_(False))))

@router.get('/tickets')
async def tickets(after:int=Query(0,ge=0),db:AsyncSession=Depends(get_db),instance=Depends(identity)):
    rows=(await db.execute(visible_tickets().where(SupportTicket.id>after).order_by(SupportTicket.id).limit(51))).all()
    visible=rows[:50]
    return {'items':[ticket_output(t,u) for t,u in visible],
        'next_cursor':visible[-1][0].id if len(rows)>50 else None}

@router.get('/tickets/recent')
async def recent(db:AsyncSession=Depends(get_db),instance=Depends(identity)):
    rows=(await db.execute(visible_tickets().order_by(SupportTicket.updated_at.desc(),SupportTicket.id.desc()).limit(50))).all()
    return {'items':[ticket_output(t,u) for t,u in rows]}

@router.get('/tickets/{ticket_id}/messages')
async def messages(ticket_id:int,after:int=Query(0,ge=0),db:AsyncSession=Depends(get_db),instance=Depends(identity)):
    t=await db.scalar(select(SupportTicket).where(SupportTicket.id==ticket_id).with_for_update())
    if not t:raise HTTPException(404,'Обращение не найдено')
    owner=await db.get(User,t.user_id)
    if not owner or owner.deleted_at:return {'deleted':True,'messages':[],'next_cursor':None}
    await preserve_previous_reply(db,t)
    thread=await read_thread(db,t,after)
    keys=dict((await db.execute(select(SupportMessage.id,func.coalesce(SupportMessage.delivery_key,SupportMessage.idempotency_key)).where(SupportMessage.ticket_id==t.id,SupportMessage.id.in_([x['id'] for x in thread['messages']])))).all())
    for item in thread['messages']:item['source_key']=keys.get(item['id'])
    # Keep the ticket lock until the complete page and its epoch are captured.
    # A concurrent merge/split must not mix old metadata with new membership.
    result={**thread,'deleted':False,'history_version':str(t.topology_version)}
    await db.commit()
    return result

@router.get('/attachments/{attachment_id}')
async def attachment(attachment_id:int,db:AsyncSession=Depends(get_db),instance=Depends(identity)):
    item=await db.scalar(select(SupportAttachment).join(SupportTicket,SupportTicket.id==SupportAttachment.ticket_id)
        .join(User,User.id==SupportTicket.user_id).where(SupportAttachment.id==attachment_id,SupportAttachment.message_id.is_not(None),User.deleted_at.is_(None)))
    if not item:raise HTTPException(404,'Вложение не найдено')
    from fastapi.responses import JSONResponse
    return JSONResponse({**metadata(item),'content_base64':base64.b64encode(item.data).decode()},headers={'Cache-Control':'private, no-store'})

@router.post('/tickets/{ticket_id}/attachments')
async def add_attachment(ticket_id:int,payload:AttachmentIn,request:Request,db:AsyncSession=Depends(get_db),instance=Depends(identity)):
    t=await ticket_for_write(db,ticket_id)
    return await upload(db,t,payload,'support-pro:'+instance,request.headers.get('Idempotency-Key'))

class ReplyIn(BaseModel):
    body:str=Field(min_length=1,max_length=5000)
    attachment_ids:list[int]=Field(default_factory=list,max_length=3)

@router.post('/tickets/{ticket_id}/reply')
async def reply(ticket_id:int,payload:ReplyIn,request:Request,db:AsyncSession=Depends(get_db),instance=Depends(identity)):
    if not request.headers.get('Idempotency-Key','').startswith('sp:'+instance+':reply:'):raise HTTPException(400,'Некорректный ключ ответа')
    t=await ticket_for_write(db,ticket_id)
    message,created=await append_message(db,t,'admin',payload.body,request.headers['Idempotency-Key'],payload.attachment_ids,'support-pro:'+instance)
    if created:
        from .main import audit
        db.add(Notification(user_id=t.user_id,channel='in_app',kind='support.reply',title=f'Ответ на обращение #{t.id}',body=message.body,status='sent',dedupe_key=f'support-message:{message.id}',sent_at=datetime.utcnow()))
        await audit(db,'support.ticket.replied','support-pro:'+instance,str(t.id))
    await db.commit();return {'id':message.id,'created':created,'status':t.status}

class StatusIn(BaseModel):
    status:str=Field(pattern='^(open|resolved)$')
    expected_message_id:int=Field(ge=0)

@router.post('/tickets/{ticket_id}/status')
async def status(ticket_id:int,payload:StatusIn,db:AsyncSession=Depends(get_db),instance=Depends(identity)):
    t=await ticket_for_write(db,ticket_id)
    if t.merged_into_id is not None:raise HTTPException(409,'Обращение объединено; откройте целевое обращение')
    latest=await db.scalar(select(func.coalesce(func.max(SupportMessage.id),0)).where(SupportMessage.ticket_id==ticket_id))
    if latest!=payload.expected_message_id:raise HTTPException(409,'Переписка изменилась; обновите обращение')
    if t.status!=payload.status:
        from .main import audit
        t.status=payload.status;t.updated_at=datetime.utcnow();await audit(db,'support.ticket.status','support-pro:'+instance,str(t.id),{'status':t.status})
    await db.commit();return {'status':t.status}

class ImportIn(BaseModel):
    telegram_id:int=Field(gt=0)
    subject:str=Field(min_length=1,max_length=255)
    created_at:datetime
    dry_run:bool=True

@router.post('/imports/{source_id}')
async def import_ticket(source_id:int,payload:ImportIn,db:AsyncSession=Depends(get_db),instance=Depends(identity)):
    if source_id<=0 or not payload.subject.strip():raise HTTPException(400,'Некорректное обращение')
    if db.bind.dialect.name=='postgresql':await db.execute(text('SELECT pg_advisory_xact_lock(1400000006)'))
    from .account_merge import identity_user
    owner=await identity_user(db,"telegram",payload.telegram_id)
    if owner:
        owner=await db.scalar(select(User).where(User.id==owner.id,User.deleted_at.is_(None)).with_for_update())
    if not owner:raise HTTPException(409,'Клиент Telegram не найден в магазине; автоматическое создание аккаунта запрещено')
    key=f'{instance}:{source_id}'
    previous=await db.get(SupportImportLink,key)
    if previous:
        t=await db.get(SupportTicket,previous.ticket_id)
        if t.user_id!=owner.id:raise HTTPException(409,'Импорт уже связан с другим аккаунтом')
        return {'id':t.id,'created':False,'dry_run':payload.dry_run,'completed':previous.completed}
    if payload.dry_run:return {'id':None,'created':False,'dry_run':True,'user_id':owner.id}
    created=payload.created_at.replace(tzinfo=timezone.utc) if payload.created_at.tzinfo is None else payload.created_at.astimezone(timezone.utc)
    t=SupportTicket(user_id=owner.id,subject=payload.subject.strip(),message='Перенесённая история обращения',created_at=created.replace(tzinfo=None))
    db.add(t);await db.flush();db.add(SupportImportLink(source_key=key,ticket_id=t.id))
    from .main import audit
    await audit(db,'support.import.created','support-pro:'+instance,str(t.id));await db.commit()
    return {'id':t.id,'created':True,'dry_run':False}

class ImportMessageIn(ReplyIn):
    role:str=Field(pattern='^(customer|admin)$')
    created_at:datetime

@router.post('/imports/{source_id}/messages')
async def import_message(source_id:int,payload:ImportMessageIn,request:Request,db:AsyncSession=Depends(get_db),instance=Depends(identity)):
    link=await db.get(SupportImportLink,f'{instance}:{source_id}')
    if not link:raise HTTPException(404,'Сначала перенесите обращение')
    key=request.headers.get('Idempotency-Key','')
    if not key.startswith('sp:'+instance+':import:'):raise HTTPException(400,'Некорректный ключ импорта')
    t=await ticket_for_write(db,link.ticket_id,importing=True)
    link=await db.scalar(select(SupportImportLink).where(SupportImportLink.source_key==link.source_key).execution_options(populate_existing=True).with_for_update())
    if link.completed:raise HTTPException(409,'Перенос уже завершён; используйте обычную переписку')
    message,created=await append_message(db,t,payload.role,payload.body,key,payload.attachment_ids,'support-pro:'+instance,importing=True)
    if created:
        date=payload.created_at.replace(tzinfo=timezone.utc) if payload.created_at.tzinfo is None else payload.created_at.astimezone(timezone.utc)
        message.created_at=date.replace(tzinfo=None)
    await db.commit();return {'id':message.id,'created':created}

class CustomerIn(ReplyIn):
    telegram_id:int|None=Field(default=None,gt=0)
    user_id:int|None=Field(default=None,gt=0)

@router.post('/tickets/{ticket_id}/customer-message')
async def customer_message(ticket_id:int,payload:CustomerIn,request:Request,db:AsyncSession=Depends(get_db),instance=Depends(identity)):
    key=request.headers.get('Idempotency-Key','')
    if not key.startswith('sp:'+instance+':customer:'):raise HTTPException(400,'Некорректный ключ сообщения')
    t=await ticket_for_write(db,ticket_id)
    owner=await db.get(User,t.user_id)
    if (payload.telegram_id is None)==(payload.user_id is None):raise HTTPException(400,'Укажите одну идентичность клиента')
    if (payload.telegram_id is not None and owner.telegram_id!=payload.telegram_id) or (payload.user_id is not None and owner.id!=payload.user_id):raise HTTPException(409,'Привязка клиента изменилась')
    message,created=await append_message(db,t,'customer',payload.body,key,payload.attachment_ids,'support-pro:'+instance)
    await db.commit();return {'id':message.id,'created':created,'status':t.status}

@router.post('/imports/{source_id}/attachments')
async def import_attachment(source_id:int,payload:AttachmentIn,request:Request,db:AsyncSession=Depends(get_db),instance=Depends(identity)):
    link=await db.get(SupportImportLink,f'{instance}:{source_id}')
    if not link or link.completed:raise HTTPException(409,'Перенос не открыт')
    t=await ticket_for_write(db,link.ticket_id,importing=True)
    link=await db.scalar(select(SupportImportLink).where(SupportImportLink.source_key==link.source_key).execution_options(populate_existing=True).with_for_update())
    if link.completed:raise HTTPException(409,'Перенос завершён')
    return await upload(db,t,payload,'support-pro:'+instance,request.headers.get('Idempotency-Key'))

@router.post('/imports/{source_id}/complete')
async def complete_import(source_id:int,payload:StatusIn,db:AsyncSession=Depends(get_db),instance=Depends(identity)):
    link=await db.get(SupportImportLink,f'{instance}:{source_id}')
    if not link:raise HTTPException(404,'Перенос не найден')
    t=await ticket_for_write(db,link.ticket_id,importing=True)
    link=await db.scalar(select(SupportImportLink).where(SupportImportLink.source_key==link.source_key).execution_options(populate_existing=True).with_for_update())
    if link.completed:return {'id':t.id,'completed':True}
    latest=await db.scalar(select(func.coalesce(func.max(SupportMessage.id),0)).where(SupportMessage.ticket_id==t.id))
    if latest!=payload.expected_message_id:raise HTTPException(409,'История изменилась')
    link.completed=True;t.status=payload.status
    from .main import audit
    await audit(db,'support.import.completed','support-pro:'+instance,str(t.id));await db.commit();return {'id':t.id,'completed':True}
