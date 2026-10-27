"""v44.5.16 privacy and refund integrity, checked by running the code (was: code lines searched in main.py).
Account deletion itself (lock, devices, saved card) runs in test_matrix_privacy.py and test_multiple_subscriptions.py;
deleted accounts get no session in test_behaviour_auth.py and no trial in test_integration_billing_vpn.py."""
from pathlib import Path

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app import main as shop
from app.models import Payment
from app.remnawave import RemnawaveClient
from app_contract import columns, revision
from test_integration_billing_vpn import panel, premium  # noqa: F401
from test_subscription_commerce import database  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]


def test_v44_5_16_migration_adds_deleted_at():
    assert revision("0030_v44_5_16_privacy_and_refund_integrity").down_revision == "0029_v44_5_15_safety_integrity"
    assert "deleted_at" in columns("users")


@pytest.mark.asyncio
async def test_a_refund_during_fulfillment_stops_it_from_completing(database, panel, monkeypatch):  # noqa: F811
    monkeypatch.setattr(shop, "redis_client", object())

    async def quiet(*a, **k):
        return None
    monkeypatch.setattr(shop, "notify_user_telegram", quiet)
    p, remote, _ = await premium(database, panel, "refunded-midway")
    real = RemnawaveClient.extend_idempotent

    async def extend_then_refund(self, *a, **k):
        out = await real(self, *a, **k)
        async with AsyncSession(database.bind) as other:  # an operator refunds while the panel call runs
            await other.execute(update(Payment).where(Payment.id == p.id).values(status="refunded", fulfillment_terminal=True))
            await other.commit()
        return out
    monkeypatch.setattr(RemnawaveClient, "extend_idempotent", extend_then_refund)
    with pytest.raises(RuntimeError, match="reconciliation is required"):
        await shop.fulfill(p.id, database)
    row = await database.get(Payment, p.id, populate_existing=True)
    assert row.status == "refunded" and row.fulfillment_status != "completed", "a refunded payment is never marked fulfilled"


def test_release_tooling_is_44_5_16():
    assert '0030_v44_5_16_privacy_and_refund_integrity' in (ROOT / "scripts/build-release.sh").read_text()
