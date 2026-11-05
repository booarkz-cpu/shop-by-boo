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


@pytest.mark.asyncio
async def test_lucy_limits_and_customer_devices(panel):
    """v28.63.0: the panel itself holds the Lucy limits (devices, unlimited traffic), and the cabinet's device
    calls (list, delete one, delete all) use the panel 3.x bodies."""
    expire = (datetime.utcnow() + timedelta(days=30)).replace(microsecond=0)
    user = await panel.create_user(f"ci_lucy_{int(datetime.utcnow().timestamp())}", expire, traffic_limit_bytes=0, device_limit=2)
    uid = int(user["id"])
    fresh = await panel.get_user(uid)
    assert fresh["hwidDeviceLimit"] == 2 and fresh["trafficLimitBytes"] == 0, "Lucy Max: 2 devices, no traffic limit"
    await panel.update_entitlements(uid, None, None, device_limit=4)
    assert (await panel.get_user(uid))["hwidDeviceLimit"] == 4, "Lucy Ultra: 4 devices"
    for hwid in ("ci-device-aaaa-1", "ci-device-bbbb-2"):
        await panel._request("POST", "/api/hwid/devices", json={"hwid": hwid, "userId": uid, "platform": "Android"})
    assert {d["hwid"] for d in await panel.hwid_devices(uid)} == {"ci-device-aaaa-1", "ci-device-bbbb-2"}
    await panel.delete_hwid_device(uid, "ci-device-aaaa-1")
    assert [d["hwid"] for d in await panel.hwid_devices(uid)] == ["ci-device-bbbb-2"]
    await panel.reset_hwid_devices(uid)
    assert await panel.hwid_devices(uid) == []


@pytest.mark.asyncio
async def test_revoke_subscription_link(panel):
    """v28.67.0 (stage 11): «Сменить ссылку подписки» — the panel issues a new shortUuid, the old link stops working."""
    expire = (datetime.utcnow() + timedelta(days=5)).replace(microsecond=0)
    user = await panel.create_user(f"ci_rv_{int(datetime.utcnow().timestamp())}", expire)
    fresh = await panel.revoke_subscription(int(user["id"]))
    assert fresh["shortUuid"] and fresh["shortUuid"] != user["shortUuid"]
    assert fresh["subscriptionUrl"].rstrip("/").endswith(fresh["shortUuid"])


NODE_ADDRESS = os.environ.get("REMNAWAVE_LIVE_NODE_ADDRESS")
SUBPAGE_URL = os.environ.get("REMNAWAVE_LIVE_SUBPAGE_URL")


@pytest.mark.asyncio
@pytest.mark.skipif(not NODE_ADDRESS, reason="no node container")
async def test_mode_panel_plus_node(panel):
    """v28.65.0 (stage 9, mode «Panel + Node»): a node of the latest release, started with the SECRET_KEY the
    panel hands out, connects to the panel once the panel knows its address and port."""
    import asyncio
    from app.node_health import fetch_nodes
    profile = (await panel._request("GET", "/api/config-profiles"))["configProfiles"][0]
    node = await panel.create_node({"name": "ci-mode-node", "address": NODE_ADDRESS, "port": 2222, "countryCode": "FI",
                                    "configProfile": {"activeConfigProfileUuid": profile["uuid"],
                                                      "activeInbounds": [profile["inbounds"][0]["uuid"]]}})
    try:
        for _ in range(60):
            row = next((r for r in await fetch_nodes(panel) if r["uuid"] == node["uuid"]), {})
            if row.get("is_connected") or row.get("isConnected") or row.get("status") == "online":
                break
            await asyncio.sleep(3)
        else:
            pytest.fail(f"the node did not connect in 180 s: {row}")
    finally:
        await panel.delete_node(node["uuid"])


