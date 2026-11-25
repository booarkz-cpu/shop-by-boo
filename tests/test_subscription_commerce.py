"""Financial and entitlement regressions for quoted subscription changes."""
import asyncio
import os
import uuid
import importlib.util
from contextlib import asynccontextmanager
from pathlib import Path
from datetime import datetime,timedelta
from decimal import Decimal
from types import SimpleNamespace
import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select,func,text
from sqlalchemy.ext.asyncio import AsyncSession,async_sessionmaker,create_async_engine
from starlette.requests import Request
from app import db as app_db
from app import main as shop
from app import subscription_commerce as commerce
from app.models import Base,User,Plan,Subscription,TrafficPackage,Payment,EntitlementOperation,EntitlementQuote,FinancialLedger

@asynccontextmanager
async def isolated_payment_background(engine, monkeypatch):
    # Conversion callbacks open a separate session after the purchase commits.
    monkeypatch.setattr(app_db, "SessionLocal", async_sessionmaker(engine, expire_on_commit=False))
    tasks = set()
    monkeypatch.setattr(shop, "_BACKGROUND_TASKS", tasks)
    try:
        yield
    finally:
        await asyncio.gather(*tasks)


@pytest_asyncio.fixture(params=['sqlite','postgres'])
async def database(monkeypatch,request):
    root=None;schema=None
    if request.param=='postgres':
        url=os.environ.get('AUDIT_TEST_DATABASE_URL')
        if not url:pytest.skip('PostgreSQL wallet races and migration run in CI')
        schema='commerce_test_'+uuid.uuid4().hex
        root=create_async_engine(url)
        async with root.begin() as conn:await conn.execute(text(f'CREATE SCHEMA {schema}'))
        engine=create_async_engine(url,connect_args={'server_settings':{'search_path':schema,'statement_timeout':'10000'}})
    else:engine=create_async_engine('sqlite+aiosqlite:///:memory:')
    async with engine.begin() as conn:await conn.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine,expire_on_commit=False) as db:
        db.add_all([User(id=1,username='Owner',referral_code='OWNER',wallet_balance=1000),User(id=2,referral_code='OTHER'),
            Plan(id=1,name='Basic',price=100,duration_days=30,traffic_limit_gb=100,device_limit=2),
            Plan(id=2,name='Plus',price=200,duration_days=30,traffic_limit_gb=200,device_limit=4),
            Subscription(id=1,user_id=1,plan_id=1,expires_at=datetime.utcnow()+timedelta(days=15),lifecycle_status='active',
                remnawave_uuid='remote-1',traffic_limit_gb_snapshot=100,device_limit_snapshot=2,unit_price_per_day=Decimal(100)/30),
            TrafficPackage(id=1,name='50 GB',traffic_gb=50,price=25)])
        await db.commit()
        if engine.dialect.name=='postgresql':
            # Explicit fixture IDs do not advance PostgreSQL serial sequences.
            for table in ('users','plans','subscriptions','traffic_packages'):
                await db.execute(text(f"SELECT setval(pg_get_serial_sequence('{table}','id'), (SELECT max(id) FROM {table}), true)"))
            await db.commit()
        async def owner(request,session):return await session.get(User,1)
        async def lock(*args,**kwargs):return ('test-lock','token')
        async def noop(*args,**kwargs):pass
        async def flag(*args,**kwargs):return True
        async def maintenance(*args):return False
        async def risk(*args):return (0,'allow')
        monkeypatch.setattr(shop,'user_from_token',owner)
        monkeypatch.setattr(shop,'_acquire_user_fulfillment_lock',lock)
        monkeypatch.setattr(shop,'_acquire_payment_side_effect_lock',lock)
        monkeypatch.setattr(shop,'_release_payment_side_effect_lock',noop)
        monkeypatch.setattr(shop,'ensure_required_channel',noop)
        monkeypatch.setattr(shop,'maintenance_enabled',maintenance)
        monkeypatch.setattr(shop,'feature_enabled',flag)
        monkeypatch.setattr(shop,'_risk_score',risk)
        async with isolated_payment_background(engine, monkeypatch):
            yield db
    await engine.dispose()
    if root:
        async with root.begin() as conn:await conn.execute(text(f'DROP SCHEMA {schema} CASCADE'))
        await root.dispose()

