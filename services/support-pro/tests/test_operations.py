import hashlib, hmac, json, re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
import httpx
import pytest
from sqlalchemy import select, func
from app import main, jobs, worker, storage
from app.models import *
from app.sla import DEFAULTS,business_add,utc
from app.services import create_ticket
from conftest import post

pytestmark=pytest.mark.asyncio

async def make_ticket(env,uid=800,team_id=None,channel='telegram'):
    async with env['session']() as s:
        c=Client(telegram_user_id=uid,full_name='Клиент');s.add(c)
        t=await create_ticket(s,c,'Не работает оплата',team_id=team_id,channel=channel)
        await s.commit();return t.id

async def test_scope_and_readonly_enforced_on_related_records(env):
    async with env['session']() as s:
        team=Team(name='Другие',calendar={});s.add(team);await s.commit();team_id=team.id
    tid=await make_ticket(env,team_id=team_id)
    async with env['session']() as s:
        msg=Message(ticket_id=tid,sender='operator',text='Secret',delivery_state='failed');s.add(msg);await s.commit();mid=msg.id
        op=await s.get(Operator,env['oid']);op.role='operator';await s.commit()
    assert (await env['client'].get(f'/ticket/{tid}')).status_code==404
    assert 'Не работает оплата' not in (await env['client'].get('/')).text
    assert (await post(env,f'/message/{mid}/retry')).status_code==400
    assert (await env['client'].get('/client/800')).status_code==404
    async with env['session']() as s:
        op=await s.get(Operator,env['oid']);op.role='viewer';await s.commit()
    assert (await post(env,'/tickets/bulk',ids=str(tid),action='status',value='closed')).status_code==403
    assert (await post(env,'/incidents',title='x',ids=str(tid))).status_code==403
    assert (await env['client'].get('/reports?format=csv')).status_code==403

async def test_session_revocation(env):
    async with env['session']() as s:row=await s.scalar(select(LoginSession));sid=row.id
    assert (await post(env,f'/sessions/{sid}/revoke')).status_code==303
    assert (await env['client'].get('/')).headers['location']=='/login'

async def test_outbox_rollback_and_rule_run_once(env):
    async with env['session']() as s:
        s.add(AutomationRule(title='Urgent',event='ticket.created',conditions={},actions={'priority':'urgent','notify':'Check'}))
        await s.commit()
    tid=await make_ticket(env)
    async with env['session']() as s:
        before=await s.scalar(select(func.count()).select_from(WorkItem))
        t=await s.get(Ticket,tid);t.subject='ROLLBACK';await s.flush();await s.rollback()
        assert await s.scalar(select(func.count()).select_from(WorkItem))==before
    for _ in range(25):
        if not await jobs.tick(env['session']):break
    async with env['session']() as s:
        assert (await s.get(Ticket,tid)).priority=='urgent'
        assert await s.scalar(select(func.count()).select_from(Notification).where(Notification.text=='Check'))==1
        assert await s.scalar(select(func.count()).select_from(WorkItem).where(WorkItem.state!='done'))==0

async def test_webhook_retry_signing_and_dead_letter(env,monkeypatch):
    monkeypatch.setenv('WEBHOOK_ALLOWED_HOSTS','hooks.example')
    async with env['session']() as s:
        hook=WebhookEndpoint(name='Hook',url='https://hooks.example/event',secret='secret',events=['ticket.created']);s.add(hook);await s.flush()
        job=WorkItem(key='stable-id',kind='webhook',event='ticket.created',target_id=hook.id,payload={'ticket_id':1});s.add(job);await s.commit();jid=job.id
    calls=[]
    class Transport:
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def post(self,url,**kwargs):
            calls.append(kwargs)
            return httpx.Response(503,request=httpx.Request('POST',url))
    monkeypatch.setattr(jobs.httpx,'AsyncClient',lambda **kwargs:Transport())
    for _ in range(8):
        async with env['session']() as s:
            j=await s.get(WorkItem,jid);j.due_at=now()-timedelta(seconds=1);await s.commit()
        await jobs.tick(env['session'])
    async with env['session']() as s:
        j=await s.get(WorkItem,jid);assert j.state=='dead' and j.attempts==8
    assert {c['headers']['Idempotency-Key'] for c in calls}=={'stable-id'}
    assert calls[0]['headers']['X-Support-Signature']=='sha256='+hmac.new(b'secret',calls[0]['content'],hashlib.sha256).hexdigest()

