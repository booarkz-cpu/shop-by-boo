import base64
from datetime import datetime,timezone
from types import SimpleNamespace
import hashlib
import pytest
from sqlalchemy import select,func
from app import shop_bridge as bridge
from app.shop_migrate import migrate_ticket
from app.models import Ticket,Message,Attachment,WorkItem,ShopSyncState,Client
from conftest import post

class FakeAPI:
    origin='https://shop.example.test'
    instance='support-main'
    def __init__(self):
        self.calls=[];self.sent={};self.fail_reply=False;self.deleted=False;self.completed=False
        self.messages=[{'id':0,'role':'customer','body':'VPN issue','created_at':'2026-01-01T00:00:00Z','attachments':[]}]
    async def request(self,method,path,payload=None,key=None):
        self.calls.append((method,path,payload,key))
        if path=='/tickets/recent':return {'items':[]}
        if path.startswith('/tickets?'):
            return {'items':[{'id':4,'user_id':23,'username':'shop-client','subject':'VPN','created_at':'2026-01-01T00:00:00Z','deleted':self.deleted}], 'next_cursor':None}
        if '/messages?' in path:
            after=int(path.split('after=')[1]);rows=[x for x in self.messages if x['id']>after or (x['id']==0 and after==0)]
            return {'messages':rows,'next_cursor':None,'deleted':self.deleted,'status':'open'}
        if path=='/attachments/88':return {'name':'log.txt','content_base64':base64.b64encode(b'log').decode()}
        if path.endswith('/attachments'):return {'id':88}
        if path.endswith('/reply') or path.endswith('/customer-message'):
            if key not in self.sent:self.sent[key]={'id':100+len(self.sent),'created':True}
            result=self.sent[key]
            if self.fail_reply:self.fail_reply=False;raise TimeoutError('lost response')
            return result
        if path.endswith('/status'):return {'status':payload['status']}
        if path.endswith('/complete'):self.completed=True;return {'completed':True}
        if '/imports/' in path and path.endswith('/messages'):return {'id':42}
        if '/imports/' in path:return {'id':4,'dry_run':payload['dry_run'],'completed':self.completed}
        raise AssertionError(path)

async def test_poll_is_idempotent_files_are_private_and_deleted_account_is_purged(env):
    api=FakeAPI();api.messages.append({'id':5,'role':'customer','body':'Attached','created_at':'2026-01-01T01:00:00Z',
        'attachments':[{'id':88,'name':'log.txt','size':3,'sha256':hashlib.sha256(b'log').hexdigest()}]})
    await bridge.poll(env['session'],api);await bridge.poll(env['session'],api)
    async with env['session']() as s:
        assert await s.scalar(select(func.count()).select_from(Ticket))==1
        assert await s.scalar(select(func.count()).select_from(Message))==2
        assert await s.scalar(select(func.count()).select_from(Attachment))==1
        t=await s.scalar(select(Ticket));assert t.channel=='shop' and t.telegram_user_id==-23
        assert t.shop_last_message_id==5 and t.shop_initial_loaded
        a=await s.scalar(select(Attachment));path=bridge.checked_path(a.path);assert path.read_bytes()==b'log'
        assert not await s.scalar(select(WorkItem.id).where(WorkItem.kind=='shop_status'))
    api.deleted=True;await bridge.poll(env['session'],api)
    assert not path.exists()
    async with env['session']() as s:
        assert await s.scalar(select(func.count()).select_from(Attachment))==0
        assert all(m.text=='[Аккаунт удалён]' for m in (await s.scalars(select(Message))).all())

async def test_operator_reply_lost_answer_retries_same_key_and_echo_does_not_duplicate(env):
    api=FakeAPI();await bridge.poll(env['session'],api)
    async with env['session']() as s:
        t=await s.scalar(select(Ticket));m=Message(ticket_id=t.id,sender='operator',operator_id=env['oid'],text='Check VPN',delivery_state='sending',source_key='web:reply-once')
        s.add(m);await s.commit();mid=m.id;api.fail_reply=True
        with pytest.raises(TimeoutError):await bridge.deliver(s,t,m,api)
        await bridge.deliver(s,t,m,api)
        assert m.delivery_state=='sent' and len(api.sent)==1
    replies=[x for x in api.calls if x[1].endswith('/reply')];assert replies[0][3]==replies[1][3]
    api.messages.append({'id':100,'role':'admin','body':'Check VPN','source_key':f'sp:support-main:reply:{mid}',
        'created_at':datetime.now(timezone.utc).isoformat(),'attachments':[]})
    await bridge.poll(env['session'],api)
    async with env['session']() as s:assert await s.scalar(select(func.count()).select_from(Message))==2

