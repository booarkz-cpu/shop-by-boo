"""Operator workflows, calendars, queue recovery and incident coordination."""
import json, secrets, hashlib
from datetime import datetime, timezone, timedelta
from difflib import SequenceMatcher
from urllib.parse import urlencode, parse_qsl
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select, func
from . import main as m
from .models import *
from .sla import validate, utc
from .services import close_ticket, STATUSES

app=m.app

async def page(request,op,title,**data):
    return await m.render(request,'operations.html',op,title=title,**data)

@app.get('/operations')
async def operations(request:Request,op=Depends(m.current_operator)):
    async with m.Session() as s:
        shop_sync=await s.get(ShopSyncState,1) if op.role=='admin' else None
        views=(await s.scalars(select(SavedView).where(SavedView.operator_id==op.id))).all()
        sessions=(await s.scalars(select(LoginSession).where(LoginSession.operator_id==op.id,LoginSession.revoked.is_(False)))).all()
        jobs=(await s.scalars(select(WorkItem).order_by(WorkItem.id.desc()).limit(100))).all() if op.role=='admin' else []
        teams=(await s.scalars(select(Team))).all() if op.role=='admin' else []
        holidays=(await s.scalars(select(Holiday).order_by(Holiday.day))).all()
        operators=(await s.scalars(select(Operator))).all() if op.role=='admin' else []
    return await page(request,op,'Рабочие инструменты',views=views,sessions=sessions,jobs=jobs,teams=teams,holidays=holidays,operators=operators,shop_sync=shop_sync)

@app.post('/views')
async def save_view(request:Request,op=Depends(m.current_operator)):
    d=await m.form_data(request)
    allowed={'q','status','priority','assigned_to','category_id','date_from','date_to','queue','tag'}
    query=urlencode([(k,v) for k,v in parse_qsl(m.text_field(d,'query',2000)) if k in allowed])
    async with m.Session() as s:
        s.add(SavedView(operator_id=op.id,name=m.text_field(d,'name',100,True),query=query));await s.commit()
    return m.redirect('/operations')

@app.post('/views/{vid}/delete')
async def delete_view(request:Request,vid:int,op=Depends(m.current_operator)):
    await m.form_data(request)
    async with m.Session() as s:
        v=await s.get(SavedView,vid)
        if not v or v.operator_id!=op.id:raise HTTPException(404)
        await s.delete(v);await s.commit()
    return m.redirect('/operations')

@app.post('/sessions/{sid}/revoke')
async def revoke(request:Request,sid:str,op=Depends(m.current_operator)):
    await m.form_data(request)
    async with m.Session() as s:
        row=await s.get(LoginSession,sid)
        if not row or row.operator_id!=op.id:raise HTTPException(404)
        row.revoked=True;m.audit(s,op,'session revoked');await s.commit()
    return m.redirect('/operations')

@app.post('/jobs/{jid}/retry')
async def retry(request:Request,jid:int,op=Depends(m.admin)):
    await m.form_data(request)
    async with m.Session() as s:
        row=await s.scalar(select(WorkItem).where(WorkItem.id==jid).with_for_update())
        if not row or row.state!='dead':raise HTTPException(409,'Повтор доступен только для неудачных задач')
        row.state,row.attempts,row.due_at,row.error='queued',0,now(),''
        m.audit(s,op,f'retry job {jid}');await s.commit()
    return m.redirect('/operations')

@app.post('/teams')
async def team(request:Request,op=Depends(m.admin)):
    d=await m.form_data(request)
    try:
        config=json.loads(m.text_field(d,'calendar',10000) or '{}')
        from .sla import DEFAULTS
        config=validate({**DEFAULTS,**config})
        if not isinstance(config.get('exceptions',{}),dict):raise ValueError('exceptions: объект дата → true/false')
        for day,value in config.get('exceptions',{}).items():
            datetime.strptime(day,'%Y-%m-%d')
            if type(value) is not bool:raise ValueError('День: true или false')
    except (ValueError,TypeError,KeyError) as exc:raise HTTPException(400,str(exc))
    async with m.Session() as s:
        tid=m.int_field(d,'team_id')
        t=await s.get(Team,tid) if tid else Team()
        if not t:raise HTTPException(404)
        t.name=m.text_field(d,'name',120,True);t.calendar=config;s.add(t)
        m.audit(s,op,'team calendar saved');await s.commit()
    return m.redirect('/operations')

