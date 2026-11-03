"""v28.69.0 (stage 12): the extension manager's panel calls with a fake panel (the real one runs in
tests/live/test_remnawave_live.py::test_extensions_*): bodies, validation, the REALITY builder, audit."""
import base64
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app import rw_extensions as ext

ADMIN = SimpleNamespace(email="owner@corgi.test")
U1, U2, U3 = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222", "33333333-3333-3333-3333-333333333333"


class Db:
    def __init__(self):
        self.rows = []

    def add(self, row):
        self.rows.append(row)

    async def commit(self):
        pass


@pytest.fixture
def panel(monkeypatch):
    calls = []

    async def fake(method, path, **kw):
        calls.append((method, path, kw.get("json"), kw.get("extra_headers")))
        if path == "/api/system/tools/x25519/generate":
            return {"keypairs": [{"publicKey": "PUB" * 10, "privateKey": "PRIV" * 10}]}
        if path == "/api/config-profiles" and method == "POST":
            return {"uuid": U1, "name": kw["json"]["name"], "inbounds": [{"uuid": U2, "tag": "VLESS_REALITY"}]}
        if path == "/api/nodes" and method == "PATCH":
            body = kw["json"]
            return {"uuid": body["uuid"], "name": "n1", "configProfile": body.get("configProfile") or {},
                    "activePluginUuid": body.get("activePluginUuid"), "versions": {"xray": "25.10.15", "node": "3.4.4"}}
        if path == "/api/subscription-settings" and method == "GET":
            return {"uuid": U3, "responseRules": None}
        if path == "/api/node-plugins" and method == "PATCH":
            return {"uuid": kw["json"]["uuid"], "name": "p", "pluginConfig": kw["json"].get("pluginConfig")}
        return {"uuid": U3, **(kw.get("json") or {})}
    monkeypatch.setattr(ext, "_panel", fake)
    return calls


def test_reality_builder():
    payload = ext.RealityIn(name="Lucy REALITY", server_names=["Node1.Example.com", "node1.example.com"], short_ids=3,
                            min_client_ver="25.1.1")
    config = ext.reality_config(payload, "PRIVATE")
    inbound = config["inbounds"][0]
    reality = inbound["streamSettings"]["realitySettings"]
    assert inbound["protocol"] == "vless" and inbound["port"] == 443 and inbound["streamSettings"]["security"] == "reality"
    assert reality["dest"] == ext.SELFSTEAL_SOCKET and reality["xver"] == 1, "SelfSteal: the node's own site on the socket"
    assert reality["serverNames"] == ["node1.example.com"] and len(reality["shortIds"]) == 3 and reality["minClientVer"] == "25.1.1"
    assert {"ip": ["geoip:private"], "outboundTag": "BLOCK"} in config["routing"]["rules"]
    site = ext.reality_config(ext.RealityIn(name="x1", server_names=["a.example.com"], dest="site", target="www.Example.com:443",
                                            block_torrent=False, doh=False), "K")
    assert site["inbounds"][0]["streamSettings"]["realitySettings"]["dest"] == "www.example.com:443"
    assert site["inbounds"][0]["streamSettings"]["realitySettings"]["xver"] == 0 and "dns" not in site
    assert {"protocol": ["bittorrent"], "outboundTag": "BLOCK"} not in site["routing"]["rules"]
    with pytest.raises(HTTPException):
        ext.reality_config(ext.RealityIn(name="x1", server_names=["a.example.com"], dest="site"), "K")
    for bad in ({"server_names": ["not a domain"]}, {"server_names": ["a.example.com"], "target": "x:99999"},
                {"server_names": ["a.example.com"], "name": "bad/name"}, {"server_names": ["a.example.com"], "extra": 1}):
        with pytest.raises(ValidationError):
            ext.RealityIn(**{"name": "ok", **bad})


