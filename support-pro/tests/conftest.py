import os
import re
import uuid
import pytest
from pathlib import Path
import pytest_asyncio
import httpx
import pyotp
from fakeredis.aioredis import FakeRedis
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import event,text

os.environ.setdefault('SESSION_SECRET', 'test-session-secret-0123456789-not-for-deployment')
os.environ.setdefault('BOT_TOKEN', '123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi')
os.environ.setdefault('DATABASE_URL', 'sqlite+aiosqlite:///:memory:')
os.environ.setdefault('UPLOAD_DIR', '/tmp/support-test-unused')
os.environ.setdefault('PUBLIC_ORIGIN', 'https://testserver')
from app import main, worker, bot, realtime, storage
from app.models import Base, Operator, Settings
from app.db import ph
from app.sla import DEFAULTS


@pytest_asyncio.fixture
async def env(tmp_path, monkeypatch,request):
    root=None;schema=None
    if getattr(request,'param','sqlite')=='postgres':
        url=os.getenv('AUDIT_TEST_SUPPORT_DATABASE_URL')
        if not url:pytest.skip('PostgreSQL bridge concurrency verified in CI')
        root=create_async_engine(url);schema='support_bridge_'+uuid.uuid4().hex
        async with root.begin() as c:await c.execute(text(f'CREATE SCHEMA {schema}'))
        engine=create_async_engine(url,connect_args={'server_settings':{'search_path':schema,'statement_timeout':'15000'}})
    else:engine = create_async_engine('sqlite+aiosqlite:///' + str(tmp_path / 'test.db'))
    @event.listens_for(engine.sync_engine, 'connect')
    def foreign_keys(connection, _):
        if engine.dialect.name=='sqlite':connection.execute('PRAGMA foreign_keys=ON')
    session = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    redis = FakeRedis(decode_responses=True)
    for module in (main, worker, bot):
        monkeypatch.setattr(module, 'Session', session)
        monkeypatch.setattr(module, 'r', redis)
    monkeypatch.setattr(realtime, 'r', redis)
    monkeypatch.setattr(storage, 'UPLOAD', tmp_path / 'uploads')
    secret = pyotp.random_base32()
    async with session() as s:
        admin = Operator(login='admin', password_hash=ph.hash('correct-password-123'), role='admin', totp_secret=secret)
        s.add(admin)
        s.add(Settings(id=1, data=DEFAULTS))
        await s.commit()
        oid = admin.id
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='https://testserver', follow_redirects=False) as client:
        page = await client.get('/login')
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
        code = pyotp.TOTP(secret).now()  # kept: the replay test sends exactly this code again
        response = await client.post('/login', data={'csrf_token': csrf, 'login': 'admin', 'password': 'correct-password-123', 'code': code})
        assert response.status_code == 303, response.text
        page = await client.get('/')
        csrf = re.search(r'name="csrf-token" content="([^"]+)"', page.text).group(1)
        yield {'session': session, 'client': client, 'csrf': csrf, 'redis': redis, 'oid': oid, 'secret': secret, 'code': code, 'tmp_path': tmp_path}
    await redis.aclose()
    await engine.dispose()
    if root:
        async with root.begin() as c:await c.execute(text(f'DROP SCHEMA {schema} CASCADE'))
        await root.dispose()


async def post(env, path, **data):
    return await env['client'].post(path, data={'csrf_token': env['csrf'], **data})
