"""v45.5 refund and renewal regressions, checked by running the code (was: code lines searched in main.py and worker.py).
Lock order of refund paths: test_v2_0_0_product_and_critical_audit.py; review retries: test_v44_5_8_deep_regressions.py;
renewal snapshots: test_v44_5_9_deep_regressions.py; refund idempotency keys: test_v30_final_hardening.py."""
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app import main as shop
from app.models import Payment, RefundRequest, Subscription
from test_integration_billing_vpn import panel, premium  # noqa: F401
from test_subscription_commerce import database  # noqa: F401


@pytest.mark.asyncio
async def test_a_payment_gets_one_refund_request(database):
    database.add(Payment(id=90, user_id=1, plan_id=1, provider="yookassa", order_id="o-90", amount=Decimal("100"), currency="RUB",
                         status="paid", idempotency_key="k-90"))
    database.add_all([RefundRequest(payment_id=90, user_id=1, amount=Decimal("100")), RefundRequest(payment_id=90, user_id=1, amount=Decimal("100"))])
    with pytest.raises(IntegrityError):
        await database.commit()


@pytest.mark.asyncio
async def test_a_repurchase_switches_a_disabled_panel_user_back_on(database, panel, monkeypatch):  # noqa: F811
    monkeypatch.setattr(shop, "redis_client", object())

    async def quiet(*a, **k):
        return None
    monkeypatch.setattr(shop, "notify_user_telegram", quiet)
    p, remote, _ = await premium(database, panel, "rebuy-1")
    panel.users[remote]["status"] = "DISABLED"  # the old subscription had ended and was switched off
    await shop.fulfill(p.id, database)
    assert panel.users[remote]["status"] == "ACTIVE" and panel.count("POST", "/actions/enable") == 1
    assert (await database.get(Subscription, 1)).lifecycle_status == "active"


@pytest.mark.asyncio
async def test_public_checkout_lists_only_the_providers_routing_would_use(database, monkeypatch):
    from app.models import PaymentProviderHealth
    await shop._payment_provider_order(database, None)
    await database.commit()
    yookassa = await database.scalar(select(PaymentProviderHealth).where(PaymentProviderHealth.provider == "yookassa"))
    yookassa.enabled = False
    await database.commit()
    order = await shop._payment_provider_order(database, None)
    assert "yookassa" not in order, "a provider switched off is not offered"
