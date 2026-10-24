"""Owner isolation and durable targets across catalog edits and retries."""
from datetime import datetime,timedelta
from decimal import Decimal
from pathlib import Path
import importlib.util
import asyncio
import pytest
from fastapi import HTTPException
from sqlalchemy import select,func,text
from sqlalchemy.ext.asyncio import AsyncSession
from app import subscriptions as profiles
from app import main as shop
from app import gift_orders as gifts
from app.models import User,Subscription,Payment,UserDevice,GiftCode,GiftRedemption,FinancialLedger,Plan,TariffConstructor,TariffConstructorOption
from test_subscription_commerce import database,request

@pytest.mark.asyncio
async def test_independent_targets_survive_selection_and_reject_foreign_owner(database):
    owner=await database.get(User,1)
    secondary=await profiles.reserve_target(database,owner,2,{'new_subscription':True})
    assert not secondary.is_primary
    secondary.name='Телефон';await database.commit()
    payment=Payment(user_id=1,subscription_id=1,plan_id=1,provider='wallet',order_id='bound',amount=10,currency='RUB',status='paid')
    database.add(payment);await database.commit()
    await profiles.select_subscription(secondary.id,request(),database)
    assert (await profiles.owned(database,1)).id==secondary.id
    assert (await profiles.payment_target(database,payment)).id==1
    database.add(Subscription(user_id=2,plan_id=1));await database.commit()
    other=await database.scalar(select(Subscription).where(Subscription.user_id==2))
    with pytest.raises(HTTPException) as error:await profiles.reserve_target(database,owner,1,{'subscription_id':other.id})
    assert error.value.status_code==404
    with pytest.raises(HTTPException):await profiles.rename_subscription(other.id,profiles.RenameIn(name='Чужая'),request(),database)
    assert profiles.remote_username(1,secondary)!=profiles.remote_username(1,await database.get(Subscription,1))
    rows=await profiles.list_subscriptions(request(),database)
    assert len(rows)==2 and sum(x['is_primary'] for x in rows)==1

@pytest.mark.asyncio
async def test_payment_retry_cannot_change_independent_target(database):
    payment=Payment(user_id=1,subscription_id=1,plan_id=1,provider='wallet',order_id='one',amount=10,currency='RUB',new_subscription=True)
    profiles.check_retry(payment,{'new_subscription':True})
    for payload in ({},{'subscription_id':1},{'new_subscription':True,'subscription_id':1}):
        with pytest.raises(HTTPException):profiles.check_retry(payment,payload)

@pytest.mark.asyncio
async def test_active_secondary_prevents_account_deletion(database):
    sub=await database.get(Subscription,1);sub.expires_at=datetime.utcnow()-timedelta(days=1)
    database.add(Subscription(user_id=1,plan_id=2,is_primary=False,lifecycle_status='active',expires_at=datetime.utcnow()+timedelta(days=1)))
    await database.commit()
    with pytest.raises(HTTPException) as error:await shop.privacy_delete(request(),database)
    assert error.value.status_code==409
    assert (await database.get(User,1)).deleted_at is None

@pytest.mark.asyncio
async def test_constructor_gift_freezes_terms_and_debits_once(database):
    database.add(TariffConstructor(id=1,name='Собрать',plan_id=2,base_price=50,remnawave_profile_id='group'))
    database.add_all([TariffConstructorOption(id=1,constructor_id=1,kind='devices',label='3',value=3,price=5),
        TariffConstructorOption(id=2,constructor_id=1,kind='traffic_gb',label='70',value=70,price=10),
        TariffConstructorOption(id=3,constructor_id=1,kind='days',label='15',value=15,price=20)])
    await database.commit()
    payload={'constructor_id':1,'device_option_id':1,'traffic_option_id':2,'days_option_id':3}
    first=await gifts.purchase_gift(payload,request('gift-once'),database)
    code=await database.scalar(select(GiftCode));assert code.purchase_amount==85
    assert code.entitlements_snapshot=={'days':15,'traffic_gb':70,'devices':3,'profile_id':'group','currency':'RUB'}
    constructor=await database.get(TariffConstructor,1);constructor.enabled=False
    option=await database.get(TariffConstructorOption,3);option.value=90;option.price=100
    await database.commit()
    again=await gifts.purchase_gift(payload,request('gift-once'),database)
    assert first['code']==again['code'] and (await database.get(User,1)).wallet_balance==915
    assert await database.scalar(select(func.count()).select_from(FinancialLedger))==1
    with pytest.raises(HTTPException):await gifts.purchase_gift({**payload,'days_option_id':4},request('gift-once'),database)

