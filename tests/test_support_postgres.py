"""Exercise conversation row locking and migration against PostgreSQL in CI."""
import asyncio
import importlib.util
import os
from pathlib import Path
import uuid
import sys

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("APP_SECRET", "support-test-secret")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "backend"))

import pytest
import pytest_asyncio
from sqlalchemy import select, text, func
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from app.models import SupportTicket, SupportMessage, SupportAttachment, SupportImportLink
from app.support_threads import append_message


@pytest_asyncio.fixture
async def support_pg():
    url=os.environ.get("AUDIT_TEST_DATABASE_URL")
    if not url:
        pytest.skip("PostgreSQL conversation regression runs in CI")
    schema="support_test_"+uuid.uuid4().hex
    root=create_async_engine(url)
    async with root.begin() as conn:
        await conn.execute(text(f"CREATE SCHEMA {schema}"))
    engine=create_async_engine(url,connect_args={"server_settings":{"search_path":schema,"statement_timeout":"10000"}})
    try:
        async with engine.begin() as conn:
            await conn.run_sync(SupportTicket.__table__.create)
            await conn.run_sync(SupportMessage.__table__.create)
            await conn.run_sync(SupportAttachment.__table__.create)
            await conn.run_sync(SupportImportLink.__table__.create)
        yield engine
    finally:
        await engine.dispose()
        async with root.begin() as conn:
            await conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        await root.dispose()


@pytest.mark.asyncio
async def test_concurrent_support_retries_store_one_message(support_pg):
    async with AsyncSession(support_pg,expire_on_commit=False) as db:
        ticket=SupportTicket(user_id=1,subject="VPN",message="Первый вопрос",status="resolved",admin_reply="Старый ответ")
        db.add(ticket);await db.commit();ticket_id=ticket.id
    async def attempt():
        async with AsyncSession(support_pg,expire_on_commit=False) as db:
            ticket=await db.scalar(select(SupportTicket).where(SupportTicket.id==ticket_id).with_for_update())
            message,created=await append_message(db,ticket,"customer","Продолжение","same-retry")
            await db.commit()
            return message.id,created
    results=await asyncio.gather(attempt(),attempt())
    assert results[0][0]==results[1][0] and sorted(r[1] for r in results)==[False,True]
    async with AsyncSession(support_pg) as db:
        assert await db.scalar(select(func.count()).select_from(SupportMessage))==2
        assert (await db.get(SupportTicket,ticket_id)).status=="open"


@pytest.mark.asyncio
async def test_support_migration_keeps_existing_operator_reply(support_pg):
    async with AsyncSession(support_pg) as db:
        db.add(SupportTicket(user_id=1,subject="VPN",message="Вопрос",admin_reply="Сохранённый ответ"))
        await db.commit()
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path=Path(__file__).resolve().parents[1]/"services/backend/alembic/versions/0043_support_conversations.py"
    spec=importlib.util.spec_from_file_location("conversation_migration",path)
    migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
    delivery_path=Path(__file__).resolve().parents[1]/"services/backend/alembic/versions/0062_support_delivery_identity.py"
    delivery_spec=importlib.util.spec_from_file_location("delivery_migration",delivery_path)
    delivery=importlib.util.module_from_spec(delivery_spec);delivery_spec.loader.exec_module(delivery)
    def migrate(connection):
        SupportAttachment.__table__.drop(connection)
        SupportMessage.__table__.drop(connection)
        connection.execute(text("ALTER TABLE support_tickets DROP COLUMN topology_version"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            delivery.upgrade()
        SupportAttachment.__table__.create(connection)
    async with support_pg.begin() as conn:
        await conn.run_sync(migrate)
    async with AsyncSession(support_pg) as db:
        messages=(await db.execute(select(SupportMessage))).scalars().all()
        assert len(messages)==1 and messages[0].role=="admin" and messages[0].body=="Сохранённый ответ"
        assert (await db.get(SupportTicket,messages[0].ticket_id)).topology_version==0