async def test_calendar_exceptions_pause_and_dst(env,monkeypatch):
    config={**DEFAULTS,'exceptions':{'2026-09-21':False,'2026-09-19':True}}
    assert business_add(datetime(2026,9,18,17,30,tzinfo=timezone.utc),120,config)==datetime(2026,9,19,10,30,tzinfo=timezone.utc)
    config['exceptions']['2026-09-19']=False
    assert business_add(datetime(2026,9,18,17,30,tzinfo=timezone.utc),120,config)==datetime(2026,9,22,10,30,tzinfo=timezone.utc)
    from app import events
    pause=datetime(2026,9,18,17,0,tzinfo=timezone.utc)
    resume=datetime(2026,9,21,10,0,tzinfo=timezone.utc)
    tid=await make_ticket(env)
    monkeypatch.setattr(events,'now',lambda:pause)
    async with env['session']() as s:
        t=await s.get(Ticket,tid)
        t.sla_deadline=datetime(2026,9,21,11,0,tzinfo=timezone.utc)
        t.status='pending';await s.commit()
        monkeypatch.setattr(events,'now',lambda:resume)
        t.status='open';await s.commit()
        # Three working hours remained at pause; resume at 10:00 means 13:00.
        assert utc(t.sla_deadline)==datetime(2026,9,21,13,0,tzinfo=timezone.utc)
        assert t.paused_at is None

async def test_bulk_merge_mentions_and_saved_views(env):
    tid=await make_ticket(env)
    async with env['session']() as s:
        c=await s.get(Client,800);other=await create_ticket(s,c,'Другая тема');await s.commit();other_id=other.id
    assert (await post(env,'/tickets/bulk',ids=f'{tid} {other_id}',action='tag',value='incident')).status_code==303
    assert (await post(env,'/views',name='Мои',query='queue=mine&unknown=discard')).status_code==303
    assert (await env['client'].get('/operations')).status_code==200
    assert (await post(env,f'/ticket/{tid}/reply',kind='note',text='@admin проверь',nonce='abcdefghijklmnop')).status_code==303
    async with env['session']() as s:assert await s.scalar(select(Notification.id).where(Notification.text.contains('упомянул')))
    assert (await post(env,f'/ticket/{tid}/merge',source_ticket_id=str(other_id))).status_code==409
    assert (await env['client'].get(f'/ticket/{tid}/merge-preview?source={other_id}')).status_code==200
    assert (await post(env,f'/ticket/{tid}/merge',source_ticket_id=str(other_id))).status_code==303

async def test_portal_isolation_notes_uploads_and_delivery(env):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),base_url='https://testserver') as client:
        page=await client.get('/portal');csrf=re.search('name="csrf-token" content="([^"]+)"',page.text)[1]
        assert (await client.post('/portal/start',data={'csrf_token':csrf,'name':'Customer'})).status_code==200
        response=await client.post('/portal/tickets',data={'csrf_token':csrf,'subject':'Веб-вопрос','text':'Помогите'})
        tid=int(response.headers['location'].split('/')[-1])
        await post(env,f'/ticket/{tid}/reply',kind='note',text='PRIVATE',nonce='abcdefghijklmnop')
        await post(env,f'/ticket/{tid}/reply',kind='reply',text='PUBLIC',nonce='qrstuvwxyzabcdef')
        mid=await worker.claim_message();fake=SimpleNamespace(send_message=AsyncMock());await worker.deliver(fake,mid)
        fake.send_message.assert_not_awaited()
        page=await client.get(f'/portal/ticket/{tid}');assert 'PUBLIC' in page.text and 'PRIVATE' not in page.text
        nonce=re.search('name="nonce" value="([^"]+)"',page.text)[1]
        r=await client.post(f'/portal/ticket/{tid}',data={'csrf_token':csrf,'nonce':nonce,'text':'Файл'},files={'file':('a.txt',b'data','text/plain')})
        assert r.status_code==303
        async with env['session']() as s:a=await s.scalar(select(Attachment).where(Attachment.ticket_id==tid));aid=a.id
        assert (await client.get(f'/portal/attachment/{aid}')).content==b'data'
        foreign=await make_ticket(env,uid=801)
        assert (await client.get(f'/portal/ticket/{foreign}')).status_code==404
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),base_url='https://testserver') as other:
        assert (await other.get(f'/portal/ticket/{tid}')).status_code==303