@pytest.mark.asyncio
@pytest.mark.skipif(not SUBPAGE_URL, reason="no subscription page container")
async def test_mode_panel_plus_subscription_page(panel):
    """v28.65.0 (stage 9, mode «Panel + Subscription Page»): the official subscription page of the latest release
    serves a panel user's subscription to a VPN client. Whether it also shows a web page to a browser is decided by
    the panel's subscription response rules (SRR); with the defaults of a fresh panel it does not."""
    import httpx
    expire = (datetime.utcnow() + timedelta(days=5)).replace(microsecond=0)
    user = await panel.create_user(f"ci_sp_{int(datetime.utcnow().timestamp())}", expire)
    # Like the panel, the page drops connections without a TLS reverse proxy in front: send what the proxy adds.
    proxy = {"x-forwarded-for": "203.0.113.9", "x-forwarded-proto": "https"}
    async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
        sub = await client.get(f"{SUBPAGE_URL}/{user['shortUuid']}", headers={**proxy, "user-agent": "v2rayNG/1.9.30"})
    assert sub.status_code == 200 and "text/html" not in sub.headers.get("content-type", ""), (sub.status_code, sub.text[:300])
    assert sub.content, "a subscription body"


class _Db:
    """Audit rows of the extension manager are not the point here."""
    def add(self, row):
        pass

    async def commit(self):
        pass


@pytest.mark.asyncio
async def test_extensions_profiles_reality_and_nodes(panel):
    """v28.69.0 (stage 12): config profiles from the shop — a VLESS + REALITY profile built from typed values with keys
    from the panel, edited, bound to a node with a host for its inbound, then removed."""
    from types import SimpleNamespace

    from app import rw_extensions as ext
    admin, db = SimpleNamespace(email="ci@corgi.test"), _Db()
    keys = await ext.x25519(admin)
    assert len(keys["public_key"]) > 30 and len(keys["private_key"]) > 30
    made = await ext.create_reality(ext.RealityIn(name=f"ci-reality-{int(datetime.utcnow().timestamp()) % 100000}", server_names=["ci.example.com"],
                                                  dest="site", target="www.example.com:443", min_client_ver="25.1.1"), db, admin)
    assert made["uuid"] and made["public_key"] and len(made["short_ids"][0]) == 16
    raw = await ext.get_profile(made["uuid"], admin)
    reality = raw["config"]["inbounds"][0]["streamSettings"]["realitySettings"]
    assert reality["serverNames"] == ["ci.example.com"] and reality["dest"] == "www.example.com:443" and reality["minClientVer"] == "25.1.1"
    inbound = raw["inbounds"][0]["uuid"]
    renamed = await ext.patch_profile(made["uuid"], ext.ProfilePatch(name="ci-reality-renamed"), db, admin)
    assert renamed["name"] == "ci-reality-renamed"
    node = await panel.create_node({"name": f"ci-ext-{int(datetime.utcnow().timestamp()) % 100000}", "address": "203.0.113.8", "port": 2222,
                                    "configProfile": {"activeConfigProfileUuid": made["uuid"], "activeInbounds": [inbound]}})
    bound = await ext.node_profile(node["uuid"], ext.NodeProfileIn(profile_uuid=made["uuid"], inbounds=[inbound]), db, admin)
    assert bound["profile"] == made["uuid"] and bound["inbounds"] == [inbound]
    host = await ext.profile_host(made["uuid"], ext.ProfileHostIn(inbound_uuid=inbound, remark="ci-reality", address="ci.example.com",
                                                                  sni="ci.example.com"), db, admin)
    assert host["uuid"]
    overview = await ext.overview(admin)
    assert any(p["uuid"] == made["uuid"] and node["name"] in p["nodes"] for p in overview["profiles"])
    await panel._request("DELETE", f"/api/hosts/{host['uuid']}")
    await panel.delete_node(node["uuid"])
    assert (await ext.delete_profile(made["uuid"], db, admin))["deleted"]


