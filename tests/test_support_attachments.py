import base64
import pytest
from fastapi import HTTPException
from sqlalchemy import select,func
from app import support_attachments as files
from app.customer_workspace_api import customer_support_reply,customer_support_messages,SupportMessageIn
from app.models import SupportTicket,SupportAttachment
from test_subscription_commerce import database,request

def payload(name='log.txt',data=b'VPN diagnostic log'):
    return files.AttachmentIn(name=name,content_base64=base64.b64encode(data).decode())

@pytest.mark.asyncio
async def test_private_attachment_retries_and_message_binding(database):
    database.add_all([SupportTicket(id=1,user_id=1,subject='VPN',message='Error'),SupportTicket(id=2,user_id=2,subject='Other',message='Private')]);await database.commit()
    item=await files.customer_upload(1,payload(),request('upload-once'),database)
    again=await files.customer_upload(1,payload(),request('upload-once'),database)
    assert item==again and await database.scalar(select(func.count()).select_from(SupportAttachment))==1
    with pytest.raises(HTTPException):await files.customer_upload(1,payload(data=b'changed'),request('upload-once'),database)
    with pytest.raises(HTTPException):await files.customer_upload(2,payload(),request('foreign'),database)
    reply=SupportMessageIn(message='Log attached',attachment_ids=[item['id']])
    message=await customer_support_reply(1,reply,request('message-once'),database)
    assert not (await customer_support_reply(1,reply,request('message-once'),database))['created']
    thread=await customer_support_messages(1,request(),0,database)
    assert thread['messages'][-1]['attachments'][0]['id']==item['id']
    downloaded=await files.customer_download(item['id'],request(),database)
    assert base64.b64decode(__import__('json').loads(downloaded.body)['content_base64'])==b'VPN diagnostic log'
    with pytest.raises(HTTPException):await customer_support_reply(1,SupportMessageIn(message='Log attached'),request('message-once'),database)
    with pytest.raises(HTTPException):await customer_support_reply(1,reply,request('reuse-other-message'),database)

@pytest.mark.asyncio
async def test_foreign_ticket_and_admin_draft_are_not_downloadable(database):
    database.add_all([SupportTicket(id=1,user_id=1,subject='VPN',message='Error'),SupportTicket(id=2,user_id=2,subject='Other',message='Private')]);await database.commit()
    own=await database.get(SupportTicket,1);other=await database.get(SupportTicket,2)
    staff=await files.upload(database,own,payload(), 'admin:operator@example.test','admin-draft')
    foreign=await files.upload(database,other,payload(),'customer:2','other-draft')
    for item in (staff,foreign):
        with pytest.raises(HTTPException) as error:await files.customer_download(item['id'],request(),database)
        assert error.value.status_code==404
    with pytest.raises(HTTPException):await customer_support_reply(1,SupportMessageIn(message='stolen',attachment_ids=[foreign['id']]),request('steal'),database)

@pytest.mark.parametrize('name,data',[('script.html',b'<script>'),('fake.png',b'hello'),('data.txt',b'\xff\x00'),('empty.txt',b''),('big.txt',b'x'*(2*1024*1024+1))])
def test_attachment_type_size_and_content_validation(name,data):
    with pytest.raises((HTTPException,ValueError)):files.decode(payload(name,data))

@pytest.mark.asyncio
async def test_unbound_file_can_be_removed_but_sent_file_cannot(database):
    database.add(SupportTicket(id=1,user_id=1,subject='VPN',message='Error'));await database.commit()
    draft=await files.customer_upload(1,payload(),request('draft'),database)
    await files.customer_remove(draft['id'],request(),database)
    assert await database.scalar(select(func.count()).select_from(SupportAttachment))==0
    item=await files.customer_upload(1,payload(),request('sent'),database)
    await customer_support_reply(1,SupportMessageIn(message='File',attachment_ids=[item['id']]),request('message'),database)
    with pytest.raises(HTTPException) as error:await files.customer_remove(item['id'],request(),database)
    assert error.value.status_code==409

@pytest.mark.asyncio
async def test_postgres_attachment_migration_preserves_conversation(database):
    if database.bind.dialect.name!='postgresql':pytest.skip('Migration verified on PostgreSQL')
    from pathlib import Path
    import importlib.util
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    database.add(SupportTicket(id=1,user_id=1,subject='VPN',message='Original'));await database.commit();await database.rollback()
    path=Path(__file__).resolve().parents[1]/'services/backend/alembic/versions/0047_support_attachments.py'
    spec=importlib.util.spec_from_file_location('files_migration',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    async with database.bind.begin() as conn:
        def migrate(connection):
            with Operations.context(MigrationContext.configure(connection)):module.downgrade();module.upgrade()
        await conn.run_sync(migrate)
    assert (await database.get(SupportTicket,1)).message=='Original'
    file=await files.customer_upload(1,payload(),request('after-migration'),database)
    assert file['size']==18

@pytest.mark.asyncio
async def test_drafts_recovery_is_actor_scoped_and_excludes_sent_files(database):
    from types import SimpleNamespace
    database.add_all([SupportTicket(id=1,user_id=1,subject='VPN',message='Error'),SupportTicket(id=2,user_id=2,subject='Other',message='Private')]);await database.commit()
    own=await files.customer_upload(1,payload(),request('recover'),database)
    sent=await files.customer_upload(1,payload(data=b'sent'),request('sent-recovery'),database)
    await customer_support_reply(1,SupportMessageIn(message='Sent',attachment_ids=[sent['id']]),request('sent-message'),database)
    ticket=await database.get(SupportTicket,1)
    staff=await files.upload(database,ticket,payload(), 'admin:one@example.test','staff')
    assert await files.customer_drafts(1,request(),database)==[own]
    assert await files.admin_drafts(1,database,SimpleNamespace(email='one@example.test'))==[staff]
    assert await files.admin_drafts(1,database,SimpleNamespace(email='two@example.test'))==[]
    with pytest.raises(HTTPException) as error:await files.customer_drafts(2,request(),database)
    assert error.value.status_code==404
