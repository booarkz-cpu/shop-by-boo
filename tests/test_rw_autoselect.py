"""Auto-selection pool («Пул автовыбора»): what the shop sends to the Remnawave panel and what it shows.

The panel here is an in-memory stand-in that keeps hosts and templates the way the real one does, so the tests
check the resulting state of the panel, not the text of the code. The real panel needs a VPS (O1 in BACKLOG.md).
"""
import copy
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app import rw_autoselect as auto

ADMIN = SimpleNamespace(email="owner@corgi.test")


def uid(n: int) -> str:
    return f"{n:08d}-0000-4000-8000-000000000000"


DE, CZ, NL, OFF = uid(1), uid(2), uid(3), uid(4)
INBOUND = uid(50)


class Db:
    def __init__(self):
        self.rows = []

    def add(self, row):
        self.rows.append(row)

    async def commit(self):
        pass


class Panel:
    """Hosts, nodes and subscription templates of a panel; answers like the Remnawave API (already unwrapped)."""

    def __init__(self):
        host = lambda u, name, addr, **kw: {"uuid": u, "remark": name, "address": addr, "port": 443, "sni": addr, "isHidden": False,  # noqa: E731
                                            "isDisabled": False, "inbound": {"configProfileUuid": uid(60), "configProfileInboundUuid": INBOUND},
                                            "nodes": [kw.pop("node")], **kw}
        self.hosts = {h["uuid"]: h for h in (host(DE, "Германия №1", "de1.example.com", node=uid(11)), host(CZ, "Чехия №1", "cz1.example.com", node=uid(12)),
                                             host(NL, "Нидерланды №2", "nl2.example.com", node=uid(13)),
                                             host(OFF, "Выключенный", "off.example.com", node=uid(13), isDisabled=True))}
        self.nodes = [{"uuid": uid(11), "name": "de-1", "countryCode": "DE", "isConnected": True, "isDisabled": False, "usersOnline": 7},
                      {"uuid": uid(12), "name": "cz-1", "countryCode": "CZ", "isConnected": False, "isDisabled": False, "usersOnline": 0},
                      {"uuid": uid(13), "name": "nl-2", "countryCode": "NL", "isConnected": True, "isDisabled": False, "usersOnline": 3}]
        self.templates = {uid(70): {"uuid": uid(70), "name": "Default", "templateType": "XRAY_JSON", "templateJson": {
            "routing": {"domainStrategy": "AsIs", "rules": [{"type": "field", "protocol": ["bittorrent"], "outboundTag": "direct"},
                                                             {"type": "field", "network": "tcp,udp", "outboundTag": "proxy"}]}}}}
        self.calls, self.next, self.fail_on = [], 100, None

    async def __call__(self, method, path, **kw):
        body = kw.get("json")
        self.calls.append((method, path, copy.deepcopy(body)))
        if self.fail_on and self.fail_on(method, path, body):
            raise HTTPException(502, "Remnawave: boom")
        if (method, path) == ("GET", "/api/hosts"):
            return copy.deepcopy(list(self.hosts.values()))
        if (method, path) == ("GET", "/api/nodes"):
            return copy.deepcopy(self.nodes)
        if (method, path) == ("GET", "/api/subscription-settings"):
            return {"uuid": uid(80), "serveJsonAtBaseSubscription": False}
        if (method, path) == ("GET", "/api/subscription-templates"):
            return {"templates": [{k: v for k, v in t.items() if k != "templateJson"} for t in self.templates.values()]}
        if method == "GET" and path.startswith("/api/subscription-templates/"):
            return copy.deepcopy(self.templates[path.rsplit("/", 1)[1]])
        if (method, path) == ("POST", "/api/subscription-templates"):
            self.next += 1
            self.templates[uid(self.next)] = {"uuid": uid(self.next), **body, "templateJson": {}}
            return {"uuid": uid(self.next)}
        if (method, path) == ("PATCH", "/api/subscription-templates"):
            self.templates[body["uuid"]].update({k: v for k, v in body.items() if k != "uuid"})
            return self.templates[body["uuid"]]
        if (method, path) == ("POST", "/api/hosts"):
            self.next += 1
            self.hosts[uid(self.next)] = {"uuid": uid(self.next), "isHidden": False, "isDisabled": False, **body}
            return {"uuid": uid(self.next)}
        if (method, path) == ("PATCH", "/api/hosts"):
            self.hosts[body["uuid"]].update({k: v for k, v in body.items() if k != "uuid"})
            return self.hosts[body["uuid"]]
        if method == "DELETE" and path.startswith("/api/hosts/"):
            return self.hosts.pop(path.rsplit("/", 1)[1])
        if method == "DELETE" and path.startswith("/api/subscription-templates/"):
            return self.templates.pop(path.rsplit("/", 1)[1])
        raise AssertionError(f"unexpected panel call {method} {path}")

    # What a customer's list shows: enabled hosts that are not hidden.
    def listed(self):
        return sorted(h["remark"] for h in self.hosts.values() if not h["isHidden"] and not h["isDisabled"])

    def tile(self):
        return next((h for h in self.hosts.values() if h.get("xrayJsonTemplateUuid")), None)

    def pool_template(self):
        return next(t for t in self.templates.values() if t["name"] == auto.TEMPLATE_NAME)["templateJson"]