def request(key='buy-one'):
    return Request({'type':'http','headers':[(b'idempotency-key',key.encode())]})

async def buy(db,kind='traffic_addon',**kwargs):
    quote=await commerce.quote_change(commerce.QuoteIn(kind=kind,**({'package_id':1} if kind=='traffic_addon' else {'plan_id':2}),**kwargs),request(),db)
    result=await commerce.purchase_change(commerce.PurchaseIn(quote_id=quote['id']),request(),db)
    return quote,result

def test_proration_never_returns_cash_credit_and_rounds_up():
    assert commerce.prorated_amount(Decimal('1'),Decimal('2'),1)==Decimal('.01')
    assert commerce.prorated_amount(Decimal('2'),Decimal('1'),86400)==0
    with pytest.raises(HTTPException):commerce.prorated_amount(Decimal(1),Decimal(2),0)

@pytest.mark.asyncio
async def test_quote_is_owner_scoped_and_preserves_expiry(database):
    quote=await commerce.quote_change(commerce.QuoteIn(kind='subscription_change',plan_id=2),request(),database)
    assert quote['before']['expires_at']==quote['after']['expires_at']
    assert Decimal(quote['amount'])==Decimal('50.00')
    assert 'profile' not in quote['after']
    with pytest.raises(HTTPException) as error:
        await commerce.quote_change(commerce.QuoteIn(kind='traffic_addon',package_id=1,subscription_id=99),request(),database)
    assert error.value.status_code==404

@pytest.mark.asyncio
async def test_purchase_retries_after_quote_expiry_do_not_debit_twice(database):
    quote,result=await buy(database)
    saved=await database.get(EntitlementQuote,quote['id']);saved.expires_at=datetime.utcnow()-timedelta(days=1);await database.commit()
    for key in ('buy-one','different-key'):
        again=await commerce.purchase_change(commerce.PurchaseIn(quote_id=quote['id']),request(key),database)
        assert again['id']==result['id']
    assert (await database.get(User,1)).wallet_balance==975
    assert await database.scalar(select(func.count()).select_from(FinancialLedger))==1
    assert await database.scalar(select(func.count()).select_from(EntitlementOperation))==1

@pytest.mark.asyncio
async def test_expired_and_changed_quotes_do_not_charge(database):
    quote=await commerce.quote_change(commerce.QuoteIn(kind='traffic_addon',package_id=1),request(),database)
    saved=await database.get(EntitlementQuote,quote['id']);saved.expires_at=datetime.utcnow()-timedelta(seconds=1);await database.commit()
    with pytest.raises(HTTPException):await commerce.purchase_change(commerce.PurchaseIn(quote_id=quote['id']),request(),database)
    quote=await commerce.quote_change(commerce.QuoteIn(kind='traffic_addon',package_id=1),request(),database)
    sub=await database.get(Subscription,1);sub.traffic_limit_gb_snapshot=120;await database.commit()
    with pytest.raises(HTTPException):await commerce.purchase_change(commerce.PurchaseIn(quote_id=quote['id']),request(),database)
    assert (await database.get(User,1)).wallet_balance==1000

@pytest.mark.asyncio
async def test_uncertain_remote_result_replays_absolute_limits_once(database,monkeypatch):
    quote,result=await buy(database)
    calls=[]
    async def update(self,uuid,traffic,profile):
        calls.append((uuid,traffic,profile))
        if len(calls)==1:raise RuntimeError('remote response lost')
    monkeypatch.setattr(commerce.RemnawaveClient,'update_entitlements',update)
    with pytest.raises(RuntimeError):await shop.fulfill(result['id'],database)
    assert (await database.get(Subscription,1)).traffic_limit_gb_snapshot==100
    await shop.fulfill(result['id'],database)
    await shop.fulfill(result['id'],database)
    assert [c[1] for c in calls]==[150,150]
    assert (await database.get(Subscription,1)).traffic_limit_gb_snapshot==150
    assert (await database.get(User,1)).wallet_balance==975
    assert (await database.get(Payment,result['id'])).fulfillment_status=='completed'

