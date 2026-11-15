"""Promotional budgets, atomic awards, privacy and PostgreSQL races."""
import asyncio
import importlib.util
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Response
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import giveaways as prizes, main as shop
from app.models import FinancialLedger, Giveaway, GiveawayEntry, User
from test_subscription_commerce import database, request

ADMIN = SimpleNamespace(email='admin@example.test')


def payload(**changes):
    return prizes.GiveawayIn(**(dict(title='Rewards', kind='wheel',
        starts_at=datetime.now(timezone.utc)-timedelta(hours=1),
        ends_at=datetime.now(timezone.utc)+timedelta(hours=1),
        max_entries=2, prizes=[{'amount':'5','weight':1}]) | changes))


async def seed(db, **changes):
    data = await prizes.create(payload(**changes), db, ADMIN)
    user = await db.get(User, 1)
    user.email = 'owner@example.test'
    user.email_verified_at = datetime.utcnow()
    await db.commit()
    await prizes.publish(data['id'], db, ADMIN)
    return await db.get(Giveaway, data['id'])


async def enter(db, row):
    return await prizes.enter(row.id, request(), Response(), db)


@pytest.mark.parametrize('changes', [
    {'title':' '}, {'starts_at':datetime.utcnow()}, {'max_entries':True},
    {'prizes':[{'amount':'1.001','weight':1}]}, {'prizes':[{'amount':'1','weight':True}]},
    {'prizes':[{'amount':'0','weight':1}]}, {'winners_count':2},
    {'kind':'contest','winners_count':3},
    {'kind':'contest','prizes':[{'amount':'1','weight':2}]},
    {'prizes':[{'amount':'10000'}],'max_entries':101},
    {'ends_at':datetime.now(timezone.utc)-timedelta(days=2)},
])
def test_policy_rejects_invalid_rules(changes):
    with pytest.raises(ValidationError):
        payload(**changes)


@pytest.mark.asyncio
async def test_wheel_lost_response_and_closed_retry_credit_once(database):
    row = await seed(database)
    first = await enter(database, row)
    assert first['my_entry']['outcome'] == 'won'
    await prizes.close(row.id, database, ADMIN)
    assert (await enter(database,row))['my_entry'] == first['my_entry']
    assert (await database.get(User,1)).wallet_balance == 1005
    assert row.entry_count == 1 and row.budget_credited == 5 and row.budget_limit == 10
    assert await database.scalar(select(func.count()).select_from(FinancialLedger)) == 1
    assert await database.scalar(select(func.count()).select_from(GiveawayEntry)) == 1
    from app.customer_workspace_api import wallet_history
    history = await wallet_history(request(), database)
    assert len(history['items']) == 1 and history['items'][0]['kind'] == 'giveaway_reward'


@pytest.mark.asyncio
@pytest.mark.parametrize('ticket,expected', [(0,'lost'), (2,'lost'), (3,'won'), (4,'won')])
async def test_weighted_integer_boundaries(database,monkeypatch,ticket,expected):
    row=await seed(database,prizes=[{'amount':'0','weight':3},{'amount':'5','weight':2}])
    monkeypatch.setattr(prizes.secrets,'randbelow',lambda limit: ticket if limit==5 else pytest.fail('Wrong weight total'))
    result=await enter(database,row)
    assert result['my_entry']['outcome']==expected
    assert (await database.get(User,1)).wallet_balance==(1005 if expected=='won' else 1000)


@pytest.mark.asyncio
@pytest.mark.parametrize('invalid',['unverified','deleted','restricted','subscription','expired','scheduled','draft','full','currency','maintenance'])
async def test_rejected_entry_does_not_change_money(database,monkeypatch,invalid):
    row=await seed(database);user=await database.get(User,1)
    if invalid=='unverified':user.email_verified_at=None
    elif invalid=='deleted':user.deleted_at=datetime.utcnow()
    elif invalid=='restricted':user.restricted_at=datetime.utcnow()
    elif invalid=='subscription':
        row.require_subscription=True
        from app.models import Subscription
        await database.delete(await database.get(Subscription,1))
    elif invalid=='expired':row.ends_at=datetime.utcnow()-timedelta(seconds=1)
    elif invalid=='scheduled':row.starts_at=datetime.utcnow()+timedelta(hours=1)
    elif invalid=='draft':row.state='draft'
    elif invalid=='full':row.entry_count=row.max_entries
    elif invalid=='currency':row.currency='USD' if prizes.settings.default_currency!='USD' else 'EUR'
    elif invalid=='maintenance':
        async def maintenance(db):return True
        monkeypatch.setattr(shop,'maintenance_enabled',maintenance)
    await database.commit()
    with pytest.raises(HTTPException):await enter(database,row)
    assert user.wallet_balance==1000
    assert await database.scalar(select(func.count()).select_from(GiveawayEntry))==0