async def test_incident_approval_idempotency(env):
    tid=await make_ticket(env)
    assert (await post(env,'/incidents',ids=str(tid),title='Сбой оплаты')).status_code==303
    assert (await env['client'].get('/incidents')).status_code==200
    async with env['session']() as s:i=await s.scalar(select(Incident));iid=i.id;draft=i.draft
    for _ in range(2):assert (await post(env,f'/incidents/{iid}',revision='0',draft=draft,send='yes')).status_code==303
    async with env['session']() as s:assert await s.scalar(select(func.count()).select_from(Message).where(Message.sender=='operator'))==1

async def test_scanner_fails_closed(env,monkeypatch):
    monkeypatch.setenv('REQUIRE_ANTIVIRUS','true');monkeypatch.delenv('CLAMAV_HOST',raising=False)
    file=env['tmp_path']/'test.txt';file.write_text('test')
    with pytest.raises(ValueError):await storage.scan_file(file)

async def test_rule_validation_rejects_unknown_actions(env):
    r=await post(env,'/rules',title='bad',event='ticket.created',conditions='{}',actions='{"delete":true}')
    assert r.status_code==400

async def test_stale_webhook_lease_recovers(env,monkeypatch):
    monkeypatch.setenv('WEBHOOK_ALLOWED_HOSTS','hooks.example')
    async with env['session']() as s:
        hook=WebhookEndpoint(name='h',url='https://hooks.example/a',secret='x',events=[]);s.add(hook);await s.flush()
        job=WorkItem(key='crash-test',kind='webhook',event='test',target_id=hook.id,payload={},state='sending',attempts=1,due_at=now()-timedelta(minutes=3));s.add(job);await s.commit();jid=job.id
    class Transport:
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def post(self,url,**kwargs):return httpx.Response(200,request=httpx.Request('POST',url))
    monkeypatch.setattr(jobs.httpx,'AsyncClient',lambda **kwargs:Transport())
    assert await jobs.tick(env['session'])
    async with env['session']() as s:
        j=await s.get(WorkItem,jid);assert j.state=='done' and j.attempts==2

async def test_scanner_stream_accepts_clean_and_blocks_infected(env,monkeypatch):
    import asyncio
    monkeypatch.setenv('CLAMAV_HOST','clamav')
    file=env['tmp_path']/'sample';file.write_bytes(b'example')
    class Writer:
        def write(self,data):pass
        async def drain(self):pass
        def close(self):pass
        async def wait_closed(self):pass
    answer=b'stream: OK\0'
    async def connection(*args):
        reader=asyncio.StreamReader();reader.feed_data(answer);reader.feed_eof();return reader,Writer()
    monkeypatch.setattr(asyncio,'open_connection',connection)
    await storage.scan_file(file)
    answer=b'stream: Eicar-Test-Signature FOUND\0'
    with pytest.raises(ValueError):await storage.scan_file(file)

async def test_cross_team_attachments_bulk_and_export(env):
    async with env['session']() as s:
        team=Team(name='Private',calendar={});s.add(team);await s.commit();team_id=team.id
    tid=await make_ticket(env,team_id=team_id)
    mine=await make_ticket(env,uid=802)
    async with env['session']() as s:
        a=Attachment(ticket_id=tid,filename='secret',path='/data/uploads/private',size=2,state='ready');s.add(a);await s.flush();aid=a.id
        op=await s.get(Operator,env['oid']);op.role='manager';await s.commit()
    assert (await env['client'].get(f'/attachment/{aid}')).status_code==404
    response=await env['client'].get('/reports?format=csv');assert response.status_code==200
    # Bulk operation must be all-or-nothing even when one id is out of scope.
    assert (await post(env,'/tickets/bulk',ids=f'{mine} {tid}',action='status',value='closed')).status_code==404
    async with env['session']() as s:assert (await s.get(Ticket,mine)).status!='closed'

async def test_team_calendar_and_holiday_routes(env):
    assert (await post(env,'/teams',name='Night',calendar=json.dumps({**DEFAULTS,'start_hour':1,'end_hour':6}))).status_code==303
    assert (await post(env,'/holidays',day='2026-10-01',title='Выходной')).status_code==303
    async with env['session']() as s:
        from app.services import settings
        team=await s.scalar(select(Team).where(Team.name=='Night'))
        config=await settings(s,team.id)
        assert config['start_hour']==1 and config['exceptions']['2026-10-01'] is False
    assert (await env['client'].get('/operations')).status_code==200
