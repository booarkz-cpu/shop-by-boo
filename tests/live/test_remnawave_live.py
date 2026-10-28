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


@pytest.mark.asyncio
async def test_panel_overview_hosts_and_grace_expiry(panel):
    from app import panel_admin, traffic_report
    view = await panel_admin.overview(panel)
    assert view["profiles"] and view["squads"], "profiles and squads are listed"
    profile = view["profiles"][0]
    host = await panel._request("POST", "/api/hosts", json={
        "remark": "ci-host", "address": "ci.example.test", "port": 443,
        "inbound": {"configProfileUuid": profile["uuid"], "configProfileInboundUuid": profile["inbounds"][0]["uuid"]}})
    assert isinstance(host, dict) and "uuid" in host, str(host)[:600]
    uuid = host["uuid"]
    for action, expected in (("disable", True), ("enable", False)):
        await panel._request("POST", f"/api/hosts/bulk/{action}", json={"uuids": [uuid]})
        hosts = (await panel_admin.overview(panel))["hosts"]
        assert next(h for h in hosts if h["uuid"] == uuid)["disabled"] is expected
    await panel._request("DELETE", f"/api/hosts/{uuid}")
    # Grace access moves expireAt with PATCH /api/users (uuid in the body).
    expire = (datetime.utcnow() + timedelta(days=3)).replace(microsecond=0)
    user = await panel.create_user(f"ci_grace_{int(datetime.utcnow().timestamp())}", expire)
    until = expire + timedelta(hours=12)
    from app.grace_access import panel_expiry_patch
    await panel.patch_user(user["id"], panel_expiry_patch(until))  # the shop keeps the panel «id» as remnawave_uuid
    fresh = await panel.get_user(user["id"])
    assert fresh["expireAt"].startswith(until.isoformat()[:16])
    rows = await traffic_report.collect(panel, max_users=50)
    assert rows and "used" in rows[0], "traffic report reads the users stream"


@pytest.mark.asyncio
async def test_host_and_squad_editor(panel):
    from app import panel_admin as pa
    view = await pa.overview(panel)
    profile = view["profiles"][0]
    inbound = profile["inbounds"][0]["uuid"]
    host = await pa.create_host(panel, pa.HostEdit(remark="ci-edit", address="edit.example.test", port=443, profile=profile["uuid"],
                                                    inbound=inbound, sni="edit.example.test", path="/ws", tag="CI"))
    await pa.update_host(panel, host["uuid"], pa.HostEdit(remark="ci-edit-2", address="edit2.example.test", port=8443,
                                                          profile=profile["uuid"], inbound=inbound))
    edited = next(h for h in (await pa.overview(panel))["hosts"] if h["uuid"] == host["uuid"])
    assert (edited["remark"], edited["address"], edited["port"], edited["inbound"]) == ("ci-edit-2", "edit2.example.test", 8443, inbound)
    await pa.delete_host(panel, host["uuid"])
    squad = await pa.create_squad(panel, pa.SquadEdit(name="ci-squad", inbounds=[inbound]))
    await pa.update_squad(panel, squad["uuid"], pa.SquadEdit(name="ci-squad-2", inbounds=[]))
    found = next(s for s in (await pa.overview(panel))["squads"] if s["uuid"] == squad["uuid"])
    assert found["name"] == "ci-squad-2" and found["inbound_uuids"] == []
    await pa.delete_squad(panel, squad["uuid"])


@pytest.mark.asyncio
async def test_connections_bandwidth_keys_and_subscription_proxy(panel, monkeypatch):
    """v28.38 (remnawave-subscription-middleware functions): the calls the shop makes, against the real panel."""
    import base64
    from types import SimpleNamespace

    from starlette.requests import Request

    from app import panel_usage, sub_proxy, vpn_sessions
    expire = (datetime.utcnow() + timedelta(days=5)).replace(microsecond=0)
    user = await panel.create_user(f"ci_mw_{int(datetime.utcnow().timestamp())}", expire)
    result = await vpn_sessions.run_job(panel, "by-user", str(user["id"]))
    assert result is not None and result.get("nodes") == [], "a user without nodes is online nowhere"
    assert (await vpn_sessions.snapshot(panel)) == {}, "no nodes, no sessions"
    assert await vpn_sessions.drop(panel, str(user["id"])) is False, "no connected node: nothing to drop (A219)"
    traffic = await panel_usage.usage(str(user["id"]), 7, panel)
    assert len(traffic["days"]) == 7 and traffic["total_bytes"] == 0
    info = await panel._request("GET", f"/api/subscriptions/by-short-uuid/{user['shortUuid']}")
    assert isinstance(info.get("links"), list)
    # The proxy fetches the real subscription from the panel's /api/sub.
    cfg = {**sub_proxy.DEFAULT, "enabled": True, "public_base": "https://sub.ci.test", "origin": URL.rstrip("/") + "/api/sub"}
    sub_proxy._state.update(cfg=cfg, at=10 ** 12)

    async def nothing(*a, **k):
        return None

    async def no_sub(db, short):
        return None
    monkeypatch.setattr(sub_proxy, "_log", nothing)
    monkeypatch.setattr(sub_proxy, "lookup", no_sub)
    monkeypatch.setattr("app.client_versions.is_outdated", lambda *a: _false())
    request = Request({"type": "http", "method": "GET", "path": "/sub/x", "query_string": b"", "client": ("127.0.0.1", 1),
                       "headers": [(b"user-agent", b"v2rayNG/1.9.30"), (b"x-hwid", b"ci-device")]})
    monkeypatch.setattr(sub_proxy, "_client_ip", lambda r: "127.0.0.1")
    answer = await sub_proxy.serve(request, user["shortUuid"], SimpleNamespace())
    assert answer.status_code == 200 and "vless://" in base64.b64decode(answer.body).decode()
    assert answer.headers["profile-web-page-url"] == f"https://sub.ci.test/{user['shortUuid']}"
    clash = await sub_proxy.serve(request, f"{user['shortUuid']}/clash", SimpleNamespace())
    assert clash.status_code == 200 and b"proxies" in clash.body or b"mixed-port" in clash.body


async def _false():
    return False