@pytest.mark.asyncio
async def test_profile_node_plugin_calls(panel):
    db = Db()
    made = await ext.create_reality(ext.RealityIn(name="Lucy", server_names=["n.example.com"]), db, ADMIN)
    assert made["public_key"] == "PUB" * 10 and made["uuid"] == U1
    post = next(c for c in panel if c[0] == "POST" and c[1] == "/api/config-profiles")
    assert post[2]["config"]["inbounds"][0]["streamSettings"]["realitySettings"]["privateKey"] == "PRIV" * 10
    bound = await ext.node_profile(U3, ext.NodeProfileIn(profile_uuid=U1, inbounds=[U2]), db, ADMIN)
    assert bound["profile"] == U1 and bound["xray"] == "25.10.15"
    assert panel[-1][2] == {"uuid": U3, "configProfile": {"activeConfigProfileUuid": U1, "activeInbounds": [U2]}}
    await ext.node_plugin(U3, ext.NodePluginIn(plugin_uuid=None), db, ADMIN)
    assert panel[-1][2] == {"uuid": U3, "activePluginUuid": None}
    out = await ext.patch_plugin(U2, ext.PluginPatch(config={"torrentBlocker": {"enabled": True}}), db, ADMIN)
    assert out["config"]["torrentBlocker"]["enabled"]
    with pytest.raises(HTTPException):
        await ext.delete_profile("../../api/users", db, ADMIN)
    actions = [r.action for r in db.rows]
    assert actions == ["rw.profile.created", "rw.node.profile", "rw.node.plugin", "rw.plugin.updated"]


@pytest.mark.asyncio
async def test_subscription_settings_srr_and_templates(panel):
    db = Db()
    await ext.patch_subscription_settings(ext.SubscriptionSettingsIn(hwid_settings={"enabled": True, "fallbackDeviceLimit": 2},
                                                                     custom_response_headers={"x-corgi": "1"}), db, ADMIN)
    body = panel[-1][2]
    assert body == {"uuid": U3, "hwidSettings": {"enabled": True, "fallbackDeviceLimit": 2}, "customResponseHeaders": {"x-corgi": "1"}}
    with pytest.raises(ValidationError):
        ext.SubscriptionSettingsIn(custom_response_headers={"bad header": "x"})
    await ext.srr_test(ext.SrrTestIn(response_rules={"version": "1"}, user_agent="Happ/1.0\nX: y", headers={"x-hwid": "abc", "bad key": "1"}), ADMIN)
    assert panel[-1][1] == "/api/system/testers/srr-matcher" and panel[-1][3] == {"x-hwid": "abc", "User-Agent": "Happ/1.0 X: y"}
    await ext.patch_template(U1, ext.TemplatePatch(template_yaml="proxies: []\n"), db, ADMIN)
    assert base64.b64decode(panel[-1][2]["encodedTemplateYaml"]).decode() == "proxies: []\n"
    await ext.patch_template(U1, ext.TemplatePatch(template_json={**ext.BALANCER_TEMPLATE}), db, ADMIN)
    assert panel[-1][2]["templateJson"]["routing"]["balancers"][0]["tag"] == "Balancer"
    with pytest.raises(ValidationError):
        ext.TemplateIn(name="x1", template_type="EXE")


@pytest.mark.asyncio
async def test_panel_errors_reach_the_admin(monkeypatch):
    from app import remnawave

    class Broken:
        async def _request(self, *a, **k):
            raise remnawave.RemnawaveError('PATCH /api/node-plugins: 400: {"message":"torrentBlocker.enabled: expected boolean"}')
    monkeypatch.setattr(remnawave, "RemnawaveClient", Broken)
    with pytest.raises(HTTPException) as err:
        await ext._panel("PATCH", "/api/node-plugins")
    assert err.value.status_code == 502 and "expected boolean" in err.value.detail

    class Missing:
        async def _request(self, *a, **k):
            raise remnawave.RemnawaveNotConfigured("no")
    monkeypatch.setattr(remnawave, "RemnawaveClient", Missing)
    with pytest.raises(HTTPException) as err:
        await ext._panel("GET", "/api/config-profiles")
    assert err.value.status_code == 503


