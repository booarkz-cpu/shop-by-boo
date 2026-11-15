"""Canonical conversation, restricted machine access and retry-safe migration."""
import base64
from datetime import datetime
import httpx
import pytest
from sqlalchemy import select,func
from app import main as shop
from app import support_bridge as bridge
from app.db import get_db
from app.models import User,SupportTicket,SupportMessage,SupportImportLink,Notification
from test_subscription_commerce import database

@pytest.fixture
def api(database,monkeypatch):
    monkeypatch.setattr(bridge.settings,'support_bridge_token','bridge-test-secret-'+'x'*32)
    async def db():yield database
    shop.app.dependency_overrides[get_db]=db
    yield httpx.AsyncClient(transport=httpx.ASGITransport(app=shop.app),base_url='https://localhost',
        headers={'Authorization':'Bearer '+bridge.settings.support_bridge_token,'X-Support-Instance':'support-main'})
    shop.app.dependency_overrides.pop(get_db,None)

@pytest.mark.asyncio
async def test_bridge_auth_and_private_read(database,api):
    database.add(SupportTicket(id=1,user_id=1,subject='VPN',message='Private question'));await database.commit()
    async with api:
        denied=await api.get('/api/internal/support-bridge/tickets',headers={'Authorization':'Bearer invalid'})
        assert denied.status_code==401
        rows=(await api.get('/api/internal/support-bridge/tickets')).json()
        assert rows['items'][0]['user_id']==1
        page=(await api.get('/api/internal/support-bridge/tickets/1/messages')).json()
        assert page['messages'][0]['body']=='Private question'
        item=await api.post('/api/internal/support-bridge/tickets/1/attachments',headers={'Idempotency-Key':'file-once'},json={'name':'log.txt','content_base64':base64.b64encode(b'log').decode()})
        assert item.status_code==200
        assert (await api.get('/api/internal/support-bridge/attachments/'+str(item.json()['id']))).status_code==404

@pytest.mark.asyncio
async def test_reply_lost_response_reuses_message_and_notification(database,api):
    database.add(SupportTicket(id=1,user_id=1,subject='VPN',message='Question'));await database.commit()
    async with api:
        payload={'body':'Operator reply','attachment_ids':[]};headers={'Idempotency-Key':'sp:support-main:reply:17'}
        first=(await api.post('/api/internal/support-bridge/tickets/1/reply',headers=headers,json=payload)).json()
        second=(await api.post('/api/internal/support-bridge/tickets/1/reply',headers=headers,json=payload)).json()
        assert first['id']==second['id'] and first['created'] and not second['created']
        assert await database.scalar(select(func.count()).select_from(Notification))==1
        assert (await api.post('/api/internal/support-bridge/tickets/1/reply',headers=headers,json={'body':'changed'})).status_code==409
        assert (await api.post('/api/internal/support-bridge/tickets/1/status',json={'status':'open','expected_message_id':0})).status_code==409
        assert (await api.post('/api/internal/support-bridge/tickets/1/status',json={'status':'open','expected_message_id':first['id']})).status_code==200
        page=(await api.get('/api/internal/support-bridge/tickets/1/messages')).json()
        assert page['messages'][-1]['source_key']==headers['Idempotency-Key']

@pytest.mark.asyncio
async def test_import_requires_existing_identity_and_dry_run_is_read_only(database,api):
    owner=await database.get(User,1);owner.telegram_id=777;await database.commit()
    async with api:
        data={'telegram_id':777,'subject':'Old ticket','created_at':'2025-01-01T12:00:00+03:00'}
        preview=(await api.post('/api/internal/support-bridge/imports/90',json=data)).json()
        assert preview['dry_run'] and await database.scalar(select(func.count()).select_from(SupportImportLink))==0
        missing=await api.post('/api/internal/support-bridge/imports/91',json={**data,'telegram_id':888,'dry_run':False})
        assert missing.status_code==409
        first=(await api.post('/api/internal/support-bridge/imports/90',json={**data,'dry_run':False})).json()
        again=(await api.post('/api/internal/support-bridge/imports/90',json={**data,'dry_run':False})).json()
        assert first['id']==again['id'] and first['created'] and not again['created']
        body={'body':'Old reply','role':'admin','created_at':'2025-01-02T00:00:00Z'}
        headers={'Idempotency-Key':'sp:support-main:import:5'}
        for _ in range(2):assert (await api.post('/api/internal/support-bridge/imports/90/messages',headers=headers,json=body)).status_code==200
        assert await database.scalar(select(func.count()).select_from(SupportMessage))==1
        assert await database.scalar(select(func.count()).select_from(Notification))==0
        m=await database.scalar(select(SupportMessage));assert m.created_at.year==2025
        ticket=await database.get(SupportTicket,first['id']);assert ticket.created_at.hour==9