@pytest.mark.asyncio
async def test_gift_lost_remote_answer_retries_fixed_target_once(database,monkeypatch):
    frozen={'days':7,'traffic_gb':30,'devices':2,'profile_id':None}
    database.add(GiftCode(id=1,code='GIFT_RETRY',plan_id=2,purchaser_user_id=2,entitlements_snapshot=frozen))
    plan=await database.get(Plan,2);plan.duration_days=100;plan.traffic_limit_gb=900;plan.enabled=False
    await database.commit()
    remote={};extensions=[]
    class Remote:
        async def get_user_by_username(self,name):return remote.get(name)
        async def get_user(self,uuid):return {'userTraffic':{'usedTrafficBytes':0}}
        async def create_user(self,name,expiry,*args,**kwargs):
            remote[name]={'id':'gift-remote','subscriptionUrl':'https://example.test/sub'}
            return remote[name]
        async def update_entitlements(self,*args,**kwargs):pass
        async def extend_idempotent(self,uuid,days,before,after):
            extensions.append((uuid,days,before,after))
            if len(extensions)==1:raise RuntimeError('response lost after SET expiry')
        async def get_subscription(self,uuid):return {'subscriptionUrl':'https://example.test/sub'}
    monkeypatch.setattr(shop,'RemnawaveClient',Remote)
    payload=shop.GiftRedeemIn(code='gift_retry',new_subscription=True)
    with pytest.raises(HTTPException) as error:await gifts.redeem_gift(payload,request(),database)
    assert error.value.status_code==503
    redemption=await database.scalar(select(GiftRedemption));sub_id=redemption.subscription_id
    owner=await database.get(User,1)
    with pytest.raises(HTTPException):await profiles.reserve_target(database,owner,1,{'subscription_id':sub_id})
    result=await gifts.redeem_gift(payload,request(),database)
    assert result['subscription_id']==sub_id and extensions[0]==extensions[1]
    sub=await database.get(Subscription,sub_id)
    assert sub.plan_id==2 and sub.traffic_limit_gb_snapshot==30 and sub.device_limit_snapshot==2
    assert sub.unit_price_per_day==0
    assert (await database.get(GiftCode,1)).used_count==1
    again=await gifts.redeem_gift(payload,request(),database)
    assert again['already_redeemed'] and len(extensions)==2
    assert (await database.get(Subscription,1)).remnawave_uuid=='remote-1'

@pytest.mark.asyncio
async def test_postgres_primary_selection_race_serializes(database):
    if database.bind.dialect.name!='postgresql':pytest.skip('PostgreSQL row locks run in CI')
    owner=await database.get(User,1)
    second=await profiles.reserve_target(database,owner,1,{'new_subscription':True});await database.commit()
    async def choose(sub_id):
        async with AsyncSession(database.bind,expire_on_commit=False) as session:
            await profiles.select_subscription(sub_id,request(),session)
    await asyncio.gather(choose(1),choose(second.id))
    assert await database.scalar(select(func.count()).select_from(Subscription).where(Subscription.user_id==1,Subscription.is_primary.is_(True)))==1

