"""Private customer portal and web conversations; notes never leave the operator UI."""
from .client_ip import client_ip
import hashlib, secrets
from datetime import timedelta
from fastapi import Request, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select,or_,and_
from . import main as m
from .models import PortalAccess, Client, Ticket, Message, Attachment, now
from .services import create_ticket, notify
from .sla import utc
from .storage import save_upload, safe_name, checked_path

app=m.app

async def customer(request):
    key=request.session.get('portal')
    async with m.Session() as s:
        access=await s.get(PortalAccess,key) if key else None
        if not access or access.revoked or utc(access.expires_at)<now():raise HTTPException(303,headers={'Location':'/portal'})
        rate_key=f'portal-rate:{access.client_id}'
        if request.method=='POST':
            count=await m.r.incr(rate_key)
            if count==1:await m.r.expire(rate_key,60)
            if count>30:raise HTTPException(429,'Не более 30 действий в минуту')
        return access.client_id

@app.get('/portal')
async def home(request:Request):
    if not request.session.get('portal'):
        return await m.render(request,'portal.html',None,tickets=None)
    uid=await customer(request)
    async with m.Session() as s:
        tickets=(await s.scalars(select(Ticket).where(Ticket.telegram_user_id==uid).order_by(Ticket.id.desc()).limit(100))).all()
    return await m.render(request,'portal.html',None,tickets=tickets)

@app.post('/portal/start')
async def start(request:Request):
    d=await m.form_data(request)
    ip=client_ip(request)
    count=await m.r.incr('portal-start:'+hashlib.sha256(ip.encode()).hexdigest())
    await m.r.expire('portal-start:'+hashlib.sha256(ip.encode()).hexdigest(),3600)
    if count>10:raise HTTPException(429,'Попробуйте позже')
    name=m.text_field(d,'name',120,True)
    token=secrets.token_urlsafe(32);key=hashlib.sha256(token.encode()).hexdigest()
    async with m.Session() as s:
        uid=-secrets.randbelow(2**62)-1
        s.add(Client(telegram_user_id=uid,full_name=name))
        s.add(PortalAccess(token_hash=key,client_id=uid,expires_at=now()+timedelta(days=30)))
        await s.commit()
    request.session['portal']=key
    # Recovery link displayed only to its owner, never emailed automatically.
    return await m.render(request,'portal.html',None,tickets=[],recovery=f'/portal/access/{token}')

@app.get('/portal/access/{token}')
async def access(request:Request,token:str):
    key=hashlib.sha256(token.encode()).hexdigest()
    async with m.Session() as s:
        access=await s.get(PortalAccess,key)
        if not access or access.revoked or utc(access.expires_at)<now():raise HTTPException(404,'Ссылка истекла или отозвана')
    request.session['portal']=key
    return m.redirect('/portal')

@app.post('/client/{uid}/portal-link')
async def issue_link(request:Request,uid:int,op=Depends(m.current_operator)):
    await m.form_data(request)
    token=secrets.token_urlsafe(32)
    async with m.Session() as s:
        if not await s.get(Client,uid):raise HTTPException(404)
        # A team-restricted operator cannot expose another team's history.
        if op.role!='admin':raise HTTPException(403,'Ссылку на полную историю выдаёт администратор')
        s.add(PortalAccess(token_hash=hashlib.sha256(token.encode()).hexdigest(),client_id=uid,expires_at=now()+timedelta(days=7)))
        m.audit(s,op,f'portal link issued for client {uid}');await s.commit()
    return await m.render(request,'portal.html',op,tickets=None,recovery=f'/portal/access/{token}')

@app.post('/portal/tickets')
async def new(request:Request):
    uid=await customer(request);d=await m.form_data(request)
    subject=m.text_field(d,'subject',255,True);body=m.text_field(d,'text',4000,True)
    async with m.Session() as s:
        c=await s.get(Client,uid)
        t=await create_ticket(s,c,subject,channel='web')
        msg=Message(ticket_id=t.id,sender='user',text=body,delivery_state='received')
        s.add(msg);await s.flush();t.last_customer_message_id=msg.id
        await notify(s,t,f'Новое веб-обращение #{t.id}');await s.commit()
    return m.redirect(f'/portal/ticket/{t.id}')