@pytest.fixture
def env(monkeypatch):
    panel, stored = Panel(), {}

    async def load(db):
        return {**auto.DEFAULT, **copy.deepcopy(stored)}

    async def save(db, config):
        stored.clear()
        stored.update(copy.deepcopy(config))
    monkeypatch.setattr(auto, "_panel", panel)
    monkeypatch.setattr(auto, "_config", load)
    monkeypatch.setattr(auto, "_store", save)
    return panel, stored, Db()


def pool(**kw):
    return auto.PoolIn(**{"hosts": [DE, CZ, NL], **kw})


# ---- the template: every algorithm, the fallback, the rules of the Default template

@pytest.mark.parametrize("algorithm", ["leastPing", "leastLoad", "roundRobin", "random"])
def test_each_algorithm_builds_a_balancer_over_the_chosen_hosts(algorithm):
    base = {"routing": {"domainStrategy": "AsIs", "rules": [{"type": "field", "domain": ["geosite:category-ru"], "outboundTag": "direct"},
                                                             {"type": "field", "network": "tcp,udp", "outboundTag": "proxy"}]}}
    out = auto.build_template(base, [DE, CZ], algorithm)
    assert out["remnawave"]["injectHosts"] == [{"selector": {"type": "uuids", "values": [DE, CZ]}, "selectFrom": "ALL", "tagPrefix": "proxy"}]
    balancer = out["routing"]["balancers"][0]
    assert balancer["strategy"]["type"] == algorithm and balancer["selector"] == ["proxy"]
    # Never «direct»: with every node down the traffic goes to the first node of the pool, not around the VPN.
    assert balancer["fallbackTag"] == "proxy"
    # The health probe each strategy needs (Xray: leastLoad — burstObservatory; the others — observatory).
    assert ("burstObservatory" in out) == (algorithm == "leastLoad") and ("observatory" in out) == (algorithm != "leastLoad")
    assert (out.get("burstObservatory") or out["observatory"])["subjectSelector"] == ["proxy"]
    # The owner's own rule stays; the Default's catch-all is dropped so the balancer gets the traffic; ours is last.
    assert out["routing"]["rules"] == [{"type": "field", "domain": ["geosite:category-ru"], "outboundTag": "direct"},
                                       {"type": "field", "network": "tcp,udp", "balancerTag": "autoselect"}]
    assert out["routing"]["domainStrategy"] == "AsIs" and base["routing"]["rules"][1]["outboundTag"] == "proxy"  # the input is not changed


def test_template_refuses_an_unknown_algorithm_and_an_empty_pool():
    with pytest.raises(ValueError):
        auto.build_template({}, [DE], "fastest")
    with pytest.raises(ValueError):
        auto.build_template({}, [], "random")
    with pytest.raises(ValidationError):
        auto.PoolIn(hosts=[DE], algorithm="fastest")
    with pytest.raises(ValidationError):
        auto.PoolIn(hosts=[])
    with pytest.raises(ValidationError):
        auto.PoolIn(hosts=["../../api/users"])
    assert auto.PoolIn(hosts=[DE, DE, CZ]).hosts == [DE, CZ]


# ---- the panel after «включить»

