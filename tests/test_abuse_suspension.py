"""Anti-abuse restriction pauses subscriptions and clearing it gives them back."""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app import platform_api
from app.models import AbuseViolation, Subscription, User
from test_subscription_commerce import database

ADMIN = SimpleNamespace(email="root@example.test")


class FakeRemnawave:
    calls = []

    async def disable_user(self, uuid):
        FakeRemnawave.calls.append(("disable", uuid))

    async def enable_user(self, uuid):
        FakeRemnawave.calls.append(("enable", uuid))


@pytest.mark.asyncio
async def test_restrict_then_clear_restores_the_paid_subscription(database, monkeypatch):
    from app import remnawave
    monkeypatch.setattr(remnawave, "RemnawaveClient", FakeRemnawave)
    FakeRemnawave.calls = []
    expired = Subscription(id=2, user_id=1, plan_id=1, is_primary=False, remnawave_uuid="remote-old",
                           expires_at=datetime.utcnow() + timedelta(days=1), lifecycle_status="cancel_scheduled")
    database.add_all([expired, AbuseViolation(id=1, user_id=1, score=90, recommendation="block", analyzers={}, summary="x",
                                              status="open", created_at=datetime.utcnow())])
    await database.commit()
    await platform_api.review_violation(1, {"action": "restrict"}, database, ADMIN)
    user = await database.get(User, 1, populate_existing=True)
    subs = {s.id: s for s in (await database.execute(platform_api.select(Subscription))).scalars()}
    assert user.restricted_at is not None
    assert subs[1].lifecycle_status == "suspended" and subs[1].suspended_from == "active"
    assert subs[2].lifecycle_status == "suspended" and subs[2].suspended_from == "cancel_scheduled"
    assert ("disable", "remote-1") in FakeRemnawave.calls
    # One of them runs out while the customer is restricted.
    subs[2].expires_at = datetime.utcnow() - timedelta(minutes=1)
    await database.commit()
    await platform_api.review_violation(1, {"action": "clear"}, database, ADMIN)
    user = await database.get(User, 1, populate_existing=True)
    subs = {s.id: s for s in (await database.execute(platform_api.select(Subscription).execution_options(populate_existing=True))).scalars()}
    assert user.restricted_at is None
    assert subs[1].lifecycle_status == "active" and subs[1].suspended_from is None
    assert subs[2].lifecycle_status == "expired"
    assert ("enable", "remote-1") in FakeRemnawave.calls and ("enable", "remote-old") not in FakeRemnawave.calls
