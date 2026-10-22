"""Home-screen widget summary: minimal payload, states, traffic cache and panel failures."""
import json
from datetime import datetime, timedelta

import pytest
from starlette.responses import Response

from app import main as shop
from app import widget
from app.models import Notification, Subscription
from test_subscription_commerce import database, request


class FakeRedis:
    def __init__(self, broken=False):
        self.data, self.broken, self.sets = {}, broken, 0

    async def get(self, key):
        if self.broken:
            raise ConnectionError("down")
        return self.data.get(key)

    async def set(self, key, value, ex=None):
        if self.broken:
            raise ConnectionError("down")
        self.sets += 1
        self.data[key] = value


class Panel:
    calls = 0
    fail = False
    used = 30 * 1024**3

    async def get_user(self, uuid):
        Panel.calls += 1
        if Panel.fail:
            raise RuntimeError("panel down")
        return {"trafficUsedBytes": Panel.used, "trafficLimitBytes": 100 * 1024**3, "subscriptionUrl": "https://secret.example/sub"}


@pytest.fixture
def panel(monkeypatch):
    Panel.calls, Panel.fail = 0, False
    redis = FakeRedis()
    monkeypatch.setattr(shop, "RemnawaveClient", Panel)
    monkeypatch.setattr(shop, "redis_client", redis)
    return redis


async def summary(db):
    return await widget.widget_summary(request(), Response(), db)


@pytest.mark.asyncio
async def test_summary_is_minimal_and_reports_remaining_traffic(database, panel):
    database.add(Notification(user_id=1, kind="payment_success", title="t", body="b", dedupe_key="n1"))
    await database.commit()
    data = await summary(database)
    sub = data["subscription"]
    assert sub["state"] == "active" and sub["plan"] == "Basic"
    assert sub["days_left"] in (15, 16)
    assert sub["traffic_available"] is True
    assert sub["traffic_left_bytes"] == 70 * 1024**3
    assert data["unread_notifications"] == 1
    payload = json.dumps(data)
    for leaked in ("secret.example", "subscription_url", "wallet", "email", "remote-1"):
        assert leaked not in payload


@pytest.mark.asyncio
async def test_traffic_is_cached_between_widget_refreshes(database, panel):
    await summary(database)
    Panel.used = 50 * 1024**3
    second = await summary(database)
    assert Panel.calls == 1 and panel.sets == 1
    assert second["subscription"]["traffic_left_bytes"] == 70 * 1024**3
    Panel.used = 30 * 1024**3


@pytest.mark.asyncio
async def test_panel_failure_is_not_cached_and_falls_back_to_plan_limit(database, panel):
    Panel.fail = True
    data = await summary(database)
    assert data["subscription"]["traffic_available"] is False
    assert data["subscription"]["traffic_limit_bytes"] == 100 * 1024**3
    assert panel.sets == 0
    Panel.fail = False
    assert (await summary(database))["subscription"]["traffic_available"] is True


@pytest.mark.asyncio
async def test_broken_cache_still_answers(database, monkeypatch):
    monkeypatch.setattr(shop, "RemnawaveClient", Panel)
    monkeypatch.setattr(shop, "redis_client", FakeRedis(broken=True))
    Panel.fail = False
    assert (await summary(database))["subscription"]["traffic_available"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "delta,status,expected",
    [(timedelta(days=-1), "active", "expired"), (timedelta(days=2), "active", "expiring"), (timedelta(days=20), "cancel_scheduled", "cancel_scheduled"), (timedelta(days=20), "active", "active")],
)
async def test_subscription_states(database, panel, delta, status, expected):
    sub = await database.get(Subscription, 1)
    sub.expires_at = datetime.utcnow() + delta
    sub.lifecycle_status = status
    await database.commit()
    assert (await summary(database))["subscription"]["state"] == expected


@pytest.mark.asyncio
async def test_without_subscription_widget_shows_none(database, panel):
    sub = await database.get(Subscription, 1)
    sub.is_primary = False
    await database.commit()
    data = await summary(database)
    assert data["subscription"] is None and data["refresh_after_seconds"] == widget.REFRESH_AFTER_SECONDS
    assert Panel.calls == 0


def test_days_left_rounds_up_like_the_cabinet():
    now = datetime(2026, 1, 1)
    assert widget.days_left(now + timedelta(hours=1), now) == 1
    assert widget.days_left(now - timedelta(hours=1), now) == 0
    assert widget.days_left(None, now) is None
