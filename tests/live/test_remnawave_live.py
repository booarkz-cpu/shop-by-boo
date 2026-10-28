"""The shop's Remnawave client against a real, newest Remnawave panel (scripts/ci/remnawave-live.sh starts it).

Skipped unless REMNAWAVE_LIVE_URL and REMNAWAVE_LIVE_TOKEN are set. Covers the calls the automation relies on:
users, nodes (create with a config profile, restart, delete), the node key, Internal Squad bulk add/remove."""
import os
from datetime import datetime, timedelta

import pytest
import pytest_asyncio

from app import remnawave
from app.config import settings

URL = os.environ.get("REMNAWAVE_LIVE_URL")
TOKEN = os.environ.get("REMNAWAVE_LIVE_TOKEN")
pytestmark = pytest.mark.skipif(not (URL and TOKEN), reason="no live Remnawave panel")


@pytest_asyncio.fixture
async def panel(monkeypatch):
    monkeypatch.setattr(settings, "remnawave_url", URL)
    monkeypatch.setattr(settings, "remnawave_token", TOKEN)
    import app.main as main
    monkeypatch.setattr(main, "redis_client", None)
    client = remnawave.RemnawaveClient()
    yield client
    await remnawave.RemnawaveClient.close_shared_client()


@pytest.mark.asyncio
async def test_nodes_and_node_key(panel):
    key = await panel.node_secret_key()
    assert len(key) > 100, "the panel hands out the node SECRET_KEY"
    profiles = (await panel._request("GET", "/api/config-profiles"))["configProfiles"]
    profile = profiles[0]
    inbound = profile["inbounds"][0]["uuid"]
    node = await panel.create_node({"name": "ci-autoscale", "address": "203.0.113.7", "port": 2222, "countryCode": "FI",
                                    "configProfile": {"activeConfigProfileUuid": profile["uuid"], "activeInbounds": [inbound]}})
    assert node["uuid"] and node["address"] == "203.0.113.7"
    from app.node_health import fetch_nodes
    rows = await fetch_nodes(panel)
    assert any(r["uuid"] == node["uuid"] for r in rows), "the node monitor sees the new node"
    await panel.restart_node(node["uuid"])
    await panel.restart_all_nodes()
    await panel.delete_node(node["uuid"])
    import asyncio
    for _ in range(20):  # the panel removes the node in a background job
        if not any(r["uuid"] == node["uuid"] for r in await fetch_nodes(panel)):
            break
        await asyncio.sleep(1)
    else:
        pytest.fail("the deleted node is still listed after 20 s")


@pytest.mark.asyncio
async def test_users_and_reserve_squad(panel):
    expire = (datetime.utcnow() + timedelta(days=30)).replace(microsecond=0)
    user = await panel.create_user(f"ci_{int(datetime.utcnow().timestamp())}", expire)
    assert user.get("uuid") or user.get("id")
    squads = await panel.list_internal_squads()
    squad = (squads.get("internalSquads") if isinstance(squads, dict) else squads)[0]["uuid"]
    await panel.squad_add_all_users(squad)
    await panel.squad_remove_all_users(squad)
    stream = await panel.stream_users(size=5)
    assert stream.get("users"), "user stream answers"