@pytest.mark.asyncio
async def test_pending_operation_blocks_second_charge(database):
    await buy(database)
    quote=await commerce.quote_change(commerce.QuoteIn(kind='traffic_addon',package_id=1),request(),database)
    with pytest.raises(HTTPException) as error:
        await commerce.purchase_change(commerce.PurchaseIn(quote_id=quote['id']),request('buy-two'),database)
    assert error.value.status_code==409
    assert (await database.get(User,1)).wallet_balance==975

@pytest.mark.asyncio
async def test_queued_refund_is_once_and_never_calls_remote(database,monkeypatch):
    async def forbidden(*args):raise AssertionError('queued order never wrote remote')
    monkeypatch.setattr(commerce.RemnawaveClient,'update_entitlements',forbidden)
    _,payment=await buy(database)
    op=await database.scalar(select(EntitlementOperation))
    admin=SimpleNamespace(email='admin@example.com')
    assert not (await commerce.refund_change(op.id,database,admin))['already_refunded']
    assert (await commerce.refund_change(op.id,database,admin))['already_refunded']
    assert (await database.get(User,1)).wallet_balance==1000
    assert await database.scalar(select(func.count()).select_from(FinancialLedger))==2
    assert (await database.get(Payment,payment['id'])).status=='refunded'

@pytest.mark.asyncio
async def test_applied_refund_waits_for_remote_and_preserves_balance_on_failure(database,monkeypatch):
    calls=[]
    async def update(self,uuid,traffic,profile):
        calls.append(traffic)
        if traffic==100 and calls.count(100)==1:raise RuntimeError('rollback response lost')
    async def remote(self,uuid):return {'response':{'trafficUsedBytes':1}}
    monkeypatch.setattr(commerce.RemnawaveClient,'update_entitlements',update)
    monkeypatch.setattr(commerce.RemnawaveClient,'get_user',remote)
    _,payment=await buy(database);await shop.fulfill(payment['id'],database)
    op=await database.scalar(select(EntitlementOperation));admin=SimpleNamespace(email='admin@example.com')
    with pytest.raises(RuntimeError):await commerce.refund_change(op.id,database,admin)
    assert (await database.get(User,1)).wallet_balance==975
    assert (await database.get(EntitlementOperation,op.id)).status=='refund_pending'
    await commerce.refund_change(op.id,database,admin)
    assert calls==[150,100,100]
    assert (await database.get(User,1)).wallet_balance==1000
    assert (await database.get(Subscription,1)).traffic_limit_gb_snapshot==100

@pytest.mark.asyncio
async def test_later_entitlements_prevent_automatic_refund(database):
    await buy(database)
    sub=await database.get(Subscription,1);sub.expires_at+=timedelta(days=1);await database.commit()
    op=await database.scalar(select(EntitlementOperation))
    with pytest.raises(HTTPException) as error:await commerce.refund_change(op.id,database,SimpleNamespace(email='admin@example.com'))
    assert error.value.status_code==409
    assert (await database.get(User,1)).wallet_balance==975


@pytest.mark.asyncio
async def test_postgres_concurrent_quote_consumption_charges_once(database):
    if database.bind.dialect.name!='postgresql':pytest.skip('SQLite has no wallet row lock')
    quote=await commerce.quote_change(commerce.QuoteIn(kind='traffic_addon',package_id=1),request(),database)
    async def attempt(key):
        async with AsyncSession(database.bind,expire_on_commit=False) as session:
            return await commerce.purchase_change(commerce.PurchaseIn(quote_id=quote['id']),request(key),session)
    results=await asyncio.gather(attempt('parallel-one'),attempt('parallel-two'))
    assert results[0]['id']==results[1]['id']
    await database.refresh(await database.get(User,1))
    assert (await database.get(User,1)).wallet_balance==975
    assert await database.scalar(select(func.count()).select_from(EntitlementOperation))==1


