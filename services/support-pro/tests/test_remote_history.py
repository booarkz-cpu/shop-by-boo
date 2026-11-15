"""Canonical topology retains identity, files and local operator notes."""
import base64
import hashlib
from sqlalchemy import select,func
import pytest
from app import shop_bridge as bridge,worker
from app.models import Ticket,Message,Attachment,WorkItem
from conftest import post
STAMP='2026-01-01T00:00:00Z'
def msg(identifier,text='Text',role='customer',attachments=None):
    return {'id':identifier,'role':role,'body':text,'created_at':STAMP,'attachments':attachments or []}
class Timeline:
    origin='https://shop.example.test';instance='support-main'
    def __init__(self):
        self.items={i:{'id':i,'user_id':23,'telegram_id':777,'username':'client','subject':f'Ticket{i}','created_at':STAMP,'deleted':False,'history_version':'1','merged_into_id':None} for i in (1,2)}
        self.history={1:[msg(0,'First'),msg(5,'Moving question',attachments=[{'id':88,'name':'log.txt','sha256':hashlib.sha256(b'log').hexdigest()}]),msg(6,'Moving reply','admin')],2:[msg(0,'Second'),msg(20,'Latest target')]}
        self.calls=[];self.page_size=100
    async def request(self,method,path,payload=None,key=None):
        self.calls.append((method,path,payload,key))
        if path=='/tickets/recent':return {'items':list(self.items.values())}
        if path.startswith('/tickets?'):return {'items':list(self.items.values()),'next_cursor':None}
        if '/messages?' in path:
            tid=int(path.split('/')[2]);after=int(path.split('after=')[1]);rows=[m for m in self.history[tid] if m['id']>after];page=rows[:self.page_size]
            if after==0:page=[self.history[tid][0],*page]
            return {'messages':page,'next_cursor':page[-1]['id'] if len(rows)>self.page_size else None,'deleted':False,'status':'merged' if self.items[tid]['merged_into_id'] else 'open','merged_into_id':self.items[tid]['merged_into_id'],'history_version':self.items[tid]['history_version']}
        if path=='/attachments/88':return {'name':'log.txt','content_base64':base64.b64encode(b'log').decode()}
        raise AssertionError(path)
    def move(self,merged=False):
        moved=self.history[1][1:];self.history[1]=self.history[1][:1]
        self.history[2]=[self.history[2][0],*sorted([*moved,*self.history[2][1:]],key=lambda m:m['id'])]
        self.items[1]['history_version']=self.items[2]['history_version']='2'
        if merged:self.items[1]['merged_into_id']=2

async def test_merge_rescans_lower_ids_moves_files_and_stops_old_outbox(env):
    api=Timeline();await bridge.poll(env['session'],api)
    async with env['session']() as s:
        source=await s.scalar(select(Ticket).where(Ticket.shop_ticket_id==1));target=await s.scalar(select(Ticket).where(Ticket.shop_ticket_id==2));sid,tid=source.id,target.id
        moving=await s.scalar(select(Message).where(Message.shop_message_id==5));moving_id=moving.id
        pending=Message(ticket_id=sid,sender='operator',text='Unsent reply',delivery_state='queued',source_key='web:pending');note=Message(ticket_id=sid,sender='note',text='Internal note',delivery_state='internal')
        s.add_all([pending,note,WorkItem(key='old-close',kind='shop_status',event='ticket.status',ticket_id=sid,payload={'status':'resolved','expected_message_id':6})]);await s.commit();pending_id=pending.id
    api.move(merged=True);await bridge.poll(env['session'],api);await bridge.poll(env['session'],api)
    async with env['session']() as s:
        assert (await s.get(Message,moving_id)).ticket_id==tid
        assert await s.scalar(select(func.count()).select_from(Message).where(Message.shop_message_id==5))==1
        a=await s.scalar(select(Attachment));assert a.ticket_id==tid and a.message_id==moving_id and bridge.checked_path(a.path).read_bytes()==b'log'
        assert (await s.scalar(select(Message).where(Message.text=='Internal note'))).ticket_id==sid
        source=await s.get(Ticket,sid);assert source.shop_merged_into_id==2 and source.status=='closed'
        assert (await s.get(Message,pending_id)).delivery_state=='uncertain'
        assert (await s.scalar(select(WorkItem).where(WorkItem.key=='old-close'))).state=='cancelled'
    assert await worker.claim_message() is None
    page=await env['client'].get(f'/ticket/{sid}');assert 'Открыть итоговое обращение' in page.text
    rejected=await post(env,f'/message/{pending_id}/retry',confirm_duplicate='yes');assert rejected.status_code==409

