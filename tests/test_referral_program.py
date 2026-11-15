"""Referral snapshot accounting, privacy, reversal and PostgreSQL serialization."""
import asyncio
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import main as shop, referral_program as program
from app.models import AppSetting, Payment, ReferralLedger, ReferralLevelReward, ReferralReward, User
from test_subscription_commerce import database, request


@pytest.mark.parametrize('rates', [[], [1]*6, [-1], [101], [90,20], ['NaN'], ['Infinity'], ['1.001']])
def test_invalid_program_rates(rates):
    with pytest.raises(ValidationError):program.ProgramIn(percentages=rates)


async def seed(db):
    owner=await db.get(User,1);owner.referred_by_id=2
    other=await db.get(User,2);other.referred_by_id=3
    db.add_all([User(id=3,referral_code='THIRD',referred_by_id=4),User(id=4,referral_code='FOURTH')])
    db.add(AppSetting(key=program.CONFIG_KEY,value='["10","5","2"]'))
    await db.flush()
    payment=Payment(user_id=1,plan_id=1,provider='wallet',order_id='referral-order',amount=Decimal('100'),status='paid',purpose='subscription',referrer_id_snapshot=2,referral_terms_snapshot=await program.snapshot(db,owner))
    db.add(payment);await db.commit()
    return payment


@pytest.mark.asyncio
async def test_snapshot_preserves_rates_and_chain_and_credits_once(database):
    p=await seed(database)
    assert p.referral_terms_snapshot==[{'user_id':2,'level':1,'percent':'10'},{'user_id':3,'level':2,'percent':'5'},{'user_id':4,'level':3,'percent':'2'}]
    (await database.get(AppSetting,program.CONFIG_KEY)).value='["99"]'
    (await database.get(User,2)).referred_by_id=None
    await database.commit()
    assert len(await program.credit(database,p,1))==3
    await database.commit()
    assert await program.credit(database,p,1)==[]
    await database.commit()
    for uid,amount in [(2,10),(3,5),(4,2)]:
        u=await database.get(User,uid);await database.refresh(u);assert u.referral_balance==amount
    assert await database.scalar(select(func.count()).select_from(ReferralReward))==1
    assert await database.scalar(select(func.count()).select_from(ReferralLevelReward))==2
    assert await database.scalar(select(func.count()).select_from(ReferralLedger))==3


@pytest.mark.asyncio
async def test_full_refund_reverses_all_levels_once_and_never_recredits(database):
    p=await seed(database);await program.credit(database,p,1);await database.commit()
    result=await shop._reverse_referral_reward_for_refund(database,p,'test-admin')
    assert result['amount']=='17.00'
    p.status='refunded';await database.commit()
    assert (await shop._reverse_referral_reward_for_refund(database,p,'test-admin'))['reversed'] is False
    assert await program.credit(database,p,1)==[]
    await database.commit()
    for uid in (2,3,4):
        u=await database.get(User,uid);await database.refresh(u);assert u.referral_balance==0
    assert await database.scalar(select(func.count()).select_from(ReferralLedger))==6


@pytest.mark.asyncio
async def test_legacy_intent_retains_one_level_contract(database):
    p=await seed(database);p.referral_terms_snapshot=None;await database.commit()
    result=await program.credit(database,p,1)
    assert len(result)==1 and result[0]['level']==1
    assert await database.scalar(select(func.count()).select_from(ReferralLevelReward))==0


@pytest.mark.asyncio
async def test_ineligible_ancestor_does_not_shift_level(database):
    await seed(database)
    (await database.get(User,2)).restricted_at=datetime.utcnow();await database.flush()
    terms=await program.snapshot(database,await database.get(User,1))
    assert terms==[{'user_id':3,'level':2,'percent':'5'},{'user_id':4,'level':3,'percent':'2'}]


@pytest.mark.asyncio
async def test_network_privacy_limit_and_owner_scope(database):
    await seed(database)
    data=await program.network(database,4,5,100)
    assert [n['level'] for n in data['nodes']]==[0,1,2,3]
    assert all(set(n)=={'id','parent','level'} and len(n['id'])==24 for n in data['nodes'])
    assert data['truncated'] is False
    limited=await program.network(database,4,5,2)
    assert len(limited['nodes'])==2 and limited['truncated'] is True
    own=await program.network(database,1,5,100)
    assert len(own['nodes'])==1 and own['nodes'][0]['id']!=data['nodes'][-1]['id']


@pytest.mark.asyncio
async def test_cycle_blocks_snapshot(database):
    await seed(database);(await database.get(User,3)).referred_by_id=1;await database.flush()
    with pytest.raises(HTTPException):await program.snapshot(database,await database.get(User,1))


@pytest.mark.asyncio
async def test_refund_clawback_preserves_negative_balance(database):
    p=await seed(database);await program.credit(database,p,1);await database.commit()
    u=await database.get(User,3);u.referral_balance=0;await database.commit()
    await shop._reverse_referral_reward_for_refund(database,p,'test-admin');await database.commit()
    await database.refresh(u);assert u.referral_balance==-5