async def test_status_has_durable_compare_and_swap_and_pull_has_no_feedback(env):
    api=FakeAPI();await bridge.poll(env['session'],api)
    async with env['session']() as s:
        t=await s.scalar(select(Ticket));tid=t.id
    response=await post(env,f'/ticket/{tid}/update',status='closed',priority='normal')
    assert response.status_code==303
    async with env['session']() as s:
        job=await s.scalar(select(WorkItem).where(WorkItem.kind=='shop_status'))
        assert job.payload=={'status':'resolved','expected_message_id':0}
    assert await bridge.status_one(env['session'],api)
    assert any(x[1]=='/tickets/4/status' for x in api.calls)

async def test_migration_preview_retains_internal_notes_and_apply_is_resumable(env):
    api=FakeAPI()
    async with env['session']() as s:
        c=Client(telegram_user_id=777,full_name='Legacy');s.add(c)
        t=Ticket(telegram_user_id=777,subject='Old');s.add(t);await s.flush()
        s.add_all([Message(ticket_id=t.id,sender='user',text='Question',delivery_state='received'),
            Message(ticket_id=t.id,sender='operator',text='Reply',delivery_state='legacy'),
            Message(ticket_id=t.id,sender='note',text='Internal secret',delivery_state='internal')]);await s.commit();tid=t.id
    preview=await migrate_ticket(env['session'],api,tid)
    assert preview['messages']==2 and preview['internal_notes_retained']==1 and preview['dry_run']
    async with env['session']() as s:assert (await s.get(Ticket,tid)).shop_ticket_id is None
    result=await migrate_ticket(env['session'],api,tid,True)
    again=await migrate_ticket(env['session'],api,tid,True)
    assert result['completed'] and again['completed']
    assert not any('Internal secret' in str(x[2]) for x in api.calls)
    async with env['session']() as s:
        t=await s.get(Ticket,tid);assert t.channel=='shop' and t.shop_import_complete
        assert await s.scalar(select(Message.text).where(Message.sender=='note'))=='Internal secret'

async def test_origin_change_cannot_rebind_existing_conversations(env):
    api=FakeAPI();await bridge.poll(env['session'],api)
    api.origin='https://different-shop.example.test'
    with pytest.raises(bridge.BridgeError):await bridge.poll(env['session'],api)

@pytest.mark.parametrize('name,data',[('bad.html',b'<html>'),('fake.png',b'fake'),('big.txt',b'x'*(2*1024*1024+1))])
def test_shop_attachment_constraints_are_checked_before_upload(name,data):
    with pytest.raises(bridge.BridgeError):bridge.validate_file(name,data)

@pytest.mark.parametrize('env',['postgres'],indirect=True)
async def test_postgres_parallel_polls_lock_cursor_and_do_not_duplicate(env):
    import asyncio
    api=FakeAPI()
    async with env['session']() as s:
        s.add(ShopSyncState(id=1,origin='',instance='',after_id=0));await s.commit()
    await asyncio.gather(bridge.poll(env['session'],api),bridge.poll(env['session'],api))
    async with env['session']() as s:
        assert await s.scalar(select(func.count()).select_from(Ticket))==1
        assert await s.scalar(select(func.count()).select_from(Message))==1
        assert (await s.get(ShopSyncState,1)).origin==api.origin

async def test_linked_portal_keeps_pending_customer_message_visible_and_rejects_html(env):
    import httpx,re,secrets
    from app import main
    from app.models import PortalAccess
    from datetime import timedelta
    api=FakeAPI();await bridge.poll(env['session'],api)
    raw=secrets.token_urlsafe(32)
    async with env['session']() as s:
        t=await s.scalar(select(Ticket));tid=t.id
        s.add(PortalAccess(token_hash=hashlib.sha256(raw.encode()).hexdigest(),client_id=t.telegram_user_id,expires_at=datetime.now(timezone.utc)+timedelta(days=1)));await s.commit()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),base_url='https://testserver') as client:
        assert (await client.get('/portal/access/'+raw)).status_code==303
        page=await client.get(f'/portal/ticket/{tid}')
        csrf=re.search('name="csrf-token" content="([^"]+)"',page.text)[1]
        nonce=re.search('name="nonce" value="([^"]+)"',page.text)[1]
        result=await client.post(f'/portal/ticket/{tid}',data={'csrf_token':csrf,'nonce':nonce,'text':'Pending question'})
        assert result.status_code==303
        page=await client.get(f'/portal/ticket/{tid}')
        assert 'Pending question' in page.text and 'Передаём сообщение' in page.text
        nonce=re.search('name="nonce" value="([^"]+)"',page.text)[1]
        rejected=await client.post(f'/portal/ticket/{tid}',data={'csrf_token':csrf,'nonce':nonce,'text':'Unsafe file'},files={'file':('bad.html',b'<script>', 'text/html')})
        assert rejected.status_code==400
    async with env['session']() as s:
        assert not await s.scalar(select(Message.id).where(Message.text=='Unsafe file'))
