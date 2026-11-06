import pytest

from test_subscription_commerce import database  # noqa: F401


# The confirm helper, the customer re-read under the lock and the deleted-account check run in
# tests/test_behaviour_fulfil_locks.py (C1, stage 19); they used to be positions of lines in the source.


@pytest.mark.asyncio
async def test_auto_renew_passes_existing_user_lock_to_fulfillment(database, monkeypatch):
    """A confirmed renewal is fulfilled under the customer lock the pass already holds and the payment lock."""
    from app import main as shop
    from test_money_review import _renewable, _scheduler_env
    charges, seen, locks = [], [], []
    _scheduler_env(monkeypatch, database, charges)

    async def paid(self, *a, **k):
        return True

    async def fulfill(payment_id, db, existing_user_lock_token=None):
        seen.append(existing_user_lock_token)

    async def payment_lock(payment_id, *a, **k):
        locks.append(payment_id)
        return ("p", "t")

    async def release(*a):
        return None
    monkeypatch.setattr(shop.YooKassaProvider, "verify_succeeded", paid)
    monkeypatch.setattr(shop, "fulfill", fulfill)
    monkeypatch.setattr(shop, "_acquire_payment_side_effect_lock", payment_lock)
    monkeypatch.setattr(shop, "_release_payment_side_effect_lock", release)
    await _renewable(database)
    await shop.run_auto_renew_pass(database)
    assert len(charges) == 1 and seen == ["token"] and len(locks) == 1, "the held customer lock is passed on"
