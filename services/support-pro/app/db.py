import os
from sqlalchemy import URL
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from argon2 import PasswordHasher

URL_VALUE = os.getenv('DATABASE_URL') or URL.create(
    'postgresql+asyncpg', username=os.getenv('POSTGRES_USER', 'support'),
    password=os.getenv('POSTGRES_PASSWORD', ''), host=os.getenv('POSTGRES_HOST', 'db'),
    port=5432, database=os.getenv('POSTGRES_DB', 'support'))
engine = create_async_engine(URL_VALUE, pool_pre_ping=True)
Session = async_sessionmaker(engine, expire_on_commit=False)
ph = PasswordHasher()

# Register transaction and request scoping hooks for API, bot and worker.
from . import events, access  # noqa: E402,F401
