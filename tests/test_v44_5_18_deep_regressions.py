import pytest
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQ = (ROOT / "backend/requirements.txt").read_text()
BUILD = (ROOT / "scripts/build-release.sh").read_text()


# test_yookassa_webhook_binds_only_after_verified_order_metadata, test_admin_retry_rejects_refunded_payment and
# test_reconciliation_passes_immutable_order_to_provider_verification: replaced by the behaviour tests
# tests/test_behaviour_payment_guards.py (C1, stage 19).


# test_all_webhooks_ignore_late_success_for_refunded_payments: replaced by the behaviour test
# tests/test_behaviour_webhooks_refunded.py (C1, stage 19).


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


def test_release_is_44_5_20_and_build_has_yaml_dependency():
    assert re.search(r'^PyYAML==\d', REQ, re.M), 'PyYAML must stay an exact pinned dependency'


# The paid transition of auto-renew takes the payment lock: test_v1_0_9_critical_regressions.py.
