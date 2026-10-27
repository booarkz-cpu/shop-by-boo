"""Survey policy, single award, privacy and PostgreSQL capacity races."""
import asyncio
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from types import SimpleNamespace
import pytest
from pydantic import ValidationError
from fastapi import HTTPException,Response
from sqlalchemy import select,func
from sqlalchemy.ext.asyncio import AsyncSession
from app import surveys as polls,main as shop
from app.models import Survey,SurveyResponse,User,FinancialLedger
from test_subscription_commerce import database,request

def payload(**changes):
    data=dict(title='Survey',questions=[{'text':'Choose','options':['A','B']}],starts_at=datetime.now(timezone.utc)-timedelta(hours=1),ends_at=datetime.now(timezone.utc)+timedelta(days=1),reward_amount='5',require_verified_email=True,max_responses=2)
    return polls.SurveyIn(**(data|changes))
async def seed(db,**changes):
    row=Survey(**payload(**changes).model_dump(),state='published',currency=polls.settings.default_currency);db.add(row)
    user=await db.get(User,1);user.email='owner@example.test';user.email_verified_at=datetime.utcnow();await db.commit();return row
async def vote(db,row,choices=(0,)):
    return await polls.submit(row.id,polls.SubmitIn(answers=[{'choices':list(choices)}]),request(),Response(),db)

def test_question_and_budget_validation():
    for changes in ({'reward_amount':'5','require_verified_email':False},{'reward_amount':'10000','max_responses':101},{'starts_at':datetime.utcnow()},{'questions':[{'text':'x','options':['A','a']}]}):
        with pytest.raises(ValidationError):payload(**changes)
    with pytest.raises(ValidationError):polls.AnswerIn(choices=[True])
    questions=[{'kind':'multiple','options':['a','b']},{'kind':'text'}]
    a,digest=polls.canonical(questions,[polls.AnswerIn(choices=[1,0]),polls.AnswerIn(text=' hello ')])
    assert a==[{'choices':[0,1],'text':''},{'choices':[],'text':'hello'}]
    assert digest==polls.canonical(questions,[polls.AnswerIn(choices=[0,1]),polls.AnswerIn(text='hello')])[1]

@pytest.mark.asyncio
async def test_award_once_and_retry_after_close(database):
    row=await seed(database);result=await vote(database,row)
    assert result['submitted'] and Decimal(result['my_reward'])==5
    row.state='closed';await database.commit()
    assert (await vote(database,row))['my_answers']==result['my_answers']
    with pytest.raises(HTTPException) as error:await vote(database,row,[1])
    assert error.value.status_code==409
    assert (await database.get(User,1)).wallet_balance==1005
    assert await database.scalar(select(func.count()).select_from(FinancialLedger))==1
    assert row.response_count==1 and row.statistics=={'0':{'0':1,'answered':1}}

@pytest.mark.asyncio
@pytest.mark.parametrize('invalid',['unverified','expired','draft','cap','currency','choice','subscription'])
async def test_reject_without_credit(database,invalid):
    row=await seed(database);user=await database.get(User,1)
    if invalid=='unverified':user.email_verified_at=None
    elif invalid=='expired':row.ends_at=datetime.utcnow()-timedelta(seconds=1)
    elif invalid=='draft':row.state='draft'
    elif invalid=='cap':row.response_count=2
    elif invalid=='currency':row.currency='USD' if polls.settings.default_currency!='USD' else 'EUR'
    elif invalid=='subscription':row.require_subscription=True;await database.delete(await database.get(__import__('app.models',fromlist=['Subscription']).Subscription,1))
    await database.commit()
    with pytest.raises(HTTPException):await vote(database,row,[2] if invalid=='choice' else [0])
    assert user.wallet_balance==1000 and await database.scalar(select(func.count()).select_from(SurveyResponse))==0

@pytest.mark.asyncio
async def test_anonymization_preserves_totals_and_ledger(database):
    row=await seed(database);await vote(database,row)
    await polls.anonymize(database,1);await database.commit()
    answer=await database.scalar(select(SurveyResponse))
    assert answer.user_id is None and answer.answers==[] and answer.fingerprint=='ANONYMIZED'
    assert row.response_count==1 and row.statistics['0']['0']==1
    assert await database.scalar(select(func.count()).select_from(FinancialLedger))==1

@pytest.mark.asyncio
async def test_visibility_and_frozen_conditions(database):
    row=await seed(database);assert polls.public(row)['statistics'] is None
    await vote(database,row);own=await database.scalar(select(SurveyResponse))
    assert polls.public(row,own)['statistics']
    row.results_mode='hidden';assert polls.public(row,own)['statistics'] is None
    assert polls.public(row,own,admin=True)['statistics']
    with pytest.raises(HTTPException):await polls.edit(row.id,payload(),database,SimpleNamespace(email='admin@example.test'))
    with pytest.raises(HTTPException):await polls.delete_draft(row.id,database,SimpleNamespace(email='admin@example.test'))

@pytest.mark.asyncio
async def test_postgres_last_slot_has_one_award(database,monkeypatch):
    if database.bind.dialect.name!='postgresql':pytest.skip('Row lock race requires PostgreSQL')
    row=await seed(database,max_responses=1);other=await database.get(User,2);other.email='other@example.test';other.email_verified_at=datetime.utcnow();await database.commit()
    async def user(req,db):return await db.get(User,int(req.headers['idempotency-key']))
    monkeypatch.setattr(shop,'user_from_token',user)
    async def participate(uid):
        async with AsyncSession(database.bind,expire_on_commit=False) as db:
            try:return await polls.submit(row.id,polls.SubmitIn(answers=[{'choices':[0]}]),request(str(uid)),Response(),db)
            except HTTPException as exc:await db.rollback();return exc.status_code
    results=await asyncio.gather(participate(1),participate(2))
    assert sum(isinstance(r,dict) for r in results)==1 and 409 in results
    assert await database.scalar(select(func.count()).select_from(SurveyResponse))==1
    assert await database.scalar(select(func.count()).select_from(FinancialLedger))==1

@pytest.mark.asyncio
async def test_postgres_migration_round_trip_and_response_guard(database):
    if database.bind.dialect.name!='postgresql':pytest.skip('PostgreSQL migration is verified in CI')
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    spec=importlib.util.spec_from_file_location('survey_migration',Path('backend/alembic/versions/0051_surveys.py'))
    migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
    async with database.bind.begin() as conn:
        def cycle(connection):
            with Operations.context(MigrationContext.configure(connection)):
                migration.downgrade();migration.upgrade()
        await conn.run_sync(cycle)
    row=await seed(database);await vote(database,row)
    with pytest.raises(RuntimeError,match='Survey responses exist'):
        async with database.bind.begin() as conn:
            def guarded(connection):
                with Operations.context(MigrationContext.configure(connection)):migration.downgrade()
            await conn.run_sync(guarded)

@pytest.mark.asyncio
async def test_postgres_simultaneous_same_user_votes(database):
    if database.bind.dialect.name!='postgresql':pytest.skip('Row lock race requires PostgreSQL')
    row=await seed(database)
    async def participate():
        async with AsyncSession(database.bind,expire_on_commit=False) as db:return await vote(db,row)
    results=await asyncio.gather(participate(),participate())
    assert all(r['submitted'] for r in results)
    await database.refresh(await database.get(User,1))
    assert (await database.get(User,1)).wallet_balance==1005
    assert await database.scalar(select(func.count()).select_from(SurveyResponse))==1