@pytest.mark.asyncio
async def test_summary_excludes_reversed_rewards(database):
    p=await seed(database);await program.credit(database,p,1);await database.commit()
    async def second(req,db):return await db.get(User,2)
    original=shop.user_from_token;shop.user_from_token=second
    try:
        assert (await shop.my_referral(request(),database))['reward_total']==10
        await shop._reverse_referral_reward_for_refund(database,p,'test-admin');await database.commit()
        assert (await shop.my_referral(request(),database))['reward_total']==0
    finally:shop.user_from_token=original


@pytest.mark.asyncio
async def test_postgres_parallel_fulfillment_credit_once(database):
    if database.bind.dialect.name!='postgresql':pytest.skip('PostgreSQL serialization')
    p=await seed(database);pid=p.id;await database.commit()
    async def credit():
        async with AsyncSession(database.bind,expire_on_commit=False) as db:
            payment=await db.get(Payment,pid)
            await program.credit(db,payment,1);await db.commit()
    await asyncio.gather(credit(),credit())
    assert await database.scalar(select(func.count()).select_from(ReferralLedger))==3


@pytest.mark.asyncio
async def test_refunded_stale_payment_never_creates_reward(database):
    p=await seed(database)
    if database.bind.dialect.name!='postgresql':pytest.skip('Separate PostgreSQL sessions')
    async with AsyncSession(database.bind,expire_on_commit=False) as other:
        row=await other.get(Payment,p.id);row.status='refunded';await other.commit()
    assert p.status=='paid'
    assert await program.credit(database,p,1)==[]
    assert await database.scalar(select(func.count()).select_from(ReferralLedger))==0


@pytest.mark.asyncio
async def test_postgres_migration_cycle_and_financial_downgrade_guard(database):
    if database.bind.dialect.name!='postgresql':pytest.skip('Requires PostgreSQL')
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    spec=importlib.util.spec_from_file_location('referral_migration',Path('services/backend/alembic/versions/0054_referral_levels.py'))
    migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
    await database.commit()
    async with database.bind.begin() as connection:
        def cycle(conn):
            with Operations.context(MigrationContext.configure(conn)):
                migration.downgrade();migration.upgrade()
        await connection.run_sync(cycle)
    p=await seed(database);await program.credit(database,p,1);await database.commit()
    with pytest.raises(RuntimeError,match='financial history'):
        async with database.bind.begin() as connection:
            def guarded(conn):
                with Operations.context(MigrationContext.configure(conn)):migration.downgrade()
            await connection.run_sync(guarded)
    assert await database.scalar(select(func.count()).select_from(ReferralLevelReward))==2


@pytest.mark.asyncio
async def test_refund_dry_run_includes_every_credited_level(database):
    from app.models import RefundRequest
    p=await seed(database);await program.credit(database,p,1)
    r=RefundRequest(payment_id=p.id,user_id=1,amount=p.amount,status='requested')
    database.add(r);await database.commit()
    result=await shop.refund_dry_run(r.id,database,SimpleNamespace(email='admin@example.test'))
    assert result['referral_reward']=='17.00'
    assert result['planned_actions'].count('reverse_referral_reward')==1


@pytest.mark.asyncio
async def test_postgres_stale_referral_binding_cannot_be_overwritten(database):
    if database.bind.dialect.name!='postgresql':pytest.skip('Requires PostgreSQL')
    from app.referrals import bind_referrer
    owner=await database.get(User,1);await database.commit()
    async with AsyncSession(database.bind,expire_on_commit=False) as other:
        row=await other.get(User,1);row.referred_by_id=2;await other.commit()
    assert owner.referred_by_id is None
    with pytest.raises(HTTPException) as error:await bind_referrer(database,owner,'OTHER')
    assert error.value.status_code==409 and owner.referred_by_id==2
@pytest.mark.asyncio
async def test_postgres_binding_does_not_invert_checkout_lock_order(database):
    if database.bind.dialect.name != 'postgresql':pytest.skip('PostgreSQL locking regression')
    import asyncio
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.referrals import bind_referrer
    from app.referral_program import snapshot
    user=await database.scalar(select(User).where(User.id==1).with_for_update())
    entered=asyncio.Event()
    async def bind():
        async with AsyncSession(database.bind,expire_on_commit=False) as other:
            other_user=await other.get(User,1)
            entered.set()
            await bind_referrer(other,other_user,'OTHER')
            await other.commit()
    task=asyncio.create_task(bind())
    try:
        await entered.wait()
        await asyncio.sleep(.05)
        # Binder must be waiting on the buyer row, not holding chain lock while
        # waiting on that row. Otherwise this snapshot deadlocks checkout.
        await asyncio.wait_for(snapshot(database,user),timeout=2)
        await database.commit()
        await asyncio.wait_for(task,timeout=2)
        await database.refresh(user)
        assert user.referred_by_id==2
    finally:
        if not task.done():task.cancel()