@pytest.mark.asyncio
async def test_deleted_account_tombstone_and_telegram_owner_guard(database,api):
    owner=await database.get(User,1);owner.telegram_id=777
    database.add(SupportTicket(id=1,user_id=1,subject='Private',message='Private'));await database.commit()
    async with api:
        headers={'Idempotency-Key':'sp:support-main:customer:9'}
        assert (await api.post('/api/internal/support-bridge/tickets/1/customer-message',headers=headers,json={'body':'Wrong owner','telegram_id':888})).status_code==409
        assert (await api.post('/api/internal/support-bridge/tickets/1/customer-message',headers=headers,json={'body':'Correct','telegram_id':777})).status_code==200
        owner.deleted_at=datetime.utcnow();await database.commit()
        rows=(await api.get('/api/internal/support-bridge/tickets')).json()
        assert rows['items'][0]['deleted'] and rows['items'][0]['telegram_id'] is None
        page=(await api.get('/api/internal/support-bridge/tickets/1/messages')).json()
        assert page['deleted'] and page['messages']==[]
        assert (await api.post('/api/internal/support-bridge/tickets/1/customer-message',headers=headers,json={'body':'Correct','telegram_id':777})).status_code==409

@pytest.mark.asyncio
async def test_postgres_bridge_reply_race_creates_one_message(database,api):
    if database.bind.dialect.name!='postgresql':pytest.skip('Row lock concurrency verified in CI')
    import asyncio
    from sqlalchemy.ext.asyncio import AsyncSession
    database.add(SupportTicket(user_id=1,subject='Race',message='Question'));await database.commit()
    tid=await database.scalar(select(SupportTicket.id))
    async def independent_db():
        async with AsyncSession(database.bind,expire_on_commit=False) as s:yield s
    shop.app.dependency_overrides[get_db]=independent_db
    async with api:
        responses=await asyncio.gather(*(api.post(f'/api/internal/support-bridge/tickets/{tid}/reply',json={'body':'One reply'},headers={'Idempotency-Key':'sp:support-main:reply:99'}) for _ in range(2)))
        assert all(r.status_code==200 for r in responses)
        assert responses[0].json()['id']==responses[1].json()['id']
        assert sorted(r.json()['created'] for r in responses)==[False,True]
    assert await database.scalar(select(func.count()).select_from(SupportMessage))==1
    assert await database.scalar(select(func.count()).select_from(Notification))==1

@pytest.mark.asyncio
async def test_import_blocks_live_writers_until_explicit_completion(database,api):
    owner=await database.get(User,1);owner.telegram_id=777;await database.commit()
    async with api:
        created=(await api.post('/api/internal/support-bridge/imports/1',json={'telegram_id':777,'subject':'Migrating','created_at':'2026-01-01T00:00:00Z','dry_run':False})).json()
        tid=created['id']
        assert (await api.get('/api/internal/support-bridge/tickets')).json()['items']==[]
        assert (await api.post(f'/api/internal/support-bridge/tickets/{tid}/reply',json={'body':'Wait'},headers={'Idempotency-Key':'sp:support-main:reply:1'})).status_code==409
        assert (await api.post('/api/internal/support-bridge/imports/1/complete',json={'status':'open','expected_message_id':0})).status_code==200
        assert (await api.get('/api/internal/support-bridge/tickets')).json()['items'][0]['id']==tid
        assert (await api.post(f'/api/internal/support-bridge/tickets/{tid}/reply',json={'body':'Ready'},headers={'Idempotency-Key':'sp:support-main:reply:1'})).status_code==200

@pytest.mark.asyncio
async def test_portal_shop_identity_is_ticket_scoped(database,api):
    database.add(SupportTicket(id=1,user_id=1,subject='Portal',message='Question'));await database.commit()
    async with api:
        headers={'Idempotency-Key':'sp:support-main:customer:45'}
        path='/api/internal/support-bridge/tickets/1/customer-message'
        assert (await api.post(path,headers=headers,json={'user_id':2,'body':'Foreign'})).status_code==409
        response=await api.post(path,headers=headers,json={'user_id':1,'body':'My reply'})
        assert response.status_code==200
        again=await api.post(path,headers=headers,json={'user_id':1,'body':'My reply'})
        assert response.json()['id']==again.json()['id'] and not again.json()['created']

