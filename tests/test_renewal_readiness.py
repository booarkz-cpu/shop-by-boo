from datetime import datetime
from decimal import Decimal
import pytest
from sqlalchemy import select
from app import main as shop,subscriptions as profiles,subscription_commerce as commerce
from app.models import User,Subscription,Payment,EntitlementOperation,TariffConstructor
from test_subscription_commerce import database,request,buy

@pytest.mark.asyncio
async def test_late_confirmation_waits_without_attempt_then_fulfills(database,monkeypatch):
    _,change=await buy(database)
    sub=await database.get(Subscription,1);before=commerce.entitlement_state(sub)
    payment=Payment(user_id=1,subscription_id=1,plan_id=1,provider='sandbox',order_id='late-confirmation',amount=100,
        status='paid',duration_days_snapshot=30,traffic_limit_gb_snapshot=100,device_limit_snapshot=2)
    database.add(payment);await database.commit()
    monkeypatch.setattr(shop,'redis_client',object());monkeypatch.setattr(shop,'sandbox_local_vpn',lambda:True)
    async def noop(*args,**kwargs):pass
    monkeypatch.setattr(shop,'notify_user_telegram',noop)
    for _ in range(10):await shop.fulfill(payment.id,database)
    assert payment.fulfillment_attempts==0 and not payment.fulfillment_terminal and payment.next_retry_at
    assert commerce.entitlement_state(sub)==before
    operation=await database.scalar(select(EntitlementOperation).where(EntitlementOperation.payment_id==change['id']))
    operation.status='applied';await database.commit()
    await shop.fulfill(payment.id,database)
    assert payment.fulfillment_status=='completed' and payment.fulfillment_attempts==1

@pytest.mark.asyncio
async def test_constructor_renewal_recovers_grant_without_using_plan_defaults(database):
    plan=await database.get(__import__('app.models',fromlist=['Plan']).Plan,1)
    database.add(TariffConstructor(plan_id=1,name='Custom',base_price=10))
    sub=await database.get(Subscription,1);sub.unit_price_per_day=Decimal(300)/10
    database.add(Payment(user_id=1,subscription_id=1,plan_id=1,provider='wallet',order_id='grant',amount=300,original_amount=350,
        status='paid',purpose='subscription',fulfillment_status='completed',duration_days_snapshot=10,
        traffic_limit_gb_snapshot=500,device_limit_snapshot=8,remnawave_profile_id_snapshot='custom'))
    await database.commit()
    terms=await profiles.renewal_terms(database,sub,plan)
    assert terms=={'amount':'350.00','days':10,'traffic_gb':500,'devices':8,'profile_id':'custom','currency':'RUB'}
    sub.unit_price_per_day=Decimal(50);await database.commit()
    assert await profiles.renewal_terms(database,sub,plan) is None
    sub.renewal_terms={'amount':'480','days':14,'traffic_gb':800,'devices':9,'profile_id':'new'}
    await database.commit()
    assert (await profiles.renewal_terms(database,sub,plan))['days']==14

@pytest.mark.asyncio
async def test_recovered_gift_uuid_checks_used_traffic_before_overwrite(database,monkeypatch):
    from app import gift_orders as gifts
    from app.models import GiftCode,GiftRedemption
    from fastapi import HTTPException
    sub=await database.get(Subscription,1);sub.remnawave_uuid=None;sub.traffic_limit_gb_snapshot=None
    database.add(GiftCode(id=1,code='RECOVER_LIMIT',plan_id=1,purchaser_user_id=2,
        entitlements_snapshot={'days':7,'traffic_gb':30,'devices':2,'profile_id':None}))
    database.add(GiftRedemption(gift_code_id=1,user_id=1,subscription_id=1,operation_key='gift:1:1',status='failed',
        remote_user_id='uncertain-created',before_snapshot=commerce.entitlement_state(sub)))
    await database.commit();seen=[]
    class Remote:
        async def get_user(self,uuid):seen.append(uuid);return {'userTraffic':{'usedTrafficBytes':31*1024**3}}
        async def update_entitlements(self,*args,**kwargs):raise AssertionError('must not overwrite consumed quota')
    monkeypatch.setattr(shop,'RemnawaveClient',Remote)
    with pytest.raises(HTTPException) as error:
        await gifts.redeem_gift(shop.GiftRedeemIn(code='RECOVER_LIMIT'),request(),database)
    assert error.value.status_code==409 and seen==['uncertain-created']
    assert (await database.get(GiftRedemption,1)).status=='failed'

@pytest.mark.asyncio
async def test_postgres_new_migrations_preserve_existing_users_and_protect_snapshots(database):
    if database.bind.dialect.name!='postgresql':pytest.skip('Requires PostgreSQL migration DDL')
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    modules=[]
    for file in ('0049_renewal_terms.py','0050_account_actions.py'):
        spec=importlib.util.spec_from_file_location(file[:-3],Path('backend/alembic/versions')/file)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);modules.append(module)
    conn=await database.connection()
    def cycle(sync):
        with Operations.context(MigrationContext.configure(sync)):
            modules[1].downgrade();modules[0].downgrade();modules[0].upgrade();modules[1].upgrade()
    await conn.run_sync(cycle);await database.commit()
    user=await database.get(User,1);await database.refresh(user)
    assert user.username=='Owner' and user.email_verified_at is None
    sub=await database.get(Subscription,1);sub.renewal_terms={'amount':'200','days':30};await database.commit()
    conn=await database.connection()
    def reject(sync):
        with Operations.context(MigrationContext.configure(sync)):modules[0].downgrade()
    with pytest.raises(RuntimeError):await conn.run_sync(reject)
    await database.refresh(sub)
    assert sub.renewal_terms=={'amount':'200','days':30}
