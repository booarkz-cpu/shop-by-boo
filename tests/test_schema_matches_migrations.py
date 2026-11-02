"""v28.58.0 (BUG-A1, BUG-A2): the database built by the migrations matches the models.

Before 0089 ``alembic`` autogenerate found 110 differences: 26 indexes that repeated a unique
constraint (three on ``payments.order_id``), indexes that only the migrations knew about, indexes
that only the models declared, and ``gift_redemptions.operation_key`` left nullable. Checked on the
PostgreSQL that CI migrates to head before the tests (``AUDIT_TEST_DATABASE_URL``)."""
import os

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.models import Base


def _flat(diff):
    for item in diff:
        if isinstance(item, list):
            yield from _flat(item)
        else:
            yield item


@pytest_asyncio.fixture
async def migrated():
    url = os.environ.get("AUDIT_TEST_DATABASE_URL")
    if not url or not url.startswith("postgresql"):
        pytest.skip("checked on the migrated PostgreSQL in CI")
    engine = create_async_engine(url)
    async with engine.connect() as conn:
        head = await conn.scalar(text("SELECT to_regclass('public.alembic_version') IS NOT NULL"))
        if not head:
            await engine.dispose()
            pytest.skip("the database is not migrated (run alembic upgrade head first)")
        yield conn
    await engine.dispose()


@pytest.mark.asyncio
async def test_models_and_migrations_describe_the_same_schema(migrated):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    def compare(sync_conn):
        return list(_flat(compare_metadata(MigrationContext.configure(sync_conn, opts={"compare_type": False}), Base.metadata)))

    diff = await migrated.run_sync(compare)
    assert diff == [], "\n".join(str(d)[:200] for d in diff[:20])


@pytest.mark.asyncio
async def test_no_index_repeats_another_on_the_same_columns(migrated):
    rows = (await migrated.execute(text("""
        SELECT i.indrelid::regclass::text, string_agg(c.relname, ', ' ORDER BY c.relname)
          FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid
          JOIN pg_namespace ns ON ns.oid = c.relnamespace AND ns.nspname = 'public'
         WHERE i.indpred IS NULL AND i.indexprs IS NULL
         GROUP BY i.indrelid, i.indkey::text HAVING count(*) > 1"""))).all()
    assert rows == []


@pytest.mark.asyncio
async def test_gift_redemption_operation_key_is_required(migrated):
    nullable = await migrated.scalar(text("SELECT is_nullable FROM information_schema.columns "
                                          "WHERE table_schema = 'public' AND table_name = 'gift_redemptions' AND column_name = 'operation_key'"))
    assert nullable == "NO"