@pytest.mark.asyncio
async def test_topology_keeps_delivery_identity_and_reports_epoch(database,api):
    from types import SimpleNamespace
    from app import support_topology as topology
    from starlette.requests import Request
    database.add_all([SupportTicket(id=1,user_id=1,subject='One',message='One'),SupportTicket(id=2,user_id=1,subject='Two',message='Two')]);await database.commit()
    async with api:
        response=await api.post('/api/internal/support-bridge/tickets/1/reply',headers={'Idempotency-Key':'sp:support-main:reply:42'},json={'body':'Answer'})
        mid=response.json()['id']
        before=(await api.get('/api/internal/support-bridge/tickets/2/messages')).json()['history_version']
        op=topology.OperationIn(kind='merge',source_id=1,target_id=2)
        actor=SimpleNamespace(email='operator@example.test');preview=await topology.preview(op,database,actor)
        await topology.apply(op.model_copy(update={'fingerprint':preview['fingerprint']}),Request({'type':'http','headers':[(b'idempotency-key',b'topology')]}),database,actor)
        page=(await api.get('/api/internal/support-bridge/tickets/2/messages')).json()
        assert page['history_version']!=before
        moved=next(m for m in page['messages'] if m['id']==mid)
        assert moved['source_key']=='sp:support-main:reply:42'
        assert (await database.get(SupportMessage,mid)).idempotency_key.startswith('moved:')
        source=(await api.get('/api/internal/support-bridge/tickets/1/messages')).json();assert source['merged_into_id']==2
        before=page['history_version']
        await api.post('/api/internal/support-bridge/tickets/2/reply',headers={'Idempotency-Key':'sp:support-main:reply:43'},json={'body':'Another answer'})
        assert (await api.get('/api/internal/support-bridge/tickets/2/messages')).json()['history_version']==before

@pytest.mark.asyncio
async def test_postgres_delivery_identity_migration_roundtrip_and_downgrade_guard(database):
    if database.bind.dialect.name!='postgresql':pytest.skip('PostgreSQL migrations run in CI')
    import importlib.util
    from pathlib import Path
    from alembic.operations import Operations
    from alembic.migration import MigrationContext
    spec=importlib.util.spec_from_file_location('delivery_migration',Path('services/backend/alembic/versions/0062_support_delivery_identity.py'))
    migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
    database.add(SupportTicket(id=1,user_id=1,subject='Keep',message='Keep'));await database.flush()
    database.add(SupportMessage(ticket_id=1,role='admin',body='Keep',idempotency_key='sp:support-main:reply:1'));await database.commit()
    async with database.bind.begin() as conn:
        def roundtrip(connection):
            with Operations.context(MigrationContext.configure(connection)):migration.downgrade();migration.upgrade()
        await conn.run_sync(roundtrip)
    database.expire_all();message=await database.scalar(select(SupportMessage));assert message.delivery_key=='sp:support-main:reply:1'
    message.idempotency_key='moved:hash';await database.commit()
    with pytest.raises(RuntimeError,match='prevent downgrade'):
        async with database.bind.begin() as conn:
            def refuse(connection):
                with Operations.context(MigrationContext.configure(connection)):migration.downgrade()
            await conn.run_sync(refuse)


@pytest.mark.asyncio
async def test_postgres_page_holds_topology_lock_until_history_is_read(database,api,monkeypatch):
    if database.bind.dialect.name!='postgresql':pytest.skip('Row lock concurrency verified in CI')
    import asyncio
    from sqlalchemy.ext.asyncio import AsyncSession
    database.add(SupportTicket(id=1,user_id=1,subject='Snapshot',message='Question'))
    await database.commit()
    started=asyncio.Event()
    writer=None
    original=bridge.read_thread

    async def change_topology():
        async with AsyncSession(database.bind,expire_on_commit=False) as other:
            started.set()
            ticket=await other.scalar(select(SupportTicket).where(SupportTicket.id==1).with_for_update())
            ticket.topology_version+=1
            ticket.subject='Changed topology'
            await other.commit()

    async def paused_read(db,ticket,after):
        nonlocal writer
        writer=asyncio.create_task(change_topology())
        await started.wait()
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.shield(writer),timeout=0.2)
        return await original(db,ticket,after)

    monkeypatch.setattr(bridge,'read_thread',paused_read)
    try:
        async with api:
            response=await api.get('/api/internal/support-bridge/tickets/1/messages')
            assert response.status_code==200
            assert response.json()['history_version']=='0'
            assert response.json()['subject']=='Snapshot'
    finally:
        if writer is not None:await asyncio.wait_for(writer,timeout=5)
    await database.refresh(await database.get(SupportTicket,1))
    assert (await database.get(SupportTicket,1)).topology_version==1
