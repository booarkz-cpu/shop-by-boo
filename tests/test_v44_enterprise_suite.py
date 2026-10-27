from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app import main as shop
from app.models import PaymentProviderHealth
from app_contract import missing_paths, revision, tables
from test_subscription_commerce import database  # noqa: F401

ROOT=Path(__file__).resolve().parents[1]
ADMIN=(ROOT/"admin/src/main.tsx").read_text()+(ROOT/"admin/src/sections.ts").read_text()


def test_v44_contract_and_migration_chain():
    assert revision('0022_enterprise_suite').down_revision == '0021_v43_hardening_docs'
    assert {'user_devices', 'campaigns', 'automation_rules', 'monitoring_checks', 'trial_grants'} <= set(tables())
    assert not missing_paths('/api/me/devices', '/api/me/trial', '/api/admin/enterprise/monitoring', '/api/admin/enterprise/campaigns',
                             '/api/admin/enterprise/rules', '/api/admin/enterprise/summary')

def test_v44_admin_surface():
    assert 'Корпоративный контур' in ADMIN
    for label in ['24/7 мониторинг','Campaign Manager','Rules Engine','мультиустройства','Trial']:
        assert label in ADMIN

@pytest.mark.asyncio
async def test_monitoring_targets_are_public_https_only(database):
    admin = SimpleNamespace(email="a@b.c")
    for url in ("http://status.example.com", "https://localhost/health", "https://127.0.0.1/health", "https://10.0.0.5/x", "https://user:pw@x.example/"):
        with pytest.raises(HTTPException) as refused:
            await shop.enterprise_monitoring_create(shop.MonitoringCheckIn(name="api", url=url), database, admin)
        assert refused.value.status_code == 400, url


def test_v44_5_release_tooling_is_consistent():
    (ROOT/"scripts/build-release.sh").read_text()
    (ROOT/"deploy/install-vps.sh").read_text()
    manifest=(ROOT/"release-manifest.template.json").read_text()
    assert 'previous_migration_head": "0021_v43_hardening_docs"' in manifest
    assert 'remnawave_vpn_shop_v1_0_0_realise_deep_audited_fixed_manifest.json' in manifest


@pytest.mark.asyncio
async def test_payment_provider_health_bootstraps_without_admin_page(database):
    assert (await database.execute(select(PaymentProviderHealth))).first() is None
    order = await shop._payment_provider_order(database, None)
    rows = (await database.execute(select(PaymentProviderHealth))).scalars().all()
    assert {r.provider for r in rows} >= set(shop.PAYMENT_AGENTS) and all(r.enabled for r in rows)
    assert order, "a fresh shop can take payments without opening an admin page first"
