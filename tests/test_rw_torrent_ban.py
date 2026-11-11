"""«Временный бан за торренты»: the node plugin Torrent Blocker switched on and off for chosen nodes.

The panel is a model that keeps nodes and plugins; the tests look at what it is left with. The blocking itself is
done by the Remnawave node (2.7.0+) and needs a real node to be seen (O1 in BACKLOG.md).
"""
import copy
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app import rw_torrent_ban as tb

ADMIN = SimpleNamespace(email="owner@corgi.test")


def uid(n: int) -> str:
    return f"{n:08d}-0000-4000-8000-000000000000"


DE, CZ, NL = uid(1), uid(2), uid(3)
OWN = uid(40)  # the owner's own plugin with an egress filter


class Db:
    def __init__(self):
        self.rows = []

    def add(self, row):
        self.rows.append(row)

    async def commit(self):
        pass


class Panel:
    def __init__(self):
        node = lambda u, name, cc, **kw: {"uuid": u, "name": name, "countryCode": cc, "isConnected": True, "isDisabled": False,  # noqa: E731
                                          "activePluginUuid": None, "versions": {"node": "2.7.4"}, **kw}
        self.nodes = {n["uuid"]: n for n in (node(DE, "de-1", "DE"), node(CZ, "cz-1", "CZ", activePluginUuid=OWN), node(NL, "nl-2", "NL", versions={"node": "2.6.1"}))}
        self.plugins = {OWN: {"uuid": OWN, "name": "MyFilters", "pluginConfig": {
            "egressFilter": {"enabled": True, "blockedIps": [], "blockedPorts": [25]},
            "torrentBlocker": {"enabled": False, "blockDuration": 3600, "ignoreLists": {"ip": [], "userId": [77]}, "includeRuleTags": ["ads"]}}}}
        self.reports = [{"createdAt": "2026-11-11T08:00:00Z", "node": {"name": "de-1"}, "user": {"username": "user_5"},
                         "report": {"actionReport": {"ip": "198.51.100.9", "blockDuration": 1800}}},
                        {"createdAt": "2026-11-11T07:00:00Z", "somethingNew": True}]
        self.calls, self.next, self.fail = [], 100, None

    async def __call__(self, method, path, **kw):
        body = kw.get("json")
        self.calls.append((method, path, copy.deepcopy(body)))
        if self.fail and self.fail(method, path):
            raise HTTPException(502, "Remnawave: Cannot GET /api/node-plugins")
        if (method, path) == ("GET", "/api/nodes"):
            return copy.deepcopy(list(self.nodes.values()))
        if (method, path) == ("PATCH", "/api/nodes"):
            self.nodes[body["uuid"]].update({k: v for k, v in body.items() if k != "uuid"})
            return self.nodes[body["uuid"]]
        if (method, path) == ("GET", "/api/node-plugins"):
            return {"nodePlugins": copy.deepcopy(list(self.plugins.values()))}
        if (method, path) == ("POST", "/api/node-plugins"):
            self.next += 1
            self.plugins[uid(self.next)] = {"uuid": uid(self.next), "name": body["name"], "pluginConfig": {
                "ingressFilter": {"enabled": False, "blockedIps": []}, "torrentBlocker": {"enabled": False, "ignoreLists": {"ip": [], "userId": []}, "blockDuration": 3600}}}
            return copy.deepcopy(self.plugins[uid(self.next)])
        if (method, path) == ("PATCH", "/api/node-plugins"):
            self.plugins[body["uuid"]]["pluginConfig"] = copy.deepcopy(body["pluginConfig"])
            return self.plugins[body["uuid"]]
        if (method, path) == ("GET", "/api/node-plugins/torrent-blocker"):
            return {"records": copy.deepcopy(self.reports), "total": len(self.reports)}
        if (method, path) == ("GET", "/api/node-plugins/torrent-blocker/stats"):
            return {"stats": {"distinctNodes": 1, "totalRequests": 2}}
        raise AssertionError(f"unexpected panel call {method} {path}")

    def blocker(self, node):
        plugin = self.plugins.get(self.nodes[node]["activePluginUuid"])
        return (plugin or {}).get("pluginConfig", {}).get("torrentBlocker")

    def ours(self):
        return next((p for p in self.plugins.values() if p["name"] == tb.PLUGIN_NAME), None)


