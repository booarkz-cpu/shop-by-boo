from pathlib import Path

import pytest

from app_contract import missing_paths, permissions, tables

ROOT=Path(__file__).parents[1]
COMPOSE=(ROOT/'docker-compose.yml').read_text()

def test_v24_reconciliation_and_refunds():
    assert "refund_requests" in tables()
    assert not missing_paths('/api/admin/payments/reconcile', '/api/admin/payments/{payment_id}/refund-request', '/api/admin/refunds/{refund_id}/mark-refunded')
    assert permissions("POST", "/api/admin/payments/reconcile") == {"payments.reconcile"}

def test_v25_secrets_survive_a_key_rotation(monkeypatch):
    from app import security
    monkeypatch.setattr(security.settings, "app_secret", "old-secret-" + "x" * 32)
    monkeypatch.setattr(security.settings, "app_secret_previous", "")
    stored = security.encrypt_secret("yookassa-card-token")
    monkeypatch.setattr(security.settings, "app_secret", "new-secret-" + "y" * 32)
    with pytest.raises(ValueError):
        security.decrypt_secret(stored)
    monkeypatch.setattr(security.settings, "app_secret_previous", "old-secret-" + "x" * 32)
    assert security.decrypt_secret(stored) == "yookassa-card-token", "the previous key still opens old secrets"
    assert security.decrypt_secret(security.encrypt_secret("new")) == "new"


def test_v25_rotation_tooling():
    assert 'APP_SECRET_PREVIOUS' in (ROOT/'.env.example').read_text()
    assert (ROOT/'scripts/rotate-secrets.sh').exists()
    assert 'no-new-privileges:true' in COMPOSE

def test_v25_worker_lease():
    assert "worker_states" in tables()
    assert not missing_paths('/api/admin/workers')

def test_v26_customer_dashboard_and_support():
    assert not missing_paths('/api/me/dashboard', '/api/me/support/tickets')
    assert "support_tickets" in tables()
    assert 'Реферальная программа' in __import__('frontend_sources').miniapp_sources()

def test_v27_referral_withdrawals():
    assert "withdrawal_requests" in tables()
    assert not missing_paths('/api/me/referral/withdrawals', '/api/admin/referrals/withdrawals/{withdrawal_id}/approve')
    assert permissions("POST", "/api/admin/referrals/withdrawals/{withdrawal_id}/approve") == {"referrals.withdrawals.approve"}

def test_v28_release_and_ci():
    assert "release_records" in tables()
    assert not missing_paths('/api/admin/releases/check')
    assert (ROOT/'.github/workflows/ci.yml').exists()
    assert (ROOT/'scripts/integration-test.sh').exists()
    assert (ROOT/'scripts/rotate-secrets.sh').exists()

def test_v27_provider_refund_adapter():
    from app.payments import PlategaProvider, RollyPayProvider, YooKassaProvider
    assert all(callable(getattr(p, "refund", None)) for p in (YooKassaProvider, PlategaProvider, RollyPayProvider))
    assert not missing_paths('/api/admin/refunds/{refund_id}/execute')

def test_v28_release_is_not_latest_tagged():
    assert 'latest' not in COMPOSE
    assert 'caddy", "validate"' in COMPOSE

def test_v28_image_pinning_tooling():
    assert (ROOT/'scripts/pin-images.sh').exists()
    assert 'RepoDigests' in (ROOT/'scripts/pin-images.sh').read_text()
    assert 'REDIS_IMAGE' in COMPOSE and 'POSTGRES_IMAGE' in COMPOSE and 'CADDY_IMAGE' in COMPOSE
