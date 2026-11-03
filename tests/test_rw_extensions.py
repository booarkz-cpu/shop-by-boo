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
