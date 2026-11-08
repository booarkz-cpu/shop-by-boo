"""BACKLOG A1 (C1): /api/me/traffic answers only for the customer of the session — checked by calling the route with two
customers in the database, not by reading its source (replaces the source check of test_v34_hardening.py)."""
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app import main as shop
from app import panel_usage
from app.models import Subscription
from test_subscription_commerce import database  # noqa: F401


def req():
    return Request({"type": "http", "method": "GET", "path": "/api/me/traffic", "headers": [], "client": ("203.0.113.5", 1),
                    "query_string": b""})


@pytest.fixture
def panel(monkeypatch):
    """The panel: every customer has own counters; the calls are recorded."""
    calls = {"get_user": [], "usage": []}
    remote = {"remote-1": {"trafficUsedBytes": 111, "trafficLimitBytes": 1000, "devices": 1, "status": "ACTIVE"},
              "remote-2": {"trafficUsedBytes": 999_999, "trafficLimitBytes": 5000, "devices": 4, "status": "ACTIVE"}}

    class Client:
        async def get_user(self, uuid):
            calls["get_user"].append(uuid)
            return remote[uuid]

    async def usage(uuid, days):
        calls["usage"].append(uuid)
        return {"range_days": days, "days": [{"date": "2026-11-08", "bytes": remote[uuid]["trafficUsedBytes"]}],
                "nodes": [{"name": f"node-of-{uuid}", "bytes": 1, "country": "NL"}], "total_bytes": 1}

    monkeypatch.setattr(shop, "RemnawaveClient", Client)
    monkeypatch.setattr(panel_usage, "usage", usage)
    return calls


async def _two_customers(db):
    own = await db.get(Subscription, 1)
    own.is_primary = True
    db.add(Subscription(id=2, user_id=2, plan_id=2, expires_at=datetime.utcnow() + timedelta(days=30),
                        lifecycle_status="active", remnawave_uuid="remote-2", is_primary=True, traffic_limit_gb_snapshot=200,
                        device_limit_snapshot=4))
    await db.commit()


@pytest.mark.asyncio
async def test_traffic_is_read_for_the_customer_of_the_session_only(database, panel):
    await _two_customers(database)
    answer = await panel_usage.my_traffic(req(), 30, database)
    assert panel["get_user"] == ["remote-1"] and panel["usage"] == ["remote-1"]
    assert answer["traffic_used_bytes"] == 111 and answer["devices"] == 1
    assert "999999" not in repr(answer) and "remote-2" not in repr(answer)
    assert answer["days"] and all("country" not in n for n in answer["nodes"])  # the node country is not given away


@pytest.mark.asyncio
async def test_traffic_without_a_session_is_refused_before_the_panel_is_asked(database, panel, monkeypatch):
    await _two_customers(database)

    async def anonymous(request, session):
        raise HTTPException(401, "Нужен вход")

    monkeypatch.setattr(shop, "user_from_token", anonymous)
    with pytest.raises(HTTPException) as err:
        await panel_usage.my_traffic(req(), 30, database)
    assert err.value.status_code == 401
    assert panel == {"get_user": [], "usage": []}


@pytest.mark.asyncio
async def test_panel_without_statistics_still_gives_the_shape(database, panel, monkeypatch):
    async def broken(uuid, days):
        raise RuntimeError("panel has no bandwidth statistics")

    monkeypatch.setattr(panel_usage, "usage", broken)
    own = await database.get(Subscription, 1)
    own.is_primary = True
    await database.commit()
    answer = await panel_usage.my_traffic(req(), 30, database)
    assert answer["days"] == [] and answer["nodes"] == []
    assert answer["traffic_used_bytes"] == 111
