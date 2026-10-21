import importlib.util
from datetime import datetime
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.models import HistoryImportJob, CustomerPasskey, SupportTopologyOperation, PartnerWithdrawal, Reseller, CustomerBatchOperation, ContentPage, PromoGroup, RuntimeSettingChange
from test_subscription_commerce import database


def migration(name):
    path=Path('backend/alembic/versions')/(name+'.py')
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_postgres_new_migrations_roundtrip_and_history_guards(database):
    if database.bind.dialect.name!='postgresql':pytest.skip('PostgreSQL DDL')
    roundtrip_names = [
        '0066_push_notifications',
        '0065_history_import',
        '0064_runtime_settings',
        '0063_account_merge',
        '0062_support_delivery_identity',
        '0061_menu_hierarchy',
        '0060_promo_audiences',
        '0059_content_publishing',
        '0058_customer_operations',
        '0057_partner_commissions',
        '0056_support_topology',
        '0055_customer_passkeys',
    ]
    # 0066 holds only re-registrable push tokens, so its downgrade is intentionally unguarded.
    guarded_names = [roundtrip_names[1], roundtrip_names[2], *roundtrip_names[6:]]
    async with database.bind.begin() as conn:
        def cycle(sync):
            with Operations.context(MigrationContext.configure(sync)):
                for name in roundtrip_names:
                    migration(name).downgrade()
                for name in reversed(roundtrip_names):
                    migration(name).upgrade()
        await conn.run_sync(cycle)
    partner=Reseller(name='Test',slug='test',api_key_hash='hash',owner_user_id=1)
    database.add(partner);await database.flush()
    database.add(PartnerWithdrawal(reseller_id=partner.id,amount=1,currency='RUB',destination='Test',idempotency_key='one'))
    database.add(CustomerPasskey(user_id=1,credential_id='credential',public_key='key',name='Test'))
    database.add(HistoryImportJob(id='retain-history-import',namespace='old-bot',adapter='generic-sqlite-v1',source_sha256='a'*64,actor='test',fingerprint='f'*64,payload_encrypted='',control={},status='cancelled',expires_at=datetime.utcnow()))
    database.add(SupportTopologyOperation(key='key',fingerprint='fingerprint',result={}))
    database.add(CustomerBatchOperation(key='key',fingerprint='fingerprint',result={}))
    database.add(PromoGroup(name='Retain history',segment='manual'))
    database.add(ContentPage(slug='terms',locale='ru',kind='legal',draft={}))
    database.add(RuntimeSettingChange(id='retain-runtime-history',base_version=0,target_version=1,status='applied',keys=['trial_max_days'],payload_encrypted='encrypted',fingerprint='f'*64,actor='test',reason='retain history'))
    await database.commit()
    for name in guarded_names:
        module=migration(name)
        async with database.bind.begin() as conn:
            def guarded(sync):
                with Operations.context(MigrationContext.configure(sync)):
                    with pytest.raises(RuntimeError):module.downgrade()
            await conn.run_sync(guarded)