@pytest.mark.asyncio
async def test_separate_tile_next_to_the_nodes(env):
    panel, stored, db = env
    view = await auto.put_pool(pool(algorithm="leastLoad"), db, ADMIN)
    tile = panel.tile()
    assert tile["remark"] == "⚡ Автовыбор" and not tile["isHidden"] and not tile["isDisabled"]
    # Nodes visible: the tile exists only where a real balancer exists (Xray JSON); other formats do not get a fake one.
    assert tile["excludeFromSubscriptionTypes"] == auto.NON_JSON_TYPES
    assert panel.listed() == ["⚡ Автовыбор", "Германия №1", "Нидерланды №2", "Чехия №1"]
    assert panel.pool_template()["routing"]["balancers"][0]["strategy"]["type"] == "leastLoad"
    assert panel.pool_template()["remnawave"]["injectHosts"][0]["selector"]["values"] == [DE, CZ, NL]
    assert tile["xrayJsonTemplateUuid"] == stored["template_uuid"] and stored["tile_uuid"] == tile["uuid"]
    # Figures come from the panel: three hosts in the pool, the Czech node is off-line.
    stats = view["stats"]
    assert (stats["pool_total"], stats["pool_online"], stats["pool_offline"], stats["in_subscription"], stats["hosts_total"]) == (3, 2, 1, 3, 3)
    assert view["tile"] == {"exists": True, "name": "⚡ Автовыбор", "visible": True, "formats_excluded": auto.NON_JSON_TYPES}
    de = next(h for h in view["hosts"] if h["uuid"] == DE)
    assert de == {"uuid": DE, "name": "Германия №1", "address": "de1.example.com", "country": "DE", "in_pool": True, "hidden": False,
                  "disabled": False, "online": True, "users_online": 7, "nodes": ["de-1"]}
    assert view["json_at_base"] is False and [r.action for r in db.rows] == ["rw.autoselect.applied"]


@pytest.mark.asyncio
async def test_hiding_the_nodes_and_bringing_them_back(env):
    panel, stored, db = env
    panel.hosts[NL]["isHidden"] = True  # the owner hid this one by hand before
    view = await auto.put_pool(pool(hide_nodes=True), db, ADMIN)
    assert panel.listed() == ["⚡ Автовыбор"]
    # Hidden nodes: the tile stays in every format, or Clash / sing-box / Base64 customers would see nothing.
    assert panel.tile()["excludeFromSubscriptionTypes"] == []
    assert stored["hidden_by_us"] == [DE, CZ] and view["stats"]["in_subscription"] == 0 and view["stats"]["pool_total"] == 3
    await auto.put_pool(pool(hide_nodes=False), db, ADMIN)
    # Only what the shop hid comes back; the host hidden by hand stays hidden.
    assert panel.listed() == ["⚡ Автовыбор", "Германия №1", "Чехия №1"] and panel.hosts[NL]["isHidden"] is True
    assert stored["hidden_by_us"] == [] and panel.tile()["excludeFromSubscriptionTypes"] == auto.NON_JSON_TYPES


@pytest.mark.asyncio
async def test_a_node_leaving_the_pool_returns_to_the_list_and_rename(env):
    panel, stored, db = env
    await auto.put_pool(pool(hide_nodes=True), db, ADMIN)
    await auto.put_pool(pool(hide_nodes=True, hosts=[DE, NL], name="🚀 Быстрый", algorithm="roundRobin"), db, ADMIN)
    assert panel.listed() == ["Чехия №1", "🚀 Быстрый"]
    assert panel.pool_template()["remnawave"]["injectHosts"][0]["selector"]["values"] == [DE, NL]
    assert panel.pool_template()["routing"]["balancers"][0]["strategy"]["type"] == "roundRobin"
    assert len([h for h in panel.hosts.values() if h.get("xrayJsonTemplateUuid")]) == 1  # the same tile, renamed
    assert len([t for t in panel.templates.values() if t["name"] == auto.TEMPLATE_NAME]) == 1


@pytest.mark.asyncio
async def test_repeating_the_same_request_changes_nothing(env):
    panel, stored, db = env
    await auto.put_pool(pool(hide_nodes=True), db, ADMIN)
    hosts, templates = copy.deepcopy(panel.hosts), copy.deepcopy(panel.templates)
    panel.calls.clear()
    await auto.put_pool(pool(hide_nodes=True), db, ADMIN)
    assert panel.hosts == hosts and panel.templates == templates
    assert not [c for c in panel.calls if c[0] in ("POST", "DELETE")]  # nothing created twice