@pytest.mark.asyncio
async def test_postgres_subscription_and_gift_migrations_preserve_binding(database):
    if database.bind.dialect.name!='postgresql':pytest.skip('Migration runs on PostgreSQL')
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    def load(name):
        path=Path(__file__).resolve().parents[1]/'backend/alembic/versions'/name
        spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
    m45=load('0045_multiple_subscriptions.py');m46=load('0046_gift_snapshots.py')
    database.add_all([GiftCode(id=1,code='OLD',plan_id=1,purchaser_user_id=1),
        Payment(user_id=1,subscription_id=1,plan_id=1,provider='wallet',order_id='old',amount=100,currency='RUB',purpose='subscription'),
        UserDevice(user_id=1,subscription_id=1,device_key='old-device',platform='android')]);await database.commit();await database.rollback()
    async with database.bind.begin() as conn:
        def migrate(connection):
            with Operations.context(MigrationContext.configure(connection)):
                m46.downgrade();m45.downgrade();m45.upgrade();m46.upgrade()
        await conn.run_sync(migrate)
    database.expire_all()
    assert (await database.get(Subscription,1)).is_primary
    assert await database.scalar(select(Payment.subscription_id))==1
    assert await database.scalar(select(UserDevice.subscription_id))==1
    assert (await database.get(GiftCode,1)).entitlements_snapshot['traffic_gb']==100

@pytest.mark.asyncio
@pytest.mark.parametrize("traffic",[200,None])
async def test_fulfillment_of_two_profiles_never_renews_selected_profile(database,monkeypatch,traffic):
    async def noop(*args,**kwargs):pass
    monkeypatch.setattr(shop,'sandbox_local_vpn',lambda:True)
    monkeypatch.setattr(shop,'redis_client',object())
    monkeypatch.setattr(shop,'notify_user_telegram',noop)
    owner=await database.get(User,1)
    target=await profiles.reserve_target(database,owner,2,{'new_subscription':True});await database.commit()
    second_id=target.id
    first_expiry=(await database.get(Subscription,1)).expires_at
    payment=Payment(user_id=1,subscription_id=second_id,new_subscription=True,plan_id=2,provider='sandbox',
        order_id='two-profile-fulfillment',amount=200,currency='RUB',status='paid',duration_days_snapshot=30,
        traffic_limit_gb_snapshot=traffic,device_limit_snapshot=4)
    database.add(payment);await database.commit()
    await shop.fulfill(payment.id,database)
    await shop.fulfill(payment.id,database)
    second=await database.get(Subscription,second_id)
    assert second.remnawave_uuid==f'sandbox-user-1-sub-{second_id}'
    assert second.expires_at>datetime.utcnow()+timedelta(days=29)
    assert second.traffic_limit_gb_snapshot==traffic
    assert (await database.get(Subscription,1)).expires_at==first_expiry
    assert (await profiles.owned(database,1)).id==1

@pytest.mark.asyncio
async def test_postgres_parallel_gift_purchase_charges_once(database):
    if database.bind.dialect.name!='postgresql':pytest.skip('PostgreSQL locks run in CI')
    async def purchase():
        async with AsyncSession(database.bind,expire_on_commit=False) as session:
            return await gifts.purchase_gift({'plan_id':1},request('parallel-gift'),session)
    a,b=await asyncio.gather(purchase(),purchase())
    assert a['code']==b['code']
    database.expire_all()
    assert (await database.get(User,1)).wallet_balance==900
    assert await database.scalar(select(func.count()).select_from(GiftCode))==1
    assert await database.scalar(select(func.count()).select_from(FinancialLedger))==1

@pytest.mark.asyncio
async def test_pending_gift_stops_privacy_deletion(database):
    sub=await database.get(Subscription,1);sub.lifecycle_status='pending';sub.expires_at=None
    database.add(GiftRedemption(user_id=1,gift_code_id=1,subscription_id=1,operation_key='unresolved',status='failed',remote_user_id='lost-remote'))
    await database.commit()
    with pytest.raises(HTTPException) as error:await shop.privacy_delete(request(),database)
    assert error.value.status_code==409
    assert (await database.get(User,1)).deleted_at is None

