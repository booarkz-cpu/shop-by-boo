"""RemnawaveClient against a panel that answers like @remnawave/backend-contract 3.4: {"response": ...}."""
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app import main, remnawave
from app.config import settings

EXPIRE = (datetime.now(timezone.utc) + timedelta(days=30)).replace(microsecond=0)
USER = {"id": 41, "uuid": "1b8f3a6e-0000-4000-8000-000000000041", "shortUuid": "abc", "username": "user_7", "status": "ACTIVE",
        "expireAt": EXPIRE.isoformat().replace("+00:00", "Z"), "subscriptionUrl": "https://sub.example/abc", "trafficLimitBytes": 0}
CALLS = []


def handler(request: httpx.Request) -> httpx.Response:
    CALLS.append((request.method, request.url.path, json.loads(request.content) if request.content else None))
    path = request.url.path
    if path == "/api/users" and request.method == "POST":
        body = json.loads(request.content)
        return httpx.Response(201, json={"response": {**USER, "username": body["username"]}})
    if path in ("/api/users/41", "/api/users/by-username/user_7") or path.startswith("/api/users/41/actions/"):
        return httpx.Response(200, json={"response": USER})
    if path == "/api/users" and request.method == "PATCH":
        return httpx.Response(200, json={"response": USER})
    if path == "/api/users" and request.method == "GET":
        return httpx.Response(200, json={"response": {"users": [USER], "total": 1}})
    if path == "/api/nodes":
        return httpx.Response(200, json={"response": [{"uuid": "n1", "name": "NL-1", "isConnected": True, "countryCode": "NL"}]})
    if path == "/api/subscriptions/by-id/41":
        return httpx.Response(200, json={"response": {"isFound": True, "user": {"username": "user_7"}, "subscriptionUrl": "https://sub.example/abc", "links": []}})
    if path == "/api/internal-squads":
        return httpx.Response(200, json={"response": {"total": 1, "internalSquads": [{"uuid": "11111111-2222-3333-4444-555555555555", "name": "Default"}]}})
    return httpx.Response(404, json={"message": "not found"})


@pytest.fixture
def panel(monkeypatch):
    CALLS.clear()
    monkeypatch.setattr(settings, "remnawave_url", "https://panel.example")
    monkeypatch.setattr(settings, "remnawave_token", "token")
    monkeypatch.setattr(main, "redis_client", None)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def shared(cls):
        return client
    monkeypatch.setattr(remnawave.RemnawaveClient, "_get_shared_client", classmethod(shared))
    return client


@pytest.mark.asyncio
async def test_user_lifecycle_reads_the_wrapped_payload(panel):
    rw = remnawave.RemnawaveClient()
    created = await rw.create_user("user_7", EXPIRE, 0, active_internal_squads=["11111111-2222-3333-4444-555555555555"], telegram_id=7)
    assert created["id"] == 41 and created["subscriptionUrl"] == "https://sub.example/abc"
    assert (await rw.get_user(41))["status"] == "ACTIVE"
    assert await rw.get_expiry(41) == EXPIRE.replace(tzinfo=None)
    assert (await rw.get_user_by_username("user_7"))["id"] == 41
    await rw.update_entitlements(41, 100, "11111111-2222-3333-4444-555555555555")
    await rw.disable_user(41)
    await rw.enable_user(41)
    sub = await rw.get_subscription(41)
    assert sub["subscriptionUrl"] == "https://sub.example/abc"
    method, path, body = next(c for c in CALLS if c[0] == "PATCH")
    # UpdateUserCommand: identifies the user by numeric id in the body.
    assert path == "/api/users" and body == {"id": 41, "trafficLimitBytes": 100 * 1024 ** 3, "activeInternalSquads": ["11111111-2222-3333-4444-555555555555"]}
    create = next(c for c in CALLS if c[0] == "POST" and c[1] == "/api/users")[2]
    assert set(create) >= {"username", "expireAt", "trafficLimitBytes", "trafficLimitStrategy", "activeInternalSquads", "telegramId"}
    assert ("POST", "/api/users/41/actions/disable", None) in CALLS and ("POST", "/api/users/41/actions/enable", None) in CALLS


@pytest.mark.asyncio
async def test_extend_uses_the_extend_action_with_days(panel, monkeypatch):
    rw = remnawave.RemnawaveClient()
    await rw.extend_user(41, 30)
    assert ("POST", "/api/users/41/actions/extend", {"days": 30}) in CALLS


@pytest.mark.asyncio
async def test_lists_nodes_users_and_squads(panel):
    from app.remnawave_shop_api import parse_squads
    from app.tariff_api import _iter_nodes
    rw = remnawave.RemnawaveClient()
    assert [n["name"] for n in _iter_nodes(await rw.list_nodes())] == ["NL-1"]
    assert main._remnawave_total(await rw.list_users(0, 1)) == 1
    assert parse_squads(await rw.list_internal_squads())[0]["uuid"] == "11111111-2222-3333-4444-555555555555"


def test_unwrap_only_touches_the_contract_wrapper():
    assert remnawave.unwrap({"response": [1]}) == [1]
    assert remnawave.unwrap({"response": {"a": 1}, "extra": 2}) == {"response": {"a": 1}, "extra": 2}
    assert remnawave.unwrap([1, 2]) == [1, 2]