# ---------------------------------------------------------------- v28.70.0: WARP in a profile and server routing

ENTRY, EXIT, NODE, SS_IN = U1, U2, U3, "44444444-4444-4444-4444-444444444444"


@pytest.fixture
def routing_panel(monkeypatch):
    state = {"profiles": {
        ENTRY: {"name": "RU-entry", "config": {"inbounds": [{"tag": "VLESS_REALITY", "port": 443}],
                                               "outbounds": [{"tag": "DIRECT", "protocol": "freedom"}],
                                               "routing": {"rules": [{"ip": ["geoip:ru"], "outboundTag": "MY_DETOUR"},
                                                                     {"domain": ["example.org"], "outboundTag": "DIRECT"}]}}},
        EXIT: {"name": "FI-exit", "config": {"inbounds": [{"tag": "VLESS_FI", "port": 443}], "outbounds": []}}},
        "squads": [], "users": {}, "patches": [], "deleted": []}

    async def fake(method, path, **kw):
        body = kw.get("json")
        if path.startswith("/api/config-profiles/") and method == "GET":
            uuid = path.rsplit("/", 1)[1]
            p = state["profiles"][uuid]
            inbounds = [{"uuid": SS_IN if i["tag"] == ext.SR_IN else NODE, "tag": i["tag"]} for i in p["config"]["inbounds"]]
            return {"uuid": uuid, "name": p["name"], "config": p["config"], "inbounds": inbounds}
        if path == "/api/config-profiles" and method == "PATCH":
            state["profiles"][body["uuid"]]["config"] = body["config"]
            return {"uuid": body["uuid"]}
        if path == "/api/config-profiles" and method == "GET":
            return {"configProfiles": [{"uuid": u, "name": p["name"]} for u, p in state["profiles"].items()]}
        if path == f"/api/nodes/{NODE}":
            return {"uuid": NODE, "address": "fi.example.com", "configProfile": {"activeConfigProfileUuid": EXIT, "activeInbounds": [NODE]}}
        if path == "/api/nodes" and method == "PATCH":
            state["patches"].append(body)
            return body
        if path == "/api/internal-squads" and method == "GET":
            return {"internalSquads": state["squads"]}
        if path == "/api/internal-squads" and method == "PATCH":
            next(q for q in state["squads"] if q["uuid"] == body["uuid"])["inbounds"] = body["inbounds"]
            return body
        if path == "/api/internal-squads" and method == "POST":
            state["squads"].append({"uuid": "squad-1", **body})
            return state["squads"][-1]
        if path.startswith("/api/users/by-username/"):
            name = path.rsplit("/", 1)[1]
            if name not in state["users"]:
                raise HTTPException(502, "Remnawave: User not found")
            return state["users"][name]
        if path == "/api/users" and method == "POST":
            state["users"][body["username"]] = {**body, "id": 77}
            return state["users"][body["username"]]
        if method == "DELETE":
            state["deleted"].append(path)
            return {}
        raise AssertionError((method, path))
    monkeypatch.setattr(ext, "_panel", fake)
    return state


@pytest.mark.asyncio
async def test_warp_outbound_in_a_profile(routing_panel):
    db = Db()
    out = await ext.profile_warp(ENTRY, ext.WarpIn(domains=["Whoer.net", "geosite:openai"]), db, ADMIN)
    config = routing_panel["profiles"][ENTRY]["config"]
    warp = next(o for o in config["outbounds"] if o["tag"] == "warp-out")
    assert warp["streamSettings"]["sockopt"]["interface"] == "warp" and out["domains"] == ["whoer.net", "geosite:openai"]
    await ext.profile_warp(ENTRY, ext.WarpIn(domains=["2ip.ru"]), db, ADMIN)  # replaced, not duplicated
    config = routing_panel["profiles"][ENTRY]["config"]
    assert [r["domain"] for r in config["routing"]["rules"] if r.get("outboundTag") == "warp-out"] == [["2ip.ru"]]
    await ext.profile_warp(ENTRY, ext.WarpIn(enabled=False), db, ADMIN)
    config = routing_panel["profiles"][ENTRY]["config"]
    assert not any(o["tag"] == "warp-out" for o in config["outbounds"]) and len(config["routing"]["rules"]) == 2
    with pytest.raises(ValidationError):
        ext.WarpIn(domains=["bad domain; rm"])