@pytest.fixture
def env(monkeypatch):
    panel = Panel()
    monkeypatch.setattr(tb, "_panel", panel)
    return panel, Db()


def ask(**kw):
    return tb.BanIn(**{"enabled": True, "node_uuids": [DE], **kw})


def test_requests_are_validated():
    assert tb.BanIn(enabled=True, node_uuids=[DE, DE], ignore_ips=[" 203.0.113.9 ", "2001:db8::1", "203.0.113.9"]).ignore_ips == ["203.0.113.9", "2001:db8::1"]
    for bad in ({"node_uuids": []}, {"node_uuids": ["x"]}, {"minutes": 0}, {"minutes": 20000}, {"ignore_ips": ["10.0.0.0/8"]}, {"ignore_ips": ["host.example"]}):
        with pytest.raises(ValidationError):
            ask(**bad)


def test_only_the_torrent_part_of_a_plugin_changes():
    before = Panel().plugins[OWN]["pluginConfig"]
    on = tb.with_blocker(before, True, 30, ["203.0.113.9"])
    assert on["egressFilter"] == before["egressFilter"]
    # The owner's user ids and rule tags stay; the duration is in seconds; the addresses are replaced.
    assert on["torrentBlocker"] == {"enabled": True, "blockDuration": 1800, "ignoreLists": {"ip": ["203.0.113.9"], "userId": [77]}, "includeRuleTags": ["ads"]}
    off = tb.with_blocker(on, False, 0, [])
    assert off["torrentBlocker"]["enabled"] is False and off["torrentBlocker"]["ignoreLists"] == {"ip": ["203.0.113.9"], "userId": [77]}
    assert before["torrentBlocker"]["enabled"] is False  # the input is not changed
    assert tb.with_blocker(None, True, 1, [])["torrentBlocker"]["blockDuration"] == 60


@pytest.mark.asyncio
async def test_a_bare_node_gets_the_shop_plugin_and_a_node_with_a_plugin_keeps_it(env):
    panel, db = env
    out = await tb.apply(ask(node_uuids=[DE, CZ], minutes=45, ignore_ips=["203.0.113.9"]), db, ADMIN)
    assert panel.nodes[DE]["activePluginUuid"] == panel.ours()["uuid"] and panel.nodes[CZ]["activePluginUuid"] == OWN
    assert panel.blocker(DE) == {"enabled": True, "ignoreLists": {"ip": ["203.0.113.9"], "userId": []}, "blockDuration": 2700}
    assert panel.blocker(CZ)["enabled"] is True and panel.blocker(CZ)["blockDuration"] == 2700 and panel.blocker(CZ)["includeRuleTags"] == ["ads"]
    assert panel.plugins[OWN]["pluginConfig"]["egressFilter"] == {"enabled": True, "blockedIps": [], "blockedPorts": [25]}
    assert panel.nodes[NL]["activePluginUuid"] is None  # not chosen: untouched
    rows = {r["name"]: r for r in out["nodes"]}
    assert (rows["de-1"]["ban"], rows["de-1"]["minutes"], rows["de-1"]["plugin"]["ours"]) == (True, 45, True)
    assert (rows["cz-1"]["ban"], rows["cz-1"]["plugin"]["name"], rows["cz-1"]["plugin"]["ours"]) == (True, "MyFilters", False)
    assert rows["nl-2"]["ban"] is False and rows["nl-2"]["supported"] is False and rows["de-1"]["supported"] is True
    assert out["enabled_nodes"] == 2 and out["minutes"] == 45 and out["ignore_ips"] == ["203.0.113.9"]
    assert out["changed"] == ["de-1", "плагин «MyFilters»"] and [r.action for r in db.rows] == ["rw.torrent_ban.enabled"]


@pytest.mark.asyncio
async def test_repeating_changes_nothing_and_nothing_is_created_twice(env):
    panel, db = env
    await tb.apply(ask(node_uuids=[DE, CZ]), db, ADMIN)
    nodes, plugins = copy.deepcopy(panel.nodes), copy.deepcopy(panel.plugins)
    panel.calls.clear()
    out = await tb.apply(ask(node_uuids=[DE, CZ]), db, ADMIN)
    assert (panel.nodes, panel.plugins) == (nodes, plugins) and out["changed"] == []
    assert not [c for c in panel.calls if c[0] != "GET"]
    assert len([p for p in panel.plugins.values() if p["name"] == tb.PLUGIN_NAME]) == 1