@pytest.mark.asyncio
async def test_postgres_commerce_migration_round_trip(database):
    if database.bind.dialect.name!='postgresql':pytest.skip('Migration verified on PostgreSQL')
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path=Path(__file__).resolve().parents[1]/'services/backend/alembic/versions/0044_subscription_commerce.py'
    spec=importlib.util.spec_from_file_location('commerce_migration',path)
    migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
    await database.rollback()
    async with database.bind.begin() as conn:
        def migrate(connection):
            with Operations.context(MigrationContext.configure(connection)):
                migration.downgrade();migration.upgrade()
        await conn.run_sync(migrate)
    assert (await database.get(Subscription,1)).traffic_limit_gb_snapshot==100
    assert await database.scalar(select(func.count()).select_from(TrafficPackage))==0
    assert await database.scalar(select(func.count()).select_from(EntitlementOperation))==0

@pytest.mark.asyncio
async def test_stolen_quote_and_conflicting_key_are_rejected(database):
    quote,original=await buy(database)
    other=await commerce.quote_change(commerce.QuoteIn(kind='traffic_addon',package_id=1),request(),database)
    with pytest.raises(HTTPException) as error:
        await commerce.purchase_change(commerce.PurchaseIn(quote_id=other['id']),request(),database)
    assert error.value.status_code==409
    saved=await database.get(EntitlementQuote,other['id']);saved.user_id=2;await database.commit()
    with pytest.raises(HTTPException) as error:
        await commerce.purchase_change(commerce.PurchaseIn(quote_id=other['id']),request('stolen-key'),database)
    assert error.value.status_code==404
    assert (await database.get(User,1)).wallet_balance==975

@pytest.mark.asyncio
async def test_insufficient_wallet_balance_is_not_debited(database):
    user=await database.get(User,1);user.wallet_balance=1;await database.commit()
    quote=await commerce.quote_change(commerce.QuoteIn(kind='traffic_addon',package_id=1),request(),database)
    with pytest.raises(HTTPException) as error:
        await commerce.purchase_change(commerce.PurchaseIn(quote_id=quote['id']),request(),database)
    assert error.value.status_code==402
    assert await database.scalar(select(func.count()).select_from(Payment))==0
    assert user.wallet_balance==1

@pytest.mark.asyncio
async def test_used_traffic_blocks_refund_with_remnawave_v3_nested_schema(database,monkeypatch):
    async def update(*args):pass
    async def remote(*args):return {'response':{'userTraffic':{'usedTrafficBytes':101*1024**3}}}
    monkeypatch.setattr(commerce.RemnawaveClient,'update_entitlements',update)
    monkeypatch.setattr(commerce.RemnawaveClient,'get_user',remote)
    _,payment=await buy(database);await shop.fulfill(payment['id'],database)
    op=await database.scalar(select(EntitlementOperation))
    with pytest.raises(HTTPException) as error:
        await commerce.refund_change(op.id,database,SimpleNamespace(email='admin@example.com'))
    assert error.value.status_code==409
    assert (await database.get(User,1)).wallet_balance==975
    assert (await database.get(Subscription,1)).traffic_limit_gb_snapshot==150

@pytest.mark.asyncio
async def test_postgres_parallel_different_quotes_cannot_reserve_twice(database):
    if database.bind.dialect.name!='postgresql':pytest.skip('SQLite has no wallet row lock')
    quotes=[await commerce.quote_change(commerce.QuoteIn(kind='traffic_addon',package_id=1),request(),database) for _ in range(2)]
    async def attempt(index):
        async with AsyncSession(database.bind,expire_on_commit=False) as session:
            return await commerce.purchase_change(commerce.PurchaseIn(quote_id=quotes[index]['id']),request(f'different-{index}'),session)
    results=await asyncio.gather(attempt(0),attempt(1),return_exceptions=True)
    assert len([r for r in results if isinstance(r,dict)])==1
    errors=[r for r in results if isinstance(r,HTTPException)]
    assert len(errors)==1 and errors[0].status_code==409
    await database.refresh(await database.get(User,1))
    assert (await database.get(User,1)).wallet_balance==975
    assert await database.scalar(select(func.count()).select_from(FinancialLedger))==1