@app.get('/portal/ticket/{tid}')
async def ticket(request:Request,tid:int):
    uid=await customer(request)
    async with m.Session() as s:
        t=await s.get(Ticket,tid)
        if not t or t.telegram_user_id!=uid:raise HTTPException(404)
        messages=(await s.scalars(select(Message).where(Message.ticket_id==tid,Message.sender!='note',or_(and_(Message.sender=='user',Message.delivery_state.in_(['received','queued','sending','failed','sent','legacy'])),and_(Message.sender!='user',Message.delivery_state.in_(['sent','legacy'])))).order_by(Message.id))).all()
        atts=(await s.scalars(select(Attachment).where(Attachment.message_id.in_([msg.id for msg in messages]),Attachment.state=='ready'))).all()
    return await m.render(request,'portal.html',None,t=t,messages=messages,attachments=atts,nonce=secrets.token_urlsafe(24))

@app.post('/portal/ticket/{tid}')
async def reply(request:Request,tid:int):
    uid=await customer(request);d=await m.form_data(request)
    text=m.text_field(d,'text',4000);nonce=m.text_field(d,'nonce',100,True)
    upload=d.get('file');path=None
    if not text and not (upload and upload.filename):raise HTTPException(400,'Введите сообщение')
    try:
        async with m.Session() as s:
            t=await s.scalar(select(Ticket).where(Ticket.id==tid,Ticket.telegram_user_id==uid).with_for_update())
            if not t:raise HTTPException(404)
            if t.shop_merged_into_id:raise HTTPException(409,'Обращение объединено; откройте итоговое обращение')
            key=f'portal:{uid}:{nonce}'
            if await s.scalar(select(Message.id).where(Message.source_key==key)):return m.redirect(f'/portal/ticket/{tid}')
            msg=Message(ticket_id=tid,sender='user',text=text,source_key=key,delivery_state='received');s.add(msg);await s.flush()
            if upload and upload.filename:
                path,size=await save_upload(upload)
                if t.shop_ticket_id:
                    from .shop_bridge import validate_file, MAX_BYTES
                    if size>MAX_BYTES:raise HTTPException(413,'Вложения магазина: до 2 МБ')
                    try:validate_file(upload.filename,path.read_bytes())
                    except ValueError as exc:raise HTTPException(400,str(exc))
                s.add(Attachment(ticket_id=tid,message_id=msg.id,filename=safe_name(upload.filename),path=str(path),size=size,content_type=upload.content_type or 'application/octet-stream'))
            t.status='open';t.closed_at=None;t.updated_at=now();t.waiting_since=now();t.last_customer_message_id=msg.id
            await notify(s,t,f'Новое сообщение в #{tid}');await s.commit()
    except ValueError as exc:
        if path:path.unlink(missing_ok=True)
        raise HTTPException(400,str(exc))
    except BaseException:
        if path:path.unlink(missing_ok=True)
        raise
    return m.redirect(f'/portal/ticket/{tid}')

@app.get('/portal/attachment/{aid}')
async def attachment(request:Request,aid:int):
    uid=await customer(request)
    async with m.Session() as s:
        a=await s.get(Attachment,aid)
        msg=await s.get(Message,a.message_id) if a else None
        t=await s.get(Ticket,a.ticket_id) if a else None
        if not a or not t or not msg or t.telegram_user_id!=uid or msg.sender=='note' or msg.delivery_state not in ('received','sent','legacy') or a.state!='ready':raise HTTPException(404)
    try:path=checked_path(a.path)
    except ValueError:raise HTTPException(404)
    return FileResponse(path,filename=a.filename,media_type='application/octet-stream')

@app.post('/portal/logout')
async def logout(request:Request):
    await m.form_data(request);request.session.pop('portal',None)
    return m.redirect('/portal')

@app.post('/client/{uid}/portal-revoke')
async def revoke(request:Request,uid:int,op=Depends(m.admin)):
    await m.form_data(request)
    async with m.Session() as s:
        rows=(await s.scalars(select(PortalAccess).where(PortalAccess.client_id==uid))).all()
        for row in rows:row.revoked=True
        m.audit(s,op,f'portal access revoked for client {uid}');await s.commit()
    return m.redirect(f'/client/{uid}')