@app.post('/teams/operator')
async def team_operator(request:Request,op=Depends(m.admin)):
    d=await m.form_data(request)
    async with m.Session() as s:
        target=await s.get(Operator,m.int_field(d,'operator_id'))
        tid=m.int_field(d,'team_id') or None;role=str(d.get('role',''))
        if not target or role not in m.ROLES or (tid and not await s.get(Team,tid)):raise HTTPException(400,'Некорректная команда или роль')
        if target.id==op.id and role!='admin':raise HTTPException(400,'Нельзя снять собственные права администратора')
        active=await s.scalar(select(Ticket.id).where(Ticket.assigned_to==target.id,Ticket.status!='closed').limit(1))
        if active and target.team_id!=tid:raise HTTPException(409,'Сначала переназначьте активные обращения оператора')
        target.team_id,target.role=tid,role;target.auth_version+=1
        m.audit(s,op,f'operator {target.id} role/team changed');await s.commit()
    return m.redirect('/operations')

@app.post('/holidays')
async def holiday(request:Request,op=Depends(m.admin)):
    d=await m.form_data(request)
    try:day=datetime.strptime(str(d.get('day','')),'%Y-%m-%d').replace(tzinfo=timezone.utc)
    except ValueError:raise HTTPException(400,'Некорректная дата')
    async with m.Session() as s:
        h=await s.scalar(select(Holiday).where(Holiday.day==day))
        if not h:h=Holiday(day=day);s.add(h)
        h.title=m.text_field(d,'title',160,True);h.is_working=d.get('working')=='on'
        m.audit(s,op,'calendar exception saved');await s.commit()
    return m.redirect('/operations')

@app.post('/tickets/bulk')
async def bulk(request:Request,op=Depends(m.current_operator)):
    d=await m.form_data(request)
    try:ids=sorted(set(int(v) for v in str(d.get('ids','')).replace(',',' ').split()))
    except ValueError:raise HTTPException(400,'Укажите номера через пробел')
    if not 1<=len(ids)<=100:raise HTTPException(400,'От 1 до 100 обращений')
    action=str(d.get('action',''));value=m.text_field(d,'value',500)
    async with m.Session() as s:
        tickets=(await s.scalars(select(Ticket).where(Ticket.id.in_(ids)).order_by(Ticket.id).with_for_update())).all()
        if len(tickets)!=len(ids):raise HTTPException(404,'Есть недоступные обращения; ничего не изменено')
        if action=='status' and any(t.shop_merged_into_id for t in tickets):raise HTTPException(409,'Обращение объединено; откройте итоговую историю')
        for t in tickets:
            if action=='status' and value in STATUSES:
                if value=='closed':await close_ticket(s,t)
                else:t.status=value;t.closed_at=None
            elif action=='assign':
                try:target=await s.get(Operator,int(value))
                except ValueError:raise HTTPException(400,'Нужен номер оператора')
                if not target or not target.active or target.team_id!=t.team_id or target.role not in ('admin','manager','senior_operator','operator'):raise HTTPException(400,'Оператор другой команды')
                t.assigned_to=target.id
            elif action=='tag':t.tags=','.join(sorted(set(filter(None,t.tags.split(',')+[value]))))[:500]
            elif action=='team' and op.role=='admin':
                try:tid=int(value) or None
                except ValueError:raise HTTPException(400,'Нужен номер команды')
                if tid and not await s.get(Team,tid):raise HTTPException(404)
                t.team_id=tid;t.assigned_to=None
                from .services import settings
                from .sla import set_deadlines
                set_deadlines(t,await settings(s,tid))
            else:raise HTTPException(400,'Некорректное действие')
            t.updated_at=now();m.audit(s,op,f'bulk {action} ticket {t.id}')
        await s.commit()
    return m.redirect('/')

