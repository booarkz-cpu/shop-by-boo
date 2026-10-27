import pytest
from main_source import main_source
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = main_source()
PAYMENTS = (ROOT / "backend/app/payments.py").read_text()
REQ = (ROOT / "backend/requirements.txt").read_text()
BUILD = (ROOT / "scripts/build-release.sh").read_text()


def _block(start_marker, end_marker):
    start = MAIN.index(start_marker)
    return MAIN[start:MAIN.index(end_marker, start)]


def test_yookassa_webhook_binds_only_after_verified_order_metadata():
    block = _block('@app.post("/api/webhooks/yookassa")', '@app.post("/api/webhooks/platega")')
    assert 'if order_id and order_id != p.order_id: raise HTTPException(403,"Order mismatch")' in block
    verify = 'await YooKassaProvider().verify_succeeded(pid,Decimal(str(p.amount)),p.currency,p.order_id)'
    assert verify in block
    assert block.index(verify) < block.index('await bind_provider_payment_id(db,p,pid)')


def test_all_webhooks_ignore_late_success_for_refunded_payments():
    for provider, marker, end in [
        ('yookassa', '@app.post("/api/webhooks/yookassa")', '@app.post("/api/webhooks/platega")'),
        ('platega', '@app.post("/api/webhooks/platega")', '@app.post("/api/webhooks/rollypay")'),
        ('rollypay', '@app.post("/api/webhooks/rollypay")', '# ---------- Reliability, sessions, analytics, referrals ----------'),
    ]:
        block = _block(marker, end)
        assert 'p.status in {"refunded", "refunded_pending_revoke"}' in block
        assert 'payment_already_refunded' in block


@pytest.mark.asyncio
async def test_provider_verification_checks_the_stored_order_id(monkeypatch):
    from decimal import Decimal

    from app import payments
    answer = {"id": "yk-1", "status": "succeeded", "paid": True, "amount": {"value": "100.00", "currency": "RUB"}, "metadata": {"order_id": "o-1"}}

    from contextlib import asynccontextmanager

    class Client:
        async def get(self, url, auth=None):
            return type("R", (), {"status_code": 200, "json": lambda self: answer})()

    @asynccontextmanager
    async def client(timeout):
        yield Client()
    monkeypatch.setattr(payments, "_public_client", client)
    provider = payments.YooKassaProvider()
    assert await provider.verify_succeeded("yk-1", Decimal("100"), "RUB", "o-1") is True
    assert await provider.verify_succeeded("yk-1", Decimal("100"), "RUB", "o-2") is False, "another order's payment does not count"
    assert await provider.verify_succeeded("yk-1", Decimal("99"), "RUB", "o-1") is False


def test_admin_retry_rejects_refunded_payment():
    block = _block('@app.post("/api/admin/payments/{payment_id}/retry")', '# ---------- V32 Operations / Monitoring / Fraud / Privacy ----------')
    assert 'p.status in {"refunded", "refunded_pending_revoke"}' in block
    assert 'Refunded payment cannot be fulfilled' in block


def test_release_is_44_5_20_and_build_has_yaml_dependency():
    assert re.search(r'^PyYAML==\d', REQ, re.M), 'PyYAML must stay an exact pinned dependency'


# The paid transition of auto-renew takes the payment lock: test_v1_0_9_critical_regressions.py.


def test_reconciliation_passes_immutable_order_to_provider_verification():
    block = _block('async def reconciliation_scheduler():', '@app.get("/api/me/subscription")')
    assert 'verify_succeeded(p.provider_payment_id,Decimal(str(p.amount)),p.currency,p.order_id)' in block