@pytest.mark.asyncio
async def test_postgres_device_quotas_and_list_follow_the_selected_profile(database):
    if database.bind.dialect.name!='postgresql':pytest.skip('Advisory device locks run in CI')
    owner=await database.get(User,1)
    target=await profiles.reserve_target(database,owner,2,{'new_subscription':True})
    target.device_limit_snapshot=1;target.unit_price_per_day=0;await database.commit();target_id=target.id
    await shop.register_device(shop.DeviceRegisterIn(device_key='device-primary-0001'),request(),database)
    await shop.register_device(shop.DeviceRegisterIn(device_key='device-primary-0002'),request(),database)
    third=await shop.register_device(shop.DeviceRegisterIn(device_key='device-secondary-0003',subscription_id=target_id),request(),database)
    with pytest.raises(HTTPException) as error:
        await shop.register_device(shop.DeviceRegisterIn(device_key='device-primary-0001',subscription_id=target_id),request(),database)
    assert error.value.status_code==409
    await database.rollback()
    assert len(await shop.my_devices(request(),database))==2
    await profiles.select_subscription(target_id,request(),database)
    rows=await shop.my_devices(request(),database)
    assert [x['id'] for x in rows]==[third['id']]

@pytest.mark.asyncio
async def test_profile_mutations_recheck_anonymized_owner_under_lock(database):
    owner=await database.get(User,1);owner.deleted_at=datetime.utcnow();await database.commit()
    for operation in (profiles.rename_subscription(1,profiles.RenameIn(name='Secret'),request(),database),profiles.select_subscription(1,request(),database)):
        with pytest.raises(HTTPException) as error:await operation
        assert error.value.status_code==409
    assert (await database.get(Subscription,1)).name=='Подписка'

@pytest.mark.asyncio
async def test_postgres_privacy_disables_all_profiles_and_erases_names_and_files(database,monkeypatch):
    if database.bind.dialect.name!='postgresql':pytest.skip('Privacy bulk update uses PostgreSQL')
    from app.models import SupportTicket,SupportAttachment
    old=await database.get(Subscription,1);old.name='Private original';old.expires_at=datetime.utcnow()-timedelta(days=1)
    database.add_all([Subscription(user_id=1,plan_id=2,is_primary=False,name='Private second',lifecycle_status='expired',
        expires_at=datetime.utcnow()-timedelta(days=1),remnawave_uuid='remote-2'),
        SupportTicket(id=1,user_id=1,subject='Issue',message='Text')]);await database.flush()
    database.add(SupportAttachment(ticket_id=1,actor='customer:1',idempotency_key='file',name='private.txt',mime='text/plain',data=b'private',size=7,sha256='0'*64));await database.commit()
    calls=[]
    class Remote:
        async def disable_user(self,uuid):calls.append(uuid)
    monkeypatch.setattr(shop,'RemnawaveClient',Remote)
    result=await shop.privacy_delete(request(),database)
    assert result['anonymized'] and set(calls)=={'remote-1','remote-2'}
    rows=(await database.execute(select(Subscription).where(Subscription.user_id==1))).scalars().all()
    assert all(x.name=='Подписка' and x.remnawave_uuid is None and not x.auto_renew_enabled for x in rows)
    assert await database.scalar(select(func.count()).select_from(SupportAttachment))==0

@pytest.mark.asyncio
async def test_unsettled_purchase_blocks_only_its_profile(database):
    owner=await database.get(User,1)
    payment=Payment(user_id=1,subscription_id=1,plan_id=1,provider='wallet',order_id='unsettled',amount=10,currency='RUB',status='paid',fulfillment_status='pending')
    database.add(payment);await database.commit()
    with pytest.raises(HTTPException) as error:
        await profiles.reserve_target(database,owner,1,{'subscription_id':1})
    assert error.value.status_code==409
    independent=await profiles.reserve_target(database,owner,1,{'new_subscription':True})
    assert independent.id!=1
    payment.fulfillment_status='completed';await database.commit()
    assert (await profiles.reserve_target(database,owner,1,{'subscription_id':1})).id==1