@app.get('/ticket/{tid}/merge-preview')
async def merge_preview(request:Request,tid:int,source:int,op=Depends(m.current_operator)):
    async with m.Session() as s:
        t=await m.ticket_get(s,tid);a=await m.ticket_get(s,source)
        if t.shop_ticket_id or a.shop_ticket_id:raise HTTPException(409,'Связанные обращения нельзя объединять только в локальной копии')
        if t.id==a.id or t.telegram_user_id!=a.telegram_user_id or t.channel!=a.channel or t.team_id!=a.team_id:raise HTTPException(400,'Нужны разные обращения одного клиента, команды и канала')
        count=await s.scalar(select(func.count()).select_from(Message).where(Message.ticket_id==source))
    request.session['merge_confirm']={'target':tid,'source':source,'version':str(a.updated_at),'target_version':str(t.updated_at)}
    return await page(request,op,'Подтверждение объединения',merge=(t,a,count))

@app.get('/incidents')
async def incidents(request:Request,op=Depends(m.current_operator)):
    async with m.Session() as s:
        items=(await s.scalars(select(Incident).order_by(Incident.id.desc()).limit(100))).all()
        tickets=(await s.scalars(select(Ticket).where(Ticket.status!='closed').order_by(Ticket.id.desc()).limit(200))).all()
        counts={i.id:await s.scalar(select(func.count(func.distinct(Ticket.telegram_user_id))).select_from(Ticket).join(IncidentTicket,IncidentTicket.ticket_id==Ticket.id).where(IncidentTicket.incident_id==i.id)) for i in items}
        suggestions=[]
        for idx,t in enumerate(tickets):
            similar=[x for x in tickets[idx+1:] if x.team_id==t.team_id and SequenceMatcher(None,t.subject.lower(),x.subject.lower()).ratio()>=.65]
            if similar:suggestions.append((t,similar[:5]))
    return await page(request,op,'Инциденты',incidents=items,counts=counts,suggestions=suggestions[:20])

@app.post('/incidents')
async def incident_create(request:Request,op=Depends(m.current_operator)):
    d=await m.form_data(request)
    try:ids=sorted(set(map(int,str(d.get('ids','')).replace(',',' ').split())))
    except ValueError:raise HTTPException(400,'Некорректные номера')
    if not 1<=len(ids)<=100:raise HTTPException(400,'От 1 до 100 обращений')
    async with m.Session() as s:
        tickets=(await s.scalars(select(Ticket).where(Ticket.id.in_(ids)))).all()
        if len(tickets)!=len(ids) or len({t.team_id for t in tickets})!=1:raise HTTPException(400,'Нужны обращения одной доступной команды')
        i=Incident(title=m.text_field(d,'title',255,True),team_id=tickets[0].team_id,draft='Мы проверяем проблему. Сообщим, когда появится решение.')
        s.add(i);await s.flush()
        for t in tickets:s.add(IncidentTicket(incident_id=i.id,ticket_id=t.id))
        m.audit(s,op,f'incident {i.id} created');await s.commit()
    return m.redirect('/incidents')

@app.post('/incidents/{iid}')
async def incident_update(request:Request,iid:int,op=Depends(m.current_operator)):
    d=await m.form_data(request)
    async with m.Session() as s:
        i=await s.scalar(select(Incident).where(Incident.id==iid).with_for_update())
        if not i:raise HTTPException(404)
        if m.int_field(d,'revision')!=i.revision:raise HTTPException(409,'Инцидент изменился; обновите страницу')
        draft=m.text_field(d,'draft',4000,True)
        if d.get('send')=='yes':
            if draft!=i.draft:raise HTTPException(409,'Сначала сохраните текст, затем подтвердите отправку')
            tickets=(await s.scalars(select(Ticket).join(IncidentTicket,IncidentTicket.ticket_id==Ticket.id).where(IncidentTicket.incident_id==iid,Ticket.status!='closed'))).all()
            for t in tickets:
                key=f'incident:{iid}:{i.revision}:{t.id}'
                if not await s.scalar(select(Message.id).where(Message.source_key==key)):
                    s.add(Message(ticket_id=t.id,operator_id=op.id,sender='operator',text=draft,delivery_state='queued',source_key=key))
            m.audit(s,op,f'incident {iid} update approved')
        else:
            i.draft=draft;i.revision+=1;i.status='resolved' if d.get('status')=='resolved' else 'open'
        await s.commit()
    return m.redirect('/incidents')