async def test_split_scan_cursor_is_durable_and_does_not_duplicate_old_ids(env):
    api=Timeline();await bridge.poll(env['session'],api);api.move();api.page_size=1
    await bridge.poll(env['session'],api)
    async with env['session']() as s:
        target=await s.scalar(select(Ticket).where(Ticket.shop_ticket_id==2));assert target.shop_scan_version=='2' and target.shop_scan_after_id==5
    await bridge.poll(env['session'],api);await bridge.poll(env['session'],api)
    async with env['session']() as s:
        target=await s.scalar(select(Ticket).where(Ticket.shop_ticket_id==2));source=await s.scalar(select(Ticket).where(Ticket.shop_ticket_id==1))
        assert target.shop_history_version=='2' and target.shop_scan_version==''
        assert source.shop_merged_into_id is None and source.status!='closed'
        assert await s.scalar(select(func.count()).select_from(Message).where(Message.shop_message_id.is_not(None)))==3
        assert not await s.scalar(select(Message.id).where(Message.ticket_id==source.id,Message.shop_message_id.in_([5,6])))

async def test_foreign_owner_mapping_is_rejected_and_rolls_back(env):
    api=Timeline();await bridge.poll(env['session'],api)
    api.items[2]['user_id']=99;api.items[2]['history_version']='2';api.history[2].insert(1,msg(5,'Foreign attempt'))
    with pytest.raises(bridge.BridgeError):await bridge.poll(env['session'],api)
    async with env['session']() as s:
        source=await s.scalar(select(Ticket).where(Ticket.shop_ticket_id==1));assert (await s.scalar(select(Message).where(Message.shop_message_id==5))).ticket_id==source.id

@pytest.mark.parametrize('env',['postgres'],indirect=True)
async def test_postgres_serialized_poll_keeps_global_message_identity(env):
    import asyncio
    api=Timeline();await bridge.poll(env['session'],api);api.move()
    await asyncio.gather(bridge.poll(env['session'],api),bridge.poll(env['session'],api))
    async with env['session']() as s:
        assert await s.scalar(select(func.count()).select_from(Message).where(Message.shop_message_id==5))==1

async def test_moved_reply_with_lost_acknowledgement_is_not_sent_twice(env):
    api=Timeline();await bridge.poll(env['session'],api)
    async with env['session']() as s:
        source=await s.scalar(select(Ticket).where(Ticket.shop_ticket_id==1))
        pending=Message(ticket_id=source.id,sender='operator',text='Lost ack',delivery_state='sending',source_key='web:lost-ack')
        s.add(pending);await s.commit();mid=pending.id
    remote=msg(7,'Lost ack','admin');remote['source_key']=f'sp:support-main:reply:{mid}';api.history[1].append(remote);api.move(merged=True)
    await bridge.poll(env['session'],api)
    async with env['session']() as s:
        target=await s.scalar(select(Ticket).where(Ticket.shop_ticket_id==2));local=await s.get(Message,mid)
        assert local.ticket_id==target.id and local.delivery_state=='sent' and local.shop_message_id==7
        assert await s.scalar(select(func.count()).select_from(Message).where(Message.text=='Lost ack'))==1
    assert await worker.claim_message() is None

@pytest.mark.parametrize('env',['postgres'],indirect=True)
async def test_postgres_remote_history_migration_backfills_and_protects_mappings(env):
    import importlib.util
    from pathlib import Path
    from alembic.operations import Operations
    from alembic.migration import MigrationContext
    spec=importlib.util.spec_from_file_location('remote_migration',Path('alembic/versions/0006_remote_history.py'))
    if not Path('alembic/versions/0006_remote_history.py').exists():spec=importlib.util.spec_from_file_location('remote_migration',Path('services/support-pro/alembic/versions/0006_remote_history.py'))
    migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
    async with env['session']() as s:
        legacy=Ticket(telegram_user_id=-23,shop_ticket_id=4,subject='Legacy',channel='shop');s.add(legacy);await s.flush()
        s.add(Message(ticket_id=legacy.id,sender='user',text='Legacy',source_key='shop:4:5'));await s.commit()
    async with env['session'].kw['bind'].begin() as conn:
        def roundtrip(connection):
            with Operations.context(MigrationContext.configure(connection)):migration.downgrade();migration.upgrade()
        await conn.run_sync(roundtrip)
    async with env['session']() as s:
        legacy=await s.scalar(select(Ticket).where(Ticket.shop_ticket_id==4));assert legacy.shop_user_id==23
        assert (await s.scalar(select(Message).where(Message.source_key=='shop:4:5'))).shop_message_id==5
        legacy.shop_history_version='1';await s.commit()
    with pytest.raises(RuntimeError,match='prevent downgrade'):
        async with env['session'].kw['bind'].begin() as conn:
            def refuse(connection):
                with Operations.context(MigrationContext.configure(connection)):migration.downgrade()
            await conn.run_sync(refuse)

async def test_automation_cannot_reopen_or_queue_messages_to_merged_source(env):
    api=Timeline();await bridge.poll(env['session'],api);api.move(merged=True);await bridge.poll(env['session'],api)
    async with env['session']() as s:
        source=await s.scalar(select(Ticket).where(Ticket.shop_ticket_id==1));source.status='open'
        automated=Message(ticket_id=source.id,sender='operator',text='Automated stale reply',delivery_state='queued');s.add(automated);await s.commit()
        assert source.status=='closed' and automated.delivery_state=='uncertain'
    assert await worker.claim_message() is None
