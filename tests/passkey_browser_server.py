"""Loopback-only, ephemeral browser fixture. Never deploy this test server."""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import sys
import os
import tempfile

test_files=tempfile.TemporaryDirectory(prefix="vpnshop-browser-")
os.environ["MEDIA_DIR"]=str(Path(test_files.name)/"media")

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
import uvicorn
from app import main as shop
# One ephemeral browser runner shares one loopback address. Production limits
# are tested separately; UI scenarios use an isolated general request cap.
shop.RATE_LIMITS = {**shop.RATE_LIMITS, "/api/admin/auth/login": 64}

from app.db import get_db
from app.models import Base, AdminUser, FeatureFlag, User, FraudSignal
from app.security import hash_password

# BROWSER_DATABASE_URL points the fixture at a disposable PostgreSQL database
# (needed for flows that take advisory locks, e.g. customer registration).
engine=create_async_engine(os.environ.get('BROWSER_DATABASE_URL') or 'sqlite+aiosqlite:///'+str(Path(test_files.name)/'browser.sqlite3'))
# Long-polling terminal endpoints open their own short DB sessions instead of get_db.
from sqlalchemy.ext.asyncio import async_sessionmaker
from app import node_terminal
node_terminal.session_factory=async_sessionmaker(engine,expire_on_commit=False)


@asynccontextmanager
async def lifespan(app):
    async with engine.begin() as connection:await connection.run_sync(Base.metadata.create_all)
    if os.environ.get('BROWSER_REDIS_URL'):
        # Optional real Redis for flows that take distributed locks (sandbox purchases).
        from redis.asyncio import Redis
        shop.redis_client=Redis.from_url(os.environ['BROWSER_REDIS_URL'],decode_responses=True)
    async with AsyncSession(engine,expire_on_commit=False) as db:
        db.add(AdminUser(email='browser@example.test',password_hash=hash_password('browser-only-password'),role='admin'))
        db.add(FeatureFlag(key='passkeys',enabled=True))
        db.add(User(email='customer@example.test', email_password_hash=hash_password('customer-browser-password')))
        # One open anti-fraud signal for the decision flow in the admin panel.
        db.add(FraudSignal(user_id=1,kind='payment_velocity',score=55,details='11 payments in 24h'))
        await db.commit()
    yield
    await engine.dispose()
    test_files.cleanup()


async def database():
    async with AsyncSession(engine,expire_on_commit=False) as db:yield db


app=FastAPI(lifespan=lifespan)
app.router.routes.extend(shop.app.router.routes)
app.dependency_overrides[get_db]=database
shop.app.dependency_overrides[get_db]=database
app.add_middleware(shop.SecurityHeadersMiddleware)

# Static panels get the production policy from deploy/Caddyfile so browser tests
# fail if a frontend build ever needs inline scripts or third-party code.
PANEL_CSP=("default-src 'self'; base-uri 'none'; frame-ancestors 'none'; object-src 'none'; img-src 'self' https: data:; "
           "connect-src 'self' https:; script-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'")


@app.middleware("http")
async def panel_content_security_policy(request,call_next):
    response=await call_next(request)
    if not request.url.path.startswith(("/api/","/media/")):
        response.headers["Content-Security-Policy"]=PANEL_CSP
    return response
app.mount('/cabinet',StaticFiles(directory=str(Path(__file__).resolve().parents[1]/'cabinet/dist'),html=True))
app.mount('/',StaticFiles(directory=str(Path(__file__).resolve().parents[1]/'admin/dist'),html=True))

if __name__=='__main__':
    uvicorn.run(app,host='127.0.0.1',port=8777,log_level='warning')
