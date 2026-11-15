import asyncio
from alembic import context
from app.db import engine
from app.models import Base


def run_migrations(connection):
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True,
                      render_as_batch=connection.dialect.name == 'sqlite')
    with context.begin_transaction():
        context.run_migrations()


async def main():
    async with engine.connect() as connection:
        await connection.run_sync(run_migrations)
    await engine.dispose()


asyncio.run(main())
