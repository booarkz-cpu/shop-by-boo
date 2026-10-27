from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from sqlalchemy import select

import worker
from app import main as shop
from app.models import Job, Payment, RefundRequest
from test_integration_billing_vpn import customer, give_trial, panel  # noqa: F401
from test_subscription_commerce import database  # noqa: F401

ROOT=Path(__file__).parents[1]

def test_v33_version_and_env_example():
    env=(ROOT/'.env.example').read_text()
    assert 'APP_SECRET_PREVIOUS=' in env
    assert 'BACKUP_S3_ENABLED=false' in env
    assert 'REFERRAL_REWARD_PERCENT=' in env

def test_compose_restart_policy_is_service_level():
    d=yaml.safe_load((ROOT/'docker-compose.yml').read_text())
    for name in ('admin','miniapp'):
        assert d['services'][name]['restart']=='unless-stopped'
        assert 'restart' not in d['services'][name]['build']['args']

# Job retries, backoff and the worker's fulfillment run in test_integration_billing_vpn.py.
@pytest.mark.asyncio
async def test_a_job_left_by_a_dead_worker_is_taken_over_after_ten_minutes(customer, panel):  # noqa: F811
    db = customer
    await give_trial(db)
    job = await db.scalar(select(Job))
    job.status, job.worker_id, job.locked_at = "processing", "dead-worker", datetime.utcnow() - timedelta(minutes=5)
    await db.commit()
    assert await worker.run_next_job("live-worker") is False, "a fresh lease is never stolen"
    job.locked_at = datetime.utcnow() - timedelta(minutes=11)
    await db.commit()
    assert await worker.run_next_job("live-worker") is True
    job = await db.scalar(select(Job).execution_options(populate_existing=True))
    assert job.status == "completed" and job.attempts == 1 and len(panel.users) == 1, "the live worker finished it once"


@pytest.mark.asyncio
async def test_refund_status_is_read_from_the_provider(database, monkeypatch):
    database.add(Payment(id=96, user_id=1, subscription_id=1, plan_id=1, provider="yookassa", order_id="o-96", amount=Decimal("100"), currency="RUB",
                         status="paid", idempotency_key="k-96"))
    database.add(RefundRequest(id=12, payment_id=96, user_id=1, amount=Decimal("100"), status="processing", provider_refund_id="rf-96"))
    await database.commit()
    asked = []

    async def pending(self, refund_id):
        asked.append(refund_id)
        return "pending"
    monkeypatch.setattr(shop.YooKassaProvider, "get_refund_status", pending)
    out = await shop.reconcile_refund(12, database, SimpleNamespace(email="a@b.c"))
    assert asked == ["rf-96"] and (await database.get(RefundRequest, 12)).status == "processing"
    assert out == {"ok": True, "status": "processing", "verified": False, "provider_status": "pending"}

    async def declined(self, refund_id):
        return "canceled"
    monkeypatch.setattr(shop.YooKassaProvider, "get_refund_status", declined)
    out = await shop.reconcile_refund(12, database, SimpleNamespace(email="a@b.c"))
    refund = await database.get(RefundRequest, 12)
    assert out["status"] == "failed" and refund.reason.endswith("Provider refund status: canceled")


def test_provider_interface_is_complete():
    from app import payments
    for cls in (payments.YooKassaProvider, payments.PlategaProvider, payments.RollyPayProvider):
        for name in ('create', 'refund', 'get_refund_status', 'verify_succeeded'):
            assert callable(getattr(cls, name, None)), (cls.__name__, name)

def test_v33_release_builder_exists():
    p=ROOT/'scripts/build-release.sh'
    assert p.exists() and p.stat().st_mode & 0o111
    assert 'sha256sum' in p.read_text()
