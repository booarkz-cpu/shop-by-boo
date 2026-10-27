"""1.0.7: fulfillment re-reads the customer under the lock; a deleted account gets nothing.
Runs in test_integration_billing_vpn.py («a deleted customer gets no trial») and here for a paid order."""
from datetime import datetime
from decimal import Decimal

import pytest

from app import main as shop
from app.models import Payment, User
from test_integration_billing_vpn import panel  # noqa: F401
from test_subscription_commerce import database  # noqa: F401


@pytest.mark.asyncio
async def test_a_paid_order_of_a_deleted_account_is_not_provisioned(database, panel, monkeypatch):  # noqa: F811
    monkeypatch.setattr(shop, "redis_client", object())
    database.add(Payment(id=99, user_id=1, subscription_id=1, plan_id=1, provider="yookassa", order_id="o-99", amount=Decimal("100"),
                         currency="RUB", status="paid", fulfillment_status="pending", idempotency_key="k-99", duration_days_snapshot=30))
    (await database.get(User, 1)).deleted_at = datetime.utcnow()
    await database.commit()
    with pytest.raises(Exception, match="deleted"):
        await shop.fulfill(99, database)
    assert panel.calls == []
