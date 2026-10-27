"""1.0.5: fulfillment acts only on a confirmed payment (was: code lines searched in main.py).
The shared payment lock and owner-only release run in test_v1_release_deep_audit.py; a refund during
fulfillment in test_v44_5_16_deep_regressions.py."""
from decimal import Decimal

import pytest

from app import main as shop
from app.models import Payment
from test_integration_billing_vpn import panel  # noqa: F401
from test_subscription_commerce import database  # noqa: F401


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["refunded", "refunded_pending_revoke", "creation_unknown", "pending"])
async def test_fulfillment_never_runs_for_an_unconfirmed_payment(database, panel, monkeypatch, status):  # noqa: F811
    monkeypatch.setattr(shop, "redis_client", object())
    database.add(Payment(id=98, user_id=1, subscription_id=1, plan_id=1, provider="yookassa", order_id="o-98", amount=Decimal("100"),
                         currency="RUB", status=status, fulfillment_status="pending", idempotency_key="k-98", duration_days_snapshot=30))
    await database.commit()
    try:
        await shop.fulfill(98, database)
    except Exception:
        pass  # refusing is fine; acting is not
    assert panel.calls == [], f"no panel call for a {status} payment"
    assert (await database.get(Payment, 98, populate_existing=True)).fulfillment_status != "completed"
