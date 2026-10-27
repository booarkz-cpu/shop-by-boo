import pytest

from test_subscription_commerce import database  # noqa: F401
from main_source import main_source
from pathlib import Path

MAIN = main_source()


def _block(start_marker, end_marker):
    start = MAIN.index(start_marker)
    end = MAIN.index(end_marker, start)
    return MAIN[start:end]


def test_confirm_helper_uses_confirmed_row_variable_and_never_undefined_name():
    block = _block('async def _confirm_and_fulfill_payment', 'async def fulfill(')
    assert 'if not confirmed:' in block
    assert 'confirmed_payment' not in block


def test_fulfill_reloads_user_for_update_even_when_caller_holds_user_lock():
    block = _block('async def fulfill(payment_id:int, db:AsyncSession, existing_user_lock_token: str|None = None):', 'async def payment_by_provider')
    lock_idx = block.index('user_token = existing_user_lock_token')
    reload_idx = block.index('select(User).where(User.id==user.id).execution_options(populate_existing=True).with_for_update()')
    assert lock_idx < reload_idx
    assert 'if not existing_user_lock_token:' not in block[block.index('The first User read'):block.index('payment_lock, token = await _acquire_payment_side_effect_lock')]


def test_fulfill_rejects_deleted_user_before_payment_side_effect_lock():
    block = _block('async def fulfill(payment_id:int, db:AsyncSession, existing_user_lock_token: str|None = None):', 'async def payment_by_provider')
    assert block.index('if not user or user.deleted_at is not None') < block.index('payment_lock, token = await _acquire_payment_side_effect_lock(payment_id)')


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