@pytest.mark.asyncio
async def test_server_routing_bridge(routing_panel):
    db = Db()
    out = await ext.create_routing(ext.RoutingIn(entry_profile_uuid=ENTRY, exit_node_uuid=NODE, port=8443), db, ADMIN)
    assert out["exit"] == "fi.example.com:8443" and "8443" in out["note"]
    exit_in = next(i for i in routing_panel["profiles"][EXIT]["config"]["inbounds"] if i["tag"] == ext.SR_IN)
    assert exit_in["protocol"] == "shadowsocks" and exit_in["settings"]["method"] == ext.SR_METHOD
    assert routing_panel["patches"][-1]["configProfile"]["activeInbounds"] == [NODE, SS_IN], "the exit node keeps its inbounds"
    assert routing_panel["squads"][0]["inbounds"] == [SS_IN]
    user = next(iter(routing_panel["users"].values()))
    assert user["activeInternalSquads"] == ["squad-1"] and 8 <= len(user["ssPassword"]) <= 32
    config = routing_panel["profiles"][ENTRY]["config"]
    bridge = next(o for o in config["outbounds"] if o["tag"] == ext.SR_OUT)
    assert bridge["settings"]["servers"][0] == {"address": "fi.example.com", "port": 8443, "method": ext.SR_METHOD,
                                                "password": user["ssPassword"], "level": 0}
    rules = config["routing"]["rules"]
    assert {"ip": ["geoip:ru"], "outboundTag": "DIRECT"} in rules and {"inboundTag": ["VLESS_REALITY"], "outboundTag": ext.SR_OUT} in rules
    assert {"domain": ["example.org"], "outboundTag": "DIRECT"} in rules, "the administrator's own rules stay"
    assert any(r.get("protocol") == ["bittorrent"] for r in rules)

    # Bridge mode: Russian addresses through the exit node, no catch-all; the same user and password are reused.
    await ext.create_routing(ext.RoutingIn(entry_profile_uuid=ENTRY, exit_node_uuid=NODE, port=8443, mode="bridge"), db, ADMIN)
    rules = routing_panel["profiles"][ENTRY]["config"]["routing"]["rules"]
    assert {"ip": ["geoip:ru"], "outboundTag": ext.SR_OUT} in rules and not any("inboundTag" in r for r in rules)
    assert sum(1 for r in rules if r.get("ip") == ["geoip:ru"]) == 1 and len(routing_panel["users"]) == 1
    listed = await ext.list_routing(ADMIN)
    assert listed["bridges"] == [{"profile_uuid": ENTRY, "profile": "RU-entry", "exit": "fi.example.com:8443", "mode": "bridge"}]

    await ext.delete_routing(ENTRY, db, ADMIN)
    config = routing_panel["profiles"][ENTRY]["config"]
    assert not any(o["tag"] == ext.SR_OUT for o in config["outbounds"])
    assert not any(r.get("outboundTag") == ext.SR_OUT for r in config["routing"]["rules"])
    assert "/api/users/77" in routing_panel["deleted"] and "/api/internal-squads/squad-1" in routing_panel["deleted"]
    with pytest.raises(HTTPException):  # an exit node running the entry profile would route into itself
        routing_panel["profiles"][ENTRY]["config"]["inbounds"].append({"tag": "x"})
        await ext.create_routing(ext.RoutingIn(entry_profile_uuid=EXIT, exit_node_uuid=NODE), db, ADMIN)
