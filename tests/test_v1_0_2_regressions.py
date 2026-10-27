from pathlib import Path

import pytest

from test_integration_billing_vpn import panel  # noqa: F401
from test_subscription_commerce import database  # noqa: F401

ROOT=Path(__file__).resolve().parents[1]
MANIFEST=(ROOT/"release-manifest.template.json").read_text()

def test_release_version_is_1_0_2_realise():
    assert '"version": "2.0.0-realise"' in MANIFEST

@pytest.mark.asyncio
async def test_fulfill_can_reuse_the_callers_customer_lock(database, panel, monkeypatch):  # noqa: F811
    import app.main as shop
    from test_integration_billing_vpn import premium
    monkeypatch.setattr(shop, "redis_client", object())

    async def quiet(*a, **k):
        return None
    monkeypatch.setattr(shop, "notify_user_telegram", quiet)
    taken = []

    async def user_lock(user_id, ttl=None):
        taken.append(user_id)
        return ("u", "t")
    monkeypatch.setattr(shop, "_acquire_user_fulfillment_lock", user_lock)
    p, _, _ = await premium(database, panel, "held-lock")
    await shop.fulfill(p.id, database, existing_user_lock_token="held-by-auto-renew")
    assert p.fulfillment_status == "completed" and taken == [], "the auto-renew lock is reused, not taken twice (no deadlock)"


@pytest.mark.asyncio
async def test_lock_release_cleans_renewal_registry_even_without_redis(monkeypatch):
    import asyncio

    import app.main as shop
    task = asyncio.get_running_loop().create_future()
    shop._LOCK_RENEW_TASKS["tok"] = task
    monkeypatch.setattr(shop, "redis_client", None)
    await shop._release_payment_side_effect_lock("lock:x", "tok")
    assert "tok" not in shop._LOCK_RENEW_TASKS and task.cancelled()