@pytest.mark.asyncio
async def test_switching_off_returns_what_was_changed(env):
    panel, db = env
    await tb.apply(ask(node_uuids=[DE, CZ]), db, ADMIN)
    out = await tb.apply(ask(enabled=False, node_uuids=[DE, CZ]), db, ADMIN)
    # Our plugin leaves the node; the owner's plugin stays on its node with only the torrent part off.
    assert panel.nodes[DE]["activePluginUuid"] is None and panel.nodes[CZ]["activePluginUuid"] == OWN
    assert panel.blocker(CZ)["enabled"] is False and panel.plugins[OWN]["pluginConfig"]["egressFilter"]["enabled"] is True
    assert out["enabled_nodes"] == 0 and [r.action for r in db.rows] == ["rw.torrent_ban.enabled", "rw.torrent_ban.disabled"]
    assert (await tb.apply(ask(enabled=False, node_uuids=[DE, CZ]), db, ADMIN))["changed"] == []  # a second «off» is harmless


@pytest.mark.asyncio
async def test_a_plugin_shared_with_nodes_that_were_not_chosen_is_not_changed_silently(env):
    panel, db = env
    panel.nodes[NL]["activePluginUuid"] = OWN  # the owner's plugin serves two nodes
    before = copy.deepcopy(panel.plugins)
    with pytest.raises(HTTPException) as error:
        await tb.apply(ask(node_uuids=[CZ]), db, ADMIN)
    assert error.value.status_code == 409 and "nl-2" in error.value.detail and "MyFilters" in error.value.detail
    assert panel.plugins == before and not [c for c in panel.calls if c[0] != "GET"]
    await tb.apply(ask(node_uuids=[CZ, NL]), db, ADMIN)  # both chosen: allowed
    assert panel.blocker(NL)["enabled"] is True
    # The shop's own plugin: another duration for one node would change the others too.
    await tb.apply(ask(node_uuids=[DE], minutes=60), db, ADMIN)
    panel.nodes[NL]["activePluginUuid"] = panel.ours()["uuid"]
    with pytest.raises(HTTPException) as error:
        await tb.apply(ask(node_uuids=[DE], minutes=5), db, ADMIN)
    assert error.value.status_code == 409 and "nl-2" in error.value.detail
    await tb.apply(ask(node_uuids=[DE], minutes=60), db, ADMIN)  # the same settings: fine


@pytest.mark.asyncio
async def test_unknown_node_is_refused_before_anything_is_touched(env):
    panel, db = env
    with pytest.raises(HTTPException) as error:
        await tb.apply(ask(node_uuids=[DE, uid(999)]), db, ADMIN)
    assert error.value.status_code == 422 and not [c for c in panel.calls if c[0] != "GET"]


@pytest.mark.asyncio
async def test_reports_are_shown_as_they_are_and_unknown_fields_stay_empty(env):
    panel, db = env
    out = await tb.get_state(ADMIN)
    assert out["reports"][0] == {"at": "2026-11-11T08:00:00Z", "node": "de-1", "user": "user_5", "ip": "198.51.100.9", "seconds": 1800}
    assert out["reports"][1] == {"at": "2026-11-11T07:00:00Z", "node": None, "user": None, "ip": None, "seconds": None}  # nothing guessed
    assert out["reports_supported"] is True and out["panel_supported"] is True


@pytest.mark.asyncio
async def test_an_old_panel_is_explained_not_shown_as_an_error(env):
    panel, db = env
    panel.fail = lambda method, path: path.startswith("/api/node-plugins")
    out = await tb.get_state(ADMIN)
    assert out["panel_supported"] is False and "Cannot GET" in out["panel_error"] and out["reports_supported"] is False
    assert [r["name"] for r in out["nodes"]] == ["cz-1", "de-1", "nl-2"] and out["enabled_nodes"] == 0
    panel.fail = lambda method, path: path.startswith("/api/node-plugins/torrent-blocker")
    out = await tb.get_state(ADMIN)  # plugins exist, the report endpoints do not
    assert out["panel_supported"] is True and out["reports_supported"] is False and out["reports"] == []
