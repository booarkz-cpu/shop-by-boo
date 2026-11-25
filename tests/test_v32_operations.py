from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
import pytest

def read(p): return p.read_text()

def test_current_manifest_and_migration():
    m=read(ROOT/'release-manifest.template.json')
    from app_contract import revision, tables
    assert '43.1.0-production' in m and '0017_v39_staging_isolation' in m
    assert {'jobs', 'fraud_signals', 'payout_transactions'} <= set(tables())
    assert revision('0017_v39_staging_isolation') is not None

@pytest.mark.asyncio
async def test_current_ops_endpoints_and_rbac():
    from fastapi import HTTPException

    from app import main as shop
    from app.security import PERMISSIONS
    from app_contract import missing_paths
    assert not missing_paths('/api/admin/monitoring', '/api/admin/jobs', '/api/admin/fraud', '/api/admin/payouts', '/api/me/privacy/export',
                             '/api/me/privacy/account', '/api/me/traffic', '/api/admin/refunds/{refund_id}/reconcile')
    assert {'referrals.withdrawals.read', 'referrals.withdrawals.approve', 'referrals.withdrawals.pay', 'referrals.reconcile'} <= PERMISSIONS['admin']
    with pytest.raises(HTTPException) as gone:
        await shop.mark_refunded(1, None)
    assert gone.value.status_code == 410, "a refund is executed or reconciled with the provider, never just marked"

def test_build_stage_images_are_pinnable():
    compose=read(ROOT/'docker-compose.yml')
    for x in ['PYTHON_BASE_IMAGE','NODE_BASE_IMAGE','NGINX_BASE_IMAGE']:
        assert x in compose
    python_image = 'python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928'
    backend = read(ROOT/'services/backend/Dockerfile')
    bot = read(ROOT/'services/backend/Dockerfile.bot')
    assert 'ARG PYTHON_BASE_IMAGE' in backend
    assert backend.count(python_image) == 1
    assert bot.count(python_image) == 1
    assert compose.count(python_image) == 4
    for script in ('install-vps.sh', 'resume-vps-after-pin.sh'):
        deployment = read(ROOT/'infrastructure/deployment'/script)
        assert 'bash scripts/pin-images.sh' in deployment
        assert 'resolve_build' not in deployment
    node_image = 'node:26.13.1-alpine@sha256:6bd9ab43c0ec0190ca7b2d193906cb8b7edf6e7f4afa43ddeccd6452710bffb5'
    assert compose.count(node_image) == 3
    for dockerfile in (
        'apps/lucy-admin/web/Dockerfile',
        'apps/user-cabinet/Dockerfile',
        'apps/telegram-mini-app/Dockerfile',
    ):
        text = read(ROOT/dockerfile)
        assert text.count(node_image) == 1
        assert 'ARG NODE_BASE_IMAGE' in text
        assert 'ARG NGINX_BASE_IMAGE' in text
    dependencies = read(ROOT/'docs/EXTERNAL_DEPENDENCIES.md')
    assert f'| Сборка трёх веб-приложений | Node.js 26.13.1 | \`{node_image.rsplit("@sha256:", 1)[1]}\` |' in dependencies