@pytest.mark.asyncio
async def test_refused_before_anything_is_touched(env):
    panel, stored, db = env
    for hosts, text in (([DE, uid(999)], "не найден"), ([DE, OFF], "выключен")):
        with pytest.raises(HTTPException) as error:
            await auto.put_pool(pool(hosts=hosts), db, ADMIN)
        assert error.value.status_code == 422 and text in error.value.detail
    assert not [c for c in panel.calls if c[0] != "GET"] and panel.tile() is None
    await auto.put_pool(pool(), db, ADMIN)
    with pytest.raises(HTTPException) as error:
        await auto.put_pool(pool(hosts=[DE, stored["tile_uuid"]]), db, ADMIN)
    assert "собственный пул" in error.value.detail


@pytest.mark.asyncio
async def test_a_failure_while_hiding_is_remembered_so_the_nodes_can_be_brought_back(env):
    panel, stored, db = env
    panel.fail_on = lambda method, path, body: method == "PATCH" and path == "/api/hosts" and body.get("uuid") == CZ
    with pytest.raises(HTTPException):
        await auto.put_pool(pool(hide_nodes=True), db, ADMIN)
    # The German node was hidden before the panel failed: the shop knows it and «убрать плитку» restores it.
    assert stored["hidden_by_us"] == [DE] and panel.hosts[DE]["isHidden"] is True
    panel.fail_on = None
    await auto.delete_pool(db, ADMIN)
    assert panel.listed() == ["Германия №1", "Нидерланды №2", "Чехия №1"]


@pytest.mark.asyncio
async def test_refresh_drops_hosts_deleted_on_the_panel_and_refuses_an_empty_pool(env):
    panel, stored, db = env
    with pytest.raises(HTTPException) as error:
        await auto.refresh_pool(db, ADMIN)
    assert error.value.status_code == 409
    await auto.put_pool(pool(algorithm="random"), db, ADMIN)
    del panel.hosts[CZ]
    assert (await auto.get_pool(db, ADMIN))["stats"]["missing"] == [CZ]
    view = await auto.refresh_pool(db, ADMIN)
    assert stored["hosts"] == [DE, NL] and view["stats"]["missing"] == [] and view["algorithm"] == "random"
    assert panel.pool_template()["remnawave"]["injectHosts"][0]["selector"]["values"] == [DE, NL]
    del panel.hosts[DE], panel.hosts[NL]
    with pytest.raises(HTTPException) as error:
        await auto.refresh_pool(db, ADMIN)
    assert error.value.status_code == 409 and "не осталось" in error.value.detail


@pytest.mark.asyncio
async def test_removing_the_tile_restores_the_list_and_leaves_nothing_behind(env):
    panel, stored, db = env
    before = copy.deepcopy(panel.hosts), copy.deepcopy(panel.templates)
    await auto.put_pool(pool(hide_nodes=True), db, ADMIN)
    view = await auto.delete_pool(db, ADMIN)
    assert (panel.hosts, panel.templates) == before
    assert view["enabled"] is False and view["tile"]["exists"] is False
    assert stored["tile_uuid"] == "" and stored["template_uuid"] == "" and stored["hidden_by_us"] == []
    assert stored["hosts"] == [DE, CZ, NL]  # the choice is kept for the next «включить»
    await auto.delete_pool(db, ADMIN)  # a second click is harmless
    assert [r.action for r in db.rows] == ["rw.autoselect.applied", "rw.autoselect.removed", "rw.autoselect.removed"]


def test_a_host_without_a_known_node_is_shown_as_unknown_not_as_online():
    host = {"uuid": DE, "remark": "x", "inbound": {"configProfileInboundUuid": uid(51)}}
    view = auto.pool_view({**auto.DEFAULT, "hosts": [DE]}, [host], [{"uuid": uid(11), "isConnected": True, "configProfile": {"activeInbounds": [{"uuid": INBOUND}]}}], None)
    assert view["hosts"][0]["online"] is None and view["hosts"][0]["users_online"] is None
    assert view["stats"]["pool_unknown"] == 1 and view["stats"]["pool_online"] == 0 and view["json_at_base"] is None
    served = auto.pool_view({**auto.DEFAULT, "hosts": [DE]}, [{**host, "inbound": {"configProfileInboundUuid": INBOUND}}],
                            [{"uuid": uid(11), "isConnected": True, "usersOnline": 4, "configProfile": {"activeInbounds": [{"uuid": INBOUND}]}}], True)
    assert served["hosts"][0]["online"] is True and served["hosts"][0]["users_online"] == 4