@pytest.mark.asyncio
async def test_extensions_plugins_srr_pages_and_templates(panel):
    """v28.69.0 (stage 12): node plugins (TorrentBlocker on, bound to a node), subscription response rules and the
    panel's matcher, subscription page configs and an Xray JSON template with the client balancer."""
    from types import SimpleNamespace

    from app import rw_extensions as ext
    admin, db = SimpleNamespace(email="ci@corgi.test"), _Db()
    stamp = int(datetime.utcnow().timestamp()) % 100000
    plugin = await ext.create_plugin(ext.PluginIn(name=f"ci-plugin-{stamp}"), db, admin)
    assert plugin["uuid"] and "torrentBlocker" in plugin["config"]
    config = {**plugin["config"], "torrentBlocker": (await ext.presets(admin))["plugins"]["torrentBlocker"]}
    edited = await ext.patch_plugin(plugin["uuid"], ext.PluginPatch(config=config), db, admin)
    assert edited["config"]["torrentBlocker"]["enabled"] is True
    with pytest.raises(Exception):  # the panel validates the config
        await ext.patch_plugin(plugin["uuid"], ext.PluginPatch(config={"torrentBlocker": {"enabled": "yes"}}), db, admin)
    profile = (await panel._request("GET", "/api/config-profiles"))["configProfiles"][0]
    node = await panel.create_node({"name": f"ci-plug-{stamp}", "address": "203.0.113.9", "port": 2222,
                                    "configProfile": {"activeConfigProfileUuid": profile["uuid"], "activeInbounds": [profile["inbounds"][0]["uuid"]]}})
    assert (await ext.node_plugin(node["uuid"], ext.NodePluginIn(plugin_uuid=plugin["uuid"]), db, admin))["plugin"] == plugin["uuid"]
    assert (await ext.node_plugin(node["uuid"], ext.NodePluginIn(plugin_uuid=None), db, admin))["plugin"] is None
    await panel.delete_node(node["uuid"])
    assert (await ext.delete_plugin(plugin["uuid"], db, admin))["deleted"]

    settings_ = await ext.subscription_settings(admin)
    assert settings_["uuid"]
    saved = await ext.patch_subscription_settings(ext.SubscriptionSettingsIn(custom_response_headers={"x-corgi-ci": "1"}), db, admin)
    assert saved["customResponseHeaders"]["x-corgi-ci"] == "1"
    rules = settings_.get("responseRules") or {"version": "1", "settings": {"disableSubscriptionAccessByPath": False}, "rules": []}
    tested = await ext.srr_test(ext.SrrTestIn(response_rules=rules, user_agent="Mozilla/5.0 (CI) Chrome/150"), admin)
    assert "matched" in tested and tested["inputHeaders"].get("user-agent", "").startswith("Mozilla")

    page = await ext.create_subpage_config(ext.NamedJsonIn(name=f"ci-page-{stamp}"), db, admin)
    assert page["uuid"] and (await ext.subpage_config(page["uuid"], admin))["uuid"] == page["uuid"]
    assert any(c["uuid"] == page["uuid"] for c in (await ext.subpage_configs(admin))["configs"])
    assert (await ext.delete_subpage_config(page["uuid"], db, admin))["deleted"]

    template = await ext.create_template(ext.TemplateIn(name=f"ci-balancer-{stamp}", template_type="XRAY_JSON"), db, admin)
    body = (await ext.template(template["uuid"], admin)).get("templateJson") or {}
    balanced = await ext.patch_template(template["uuid"], ext.TemplatePatch(template_json={**body, **ext.BALANCER_TEMPLATE}), db, admin)
    assert balanced["templateJson"]["routing"]["balancers"][0]["strategy"]["type"] == "leastPing"
    assert (await ext.delete_template(template["uuid"], db, admin))["deleted"]


@pytest.mark.asyncio
async def test_renewal_block_and_reactivation_on_the_real_panel(panel):
    """v28.77.0 (stage 18, main scenario): the calls a paid renewal, a refund and a repeat purchase make —
    extend by days (verified like the shop does), disable, enable — against the real panel."""
    expire = (datetime.utcnow() + timedelta(days=5)).replace(microsecond=0)
    user = await panel.create_user(f"ci_life_{int(datetime.utcnow().timestamp())}", expire)
    uid = user["id"]  # the shop keeps the panel «id» as remnawave_uuid
    before = await panel.get_expiry(uid)
    assert before and abs((before - expire).total_seconds()) < 120
    out = await panel.extend_idempotent(uid, 30, before, before + timedelta(days=30))
    assert out["already_applied"] is False and out["expires_at"] >= before + timedelta(days=30)
    again = await panel.extend_idempotent(uid, 30, before, before + timedelta(days=30))
    assert again["already_applied"] is True, "a retried renewal never adds the days twice"
    await panel.disable_user(uid)  # refund
    assert str((await panel.get_user(uid))["status"]).upper() == "DISABLED"
    await panel.enable_user(uid)  # a later purchase re-enables
    assert str((await panel.get_user(uid))["status"]).upper() == "ACTIVE"
