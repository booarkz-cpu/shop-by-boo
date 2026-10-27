import importlib.util
from datetime import datetime
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.models import DmarcReport, TerminalSession, HistoryImportJob, CustomerPasskey, SupportTopologyOperation, PartnerWithdrawal, Reseller, CustomerBatchOperation, ContentPage, PromoGroup, RuntimeSettingChange, UserConsent, StarsSubscription
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
        '0079_acquisition',
        '0078_campaign_ab',
        '0077_app_growth',
        '0076_growth',
        '0075_app_config',
        '0074_automation_engine',
        '0073_e2e_v2',
        '0072_traffic_analysis',
        '0071_torrent_detection',
        '0070_node_terminal',
        '0069_mail_domain',
        '0068_network_intel',
        '0067_plugin_runtime',
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
    # 0079 (acquisition source: marketing attribution), 0078 (scheduled campaigns and A/B recipients: marketing statistics) and 0077 (re-collected app
    # analytics and a campaign send log; it refuses only while tax receipts exist) are intentionally unguarded.
    # 0076 is guarded by Telegram Stars subscriptions, family members and gift commissions. 0075 is guarded by stored offer consents. 0074 (automation executions; downgrade restores suspended lifecycles), 0073 (staging run evidence, re-creatable by a new run), 0072/0071 (30-day counters), 0068 (cache)
    # and 0066 (re-registrable push tokens) are intentionally unguarded.
    guarded_names = [roundtrip_names[3], roundtrip_names[4], roundtrip_names[9], roundtrip_names[10], roundtrip_names[14], roundtrip_names[15], *roundtrip_names[19:]]
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
    database.add(UserConsent(user_id=1,document='offer',version='1'))
    database.add(StarsSubscription(order_id='starsub-retain',user_id=1,plan_id=1,stars_amount=50,amount=100))
    database.add(HistoryImportJob(id='retain-history-import',namespace='old-bot',adapter='generic-sqlite-v1',source_sha256='a'*64,actor='test',fingerprint='f'*64,payload_encrypted='',control={},status='cancelled',expires_at=datetime.utcnow()))
    database.add(SupportTopologyOperation(key='key',fingerprint='fingerprint',result={}))
    database.add(CustomerBatchOperation(key='key',fingerprint='fingerprint',result={}))
    database.add(PromoGroup(name='Retain history',segment='manual'))
    database.add(ContentPage(slug='terms',locale='ru',kind='legal',draft={}))
    database.add(TerminalSession(id='retain-terminal', agent_id=1, agent_name='n', admin_id=1, admin_email='a@example.test', reason='audit', status='closed', created_at=datetime.utcnow(), expires_at=datetime.utcnow()))
    database.add(DmarcReport(org_name='Retain', report_id='r-1', domain='shop.example', date_begin=datetime.utcnow(), date_end=datetime.utcnow(), received_at=datetime.utcnow(), source='upload'))
    database.add(RuntimeSettingChange(id='retain-runtime-history',base_version=0,target_version=1,status='applied',keys=['trial_max_days'],payload_encrypted='encrypted',fingerprint='f'*64,actor='test',reason='retain history'))
    await database.commit()
    for name in guarded_names:
        module=migration(name)
        async with database.bind.begin() as conn:
            def guarded(sync, module=module):
                with Operations.context(MigrationContext.configure(sync)):
                    with pytest.raises(RuntimeError):module.downgrade()
            await conn.run_sync(guarded)
