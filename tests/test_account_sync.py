"""Every client reads one account state with a version: a paid subscription shows up everywhere."""
import asyncio
import json

import pytest
from starlette.requests import Request

from app import account_sync, node_health
from app import main as shop
from app.models import User
from test_integration_billing_vpn import panel, premium  # noqa: F401
from test_subscription_commerce import database  # noqa: F401


def req(query=b"", etag=None):
    headers = [(b"if-none-match", etag.encode())] if etag else []
    return Request({"type": "http", "method": "GET", "path": "/api/me/sync", "client": ("10.0.0.1", 1), "query_string": query, "headers": headers})


@pytest.fixture
def signed_in(database, monkeypatch):
    async def first(request, session):
        return await session.get(User, 1)

    async def snapshot():
        return {"nodes": [{"name": "Франкфурт", "country": "DE", "status": "online", "users_online": 7},
                          {"name": "Старая", "country": "NL", "status": "disabled", "users_online": 0}]}
    monkeypatch.setattr(shop, "user_from_token", first)
    monkeypatch.setattr(node_health, "node_snapshot", snapshot)
    monkeypatch.setattr(account_sync, "POLL_SECONDS", 0.02)
    return database


@pytest.mark.asyncio
async def test_payment_changes_the_version_and_an_unchanged_state_answers_304(signed_in, panel, monkeypatch):  # noqa: F811
    monkeypatch.setattr(shop, "redis_client", object())

    async def quiet(*a, **k):
        return None
    monkeypatch.setattr(shop, "notify_user_telegram", quiet)
    db = signed_in
    p, _, _ = await premium(db, panel)
    payment_id = p.id
    first = json.loads((await account_sync.my_sync(req(), db=db)).body)
    assert first["servers"] == [{"name": "Франкфурт", "country": "DE", "status": "online"}], "disabled nodes and online counters are not synced"
    assert first["subscriptions"][0]["primary"] and first["pending_payments"] == 0
    same = await account_sync.my_sync(req(etag=f'"{first["version"]}"'), db=db)
    assert same.status_code == 304
    await shop.fulfill(payment_id, db)
    after = await account_sync.my_sync(req(), since=first["version"], db=db)
    body = json.loads(after.body)
    assert after.status_code == 200 and body["version"] != first["version"]
    assert body["subscriptions"][0]["expires_at"] > first["subscriptions"][0]["expires_at"]
    assert body["subscriptions"][0]["device_limit"] == 4 and body["active"]


@pytest.mark.asyncio
async def test_a_waiting_client_is_answered_as_soon_as_the_state_changes(signed_in):
    db = signed_in
    first = json.loads((await account_sync.my_sync(req(), db=db)).body)

    async def top_up():
        await asyncio.sleep(0.1)
        user = await db.get(User, 1)
        user.wallet_balance = 500
        await db.commit()
    task = asyncio.create_task(top_up())
    answer = await asyncio.wait_for(account_sync.my_sync(req(), since=first["version"], wait=10, db=db), timeout=5)
    await task
    assert json.loads(answer.body)["wallet"]["balance"] in {"500", "500.00"}


@pytest.mark.asyncio
async def test_a_wait_without_changes_ends_with_304(signed_in, monkeypatch):
    monkeypatch.setattr(account_sync, "MAX_WAIT", 0)
    first = json.loads((await account_sync.my_sync(req(), db=signed_in)).body)
    assert (await account_sync.my_sync(req(), since=first["version"], wait=25, db=signed_in)).status_code == 304


@pytest.mark.asyncio
async def test_a_committed_change_wakes_the_waiting_client_at_once(signed_in, monkeypatch):
    """No 3-second polling: the commit itself wakes the request and is published for the other processes."""
    published = []

    class Redis:
        async def publish(self, channel, message):
            published.append(channel)
    monkeypatch.setattr(shop, "redis_client", Redis())
    monkeypatch.setattr(account_sync, "POLL_SECONDS", 30)
    db = signed_in
    first = json.loads((await account_sync.my_sync(req(), db=db)).body)

    async def top_up():
        await asyncio.sleep(0.1)
        user = await db.get(User, 1)
        user.wallet_balance = 700
        await db.commit()
    task = asyncio.create_task(top_up())
    started = asyncio.get_running_loop().time()
    answer = await asyncio.wait_for(account_sync.my_sync(req(), since=first["version"], wait=25, db=db), timeout=10)
    await task
    await asyncio.sleep(0)
    assert asyncio.get_running_loop().time() - started < 5, "woken by the commit, not by a poll"
    assert json.loads(answer.body)["wallet"]["balance"] in {"700", "700.00"}
    assert "sync:user:1" in published