@pytest.mark.asyncio
async def test_contest_end_draw_once_and_personal_results(database,monkeypatch):
    row=await seed(database,kind='contest',winners_count=2)
    first=await enter(database,row)
    assert first['my_entry']['outcome']=='entered' and (await database.get(User,1)).wallet_balance==1000
    with pytest.raises(HTTPException):await prizes.draw(row.id,database,ADMIN)
    await database.rollback()
    row=await database.get(Giveaway,first['id'])
    row.ends_at=datetime.utcnow()-timedelta(seconds=1);await database.commit()
    await prizes.draw(row.id,database,ADMIN)
    await prizes.draw(row.id,database,ADMIN)
    assert row.state=='drawn' and row.budget_credited==5
    assert (await database.get(User,1)).wallet_balance==1005
    assert await database.scalar(select(func.count()).select_from(FinancialLedger))==1
    result=await prizes.customer_list(request(),Response(),0,database)
    assert result['items'][0]['my_entry']['outcome']=='won'
    assert 'user_id' not in result['items'][0]['my_entry']


@pytest.mark.asyncio
async def test_anonymized_or_restricted_entries_not_awarded(database):
    row=await seed(database,kind='contest');await enter(database,row)
    await prizes.anonymize(database,1)
    row.ends_at=datetime.utcnow()-timedelta(seconds=1);await database.commit()
    await prizes.draw(row.id,database,ADMIN)
    entry=await database.scalar(select(GiveawayEntry))
    assert entry.user_id is None and entry.outcome=='ineligible'
    assert row.entry_count==1 and row.budget_credited==0


@pytest.mark.asyncio
async def test_closed_contest_cannot_draw_and_frozen_campaign_cannot_delete(database):
    row=await seed(database,kind='contest')
    with pytest.raises(HTTPException):await prizes.delete_draft(row.id,database,ADMIN)
    await prizes.close(row.id,database,ADMIN)
    with pytest.raises(HTTPException):await prizes.publish(row.id,database,ADMIN)
    with pytest.raises(HTTPException):await prizes.draw(row.id,database,ADMIN)


@pytest.mark.asyncio
async def test_postgres_last_slot_and_duplicate_race(database,monkeypatch):
    if database.bind.dialect.name!='postgresql':pytest.skip('Requires PostgreSQL row locks')
    row=await seed(database,max_entries=1)
    other=await database.get(User,2);other.email='other@example.test';other.email_verified_at=datetime.utcnow();await database.commit()
    async def owner(req,db):return await db.get(User,int(req.headers['idempotency-key']))
    monkeypatch.setattr(shop,'user_from_token',owner)
    campaign_id=row.id
    async def attempt(uid):
        async with AsyncSession(database.bind,expire_on_commit=False) as db:
            try:return await prizes.enter(campaign_id,request(str(uid)),Response(),db)
            except HTTPException as error:await db.rollback();return error.status_code
    results=await asyncio.gather(attempt(1),attempt(2))
    assert sum(isinstance(r,dict) for r in results)==1 and 409 in results
    winner=next(r for r in results if isinstance(r,dict))
    uid=await database.scalar(select(GiveawayEntry.user_id).where(GiveawayEntry.id==winner['my_entry']['id']))
    again=await asyncio.gather(attempt(uid),attempt(uid))
    assert all(r['my_entry']==winner['my_entry'] for r in again)
    assert await database.scalar(select(func.count()).select_from(FinancialLedger))==1


@pytest.mark.asyncio
async def test_postgres_draw_race_and_migration_guard(database):
    if database.bind.dialect.name!='postgresql':pytest.skip('Requires PostgreSQL')
    spec=importlib.util.spec_from_file_location('giveaway_migration',Path('services/backend/alembic/versions/0052_giveaways.py'))
    migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    async with database.bind.begin() as conn:
        def cycle(connection):
            with Operations.context(MigrationContext.configure(connection)):
                migration.downgrade();migration.upgrade()
        await conn.run_sync(cycle)
    row=await seed(database,kind='contest');await enter(database,row)
    row.ends_at=datetime.utcnow()-timedelta(seconds=1);await database.commit();campaign_id=row.id
    async def draw():
        async with AsyncSession(database.bind,expire_on_commit=False) as db:
            return await prizes.draw(campaign_id,db,ADMIN)
    results=await asyncio.gather(draw(),draw())
    assert all(r['budget_credited']=='5.00' for r in results)
    assert await database.scalar(select(func.count()).select_from(FinancialLedger))==1
    with pytest.raises(RuntimeError,match='Giveaway entries exist'):
        async with database.bind.begin() as conn:
            def guarded(connection):
                with Operations.context(MigrationContext.configure(connection)):migration.downgrade()
            await conn.run_sync(guarded)
