"""«Починка блока: смена протокола»: four stages against a model of the Remnawave panel.

The model keeps a config profile, hosts and nodes like the real panel; the tests look at the state the panel is
left in and at what the owner is told. The real panel and real nodes need a VPS (O1 in BACKLOG.md).
"""
import copy
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app import rw_protocol_switch as ps

ADMIN = SimpleNamespace(email="owner@corgi.test")
PROFILE, INBOUND = "00000001-0000-4000-8000-000000000000", "00000002-0000-4000-8000-000000000000"
OTHER = "00000003-0000-4000-8000-000000000000"
PRIVATE_KEY = "reality-private-key-must-not-leak"


def uid(n: int) -> str:
    return f"{n:08d}-0000-4000-8000-00000000000a"


class Db:
    def __init__(self):
        self.rows = []

    def add(self, row):
        self.rows.append(row)

    async def commit(self):
        pass


class Panel:
    def __init__(self):
        reality = {"privateKey": PRIVATE_KEY, "shortIds": ["ab"], "serverNames": ["node.example.com"], "target": "/dev/shm/nginx.sock"}
        self.profile = {"uuid": PROFILE, "name": "Узлы", "inbounds": [{"uuid": INBOUND, "tag": "STEAL-T12"}, {"uuid": OTHER, "tag": "HY2"}], "config": {"inbounds": [
            {"tag": "STEAL-T12", "port": 8443, "protocol": "vless", "settings": {"clients": [], "decryption": "none"},
             "streamSettings": {"network": "grpc", "security": "reality", "realitySettings": reality, "grpcSettings": {"serviceName": "grpc", "multiMode": True}}},
            {"tag": "HY2", "port": 4443, "protocol": "hysteria", "streamSettings": {"network": "hysteria", "security": "tls"}}], "routing": {"rules": []}}}
        self.hosts = {uid(1): {"uuid": uid(1), "remark": "Германия №1", "path": "grpc", "inbound": {"configProfileInboundUuid": INBOUND}},
                      uid(2): {"uuid": uid(2), "remark": "Hysteria", "path": None, "inbound": {"configProfileInboundUuid": OTHER}}}
        node = lambda n, name, cc, online=True, **kw: {"uuid": uid(10 + n), "name": name, "countryCode": cc, "isConnected": online, "isDisabled": False,  # noqa: E731
                                                       "configProfile": {"activeInbounds": [{"uuid": INBOUND}]}, **kw}
        self.nodes = [node(1, "de-1", "DE"), node(2, "cz-1", "CZ"), node(3, "nl-2", "NL", online=False, lastStatusMessage="connect ETIMEDOUT")]
        self.calls, self.fail_on = [], None

    async def __call__(self, method, path, **kw):
        body = kw.get("json")
        self.calls.append((method, path, copy.deepcopy(body)))
        if self.fail_on and self.fail_on(method, path, body):
            raise HTTPException(502, "Remnawave: 400 invalid config")
        if (method, path) == ("GET", "/api/config-profiles"):
            return {"configProfiles": [copy.deepcopy(self.profile)]}
        if (method, path) == ("GET", f"/api/config-profiles/{PROFILE}"):
            return copy.deepcopy(self.profile)
        if method == "GET" and path.startswith("/api/config-profiles/"):
            raise HTTPException(404, "Remnawave: профиль не найден")
        if (method, path) == ("PATCH", "/api/config-profiles"):
            self.profile["config"] = copy.deepcopy(body["config"])
            return self.profile
        if (method, path) == ("GET", "/api/hosts"):
            return copy.deepcopy(list(self.hosts.values()))
        if (method, path) == ("PATCH", "/api/hosts"):
            self.hosts[body["uuid"]].update({k: v for k, v in body.items() if k != "uuid"})
            return self.hosts[body["uuid"]]
        if (method, path) == ("GET", "/api/nodes"):
            return copy.deepcopy(self.nodes)
        raise AssertionError(f"unexpected panel call {method} {path}")

    def inbound(self):
        return self.profile["config"]["inbounds"][0]


@pytest.fixture
def env(monkeypatch):
    panel, store = Panel(), {"jobs": []}

    async def load(db, key, default):
        return copy.deepcopy(store)

    async def save(db, key, value):
        store.clear()
        store.update(copy.deepcopy(value))
    from app import node_health
    monkeypatch.setattr(ps, "_panel", panel)
    monkeypatch.setattr(node_health, "_load", load)
    monkeypatch.setattr(node_health, "_save", save)
    return panel, store, Db()


def ask(target="xhttp", tag="STEAL-T12", profile=PROFILE):
    return ps.SwitchIn(profile_uuid=profile, inbound_tag=tag, target=target)


def stages(job):
    return {s["key"]: s["status"] for s in job["stages"]}


# ---- the inbound itself

@pytest.mark.parametrize("target,settings", [("xhttp", {"xhttpSettings": {"path": "/xhttp", "mode": "auto"}}),
                                               ("grpc", {"grpcSettings": {"serviceName": "grpc", "multiMode": True}}), ("tcp", {})])
def test_only_the_transport_changes(target, settings):
    before = Panel().inbound()
    after = ps.switched(before, target)
    stream = after["streamSettings"]
    assert stream["network"] == target and stream["security"] == "reality" and stream["realitySettings"] == before["streamSettings"]["realitySettings"]
    assert {k: v for k, v in stream.items() if k.endswith("Settings") and k != "realitySettings"} == settings  # nothing left of the old transport
    assert (after["tag"], after["port"], after["protocol"], after["settings"]) == (before["tag"], before["port"], before["protocol"], before["settings"])
    assert before["streamSettings"]["network"] == "grpc"  # the input is not changed
    assert ps.network_of({"streamSettings": {"network": "raw"}}) == "tcp" and ps.network_of({"streamSettings": {"network": "splithttp"}}) == "xhttp"


def test_requests_are_validated():
    for bad in ({"profile_uuid": "x"}, {"target": "ws"}, {"inbound_tag": "a;rm -rf /"}):
        with pytest.raises(ValidationError):
            ps.SwitchIn(**{"profile_uuid": PROFILE, "inbound_tag": "STEAL-T12", "target": "xhttp", **bad})


# ---- the four stages

@pytest.mark.asyncio
async def test_grpc_to_xhttp_then_part_of_the_nodes_is_not_a_success(env):
    panel, store, db = env
    job = await ps.start(ask("xhttp"), db, ADMIN)
    assert job["from"] == "grpc" and job["to"] == "xhttp" and job["status"] == "checking" and job["hosts_updated"] == 1
    assert stages(job) == {"read": "done", "switch": "done", "hosts": "done", "reconnect": "running"}
    assert all(s["started_at"] and s["log"] for s in job["stages"][:3])  # every stage has its time and its log
    # The panel: the inbound is on XHTTP, its host got the new path, the other inbound and its host are untouched.
    assert panel.inbound()["streamSettings"]["network"] == "xhttp" and "grpcSettings" not in panel.inbound()["streamSettings"]
    assert panel.hosts[uid(1)]["path"] == "/xhttp" and panel.hosts[uid(2)]["path"] is None
    assert panel.profile["config"]["inbounds"][1]["streamSettings"]["network"] == "hysteria"

    job = await ps.check(job["id"], db, ADMIN)
    # Two of three nodes are back: «частично», with the reason for the third and a note that it was off-line before.
    assert job["status"] == "partial" and "2 из 3" in job["summary"] and "не считается успешной" in job["summary"]
    assert [(r["n"], r["country"], r["name"], r["online"], r["transport"]) for r in job["nodes"]] == [
        (1, "CZ", "cz-1", True, "xhttp"), (2, "DE", "de-1", True, "xhttp"), (3, "NL", "nl-2", False, "xhttp")]
    assert "ETIMEDOUT" in job["nodes"][2]["error"] and "и до смены" in job["nodes"][2]["error"] and job["nodes"][0]["error"] is None
    assert all(r["checked_at"] for r in job["nodes"])

    panel.nodes[2]["isConnected"] = True
    job = await ps.check(job["id"], db, ADMIN)
    assert job["status"] == "succeeded" and "3 из 3" in job["summary"] and job["checks"] == 2 and stages(job)["reconnect"] == "done"
    assert [r.action for r in db.rows] == ["rw.protocol_switch.applied"]


@pytest.mark.asyncio
async def test_the_private_key_never_reaches_the_page_and_is_encrypted_at_rest(env):
    panel, store, db = env
    job = await ps.start(ask("tcp"), db, ADMIN)
    listed = await ps.overview(db, ADMIN)
    assert PRIVATE_KEY not in json.dumps(job) and PRIVATE_KEY not in json.dumps(listed) and "saved" not in job
    assert PRIVATE_KEY not in json.dumps(store)  # what the shop keeps for the rollback
    assert panel.hosts[uid(1)]["path"] is None  # TCP has no path


@pytest.mark.asyncio
async def test_same_transport_changes_nothing(env):
    panel, store, db = env
    before = copy.deepcopy(panel.profile), copy.deepcopy(panel.hosts)
    job = await ps.start(ask("grpc"), db, ADMIN)
    assert job["status"] == "unchanged" and stages(job) == {"read": "done", "switch": "skipped", "hosts": "skipped", "reconnect": "skipped"}
    assert (panel.profile, panel.hosts) == before and not [c for c in panel.calls if c[0] != "GET"]


@pytest.mark.asyncio
async def test_a_refused_host_update_puts_the_inbound_back(env):
    panel, store, db = env
    before = copy.deepcopy(panel.profile), copy.deepcopy(panel.hosts)
    panel.fail_on = lambda method, path, body: (method, path) == ("PATCH", "/api/hosts") and body.get("path") == "/xhttp"
    job = await ps.start(ask("xhttp"), db, ADMIN)
    assert job["status"] == "failed" and stages(job) == {"read": "done", "switch": "done", "hosts": "failed", "reconnect": "pending"}
    assert "Прежнее состояние восстановлено" in job["summary"] and job["restored"] == ["inbound STEAL-T12: транспорт gRPC возвращён"]
    assert (panel.profile, panel.hosts) == before  # inbound and hosts agree again
    assert [r.action for r in db.rows] == ["rw.protocol_switch.failed"]
    with pytest.raises(HTTPException) as error:
        await ps.check(job["id"], db, ADMIN)
    assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_a_refused_profile_change_leaves_the_panel_untouched(env):
    panel, store, db = env
    before = copy.deepcopy(panel.profile), copy.deepcopy(panel.hosts)
    panel.fail_on = lambda method, path, body: (method, path) == ("PATCH", "/api/config-profiles")
    job = await ps.start(ask("xhttp"), db, ADMIN)
    assert job["status"] == "failed" and "ничего не изменено" in job["summary"] and job["restored"] == []
    assert (panel.profile, panel.hosts) == before


@pytest.mark.asyncio
async def test_when_the_panel_cannot_even_restore_the_owner_is_told_and_can_roll_back_later(env):
    panel, store, db = env
    state = {"profile_patches": 0}

    def fail(method, path, body):
        if (method, path) == ("PATCH", "/api/hosts"):
            return True
        if (method, path) == ("PATCH", "/api/config-profiles"):
            state["profile_patches"] += 1
            return state["profile_patches"] == 2  # the switch passes, the restore is refused
        return False
    panel.fail_on = fail
    job = await ps.start(ask("xhttp"), db, ADMIN)
    assert job["status"] == "failed_inconsistent" and "могут не совпадать" in job["summary"]
    panel.fail_on = None
    job = await ps.rollback(job["id"], db, ADMIN)
    assert job["status"] == "rolled_back" and panel.inbound()["streamSettings"]["network"] == "grpc" and panel.hosts[uid(1)]["path"] == "grpc"


@pytest.mark.asyncio
async def test_rollback_returns_the_previous_transport_and_only_the_latest_run_can_be_rolled_back(env):
    panel, store, db = env
    before = copy.deepcopy(panel.profile), copy.deepcopy(panel.hosts)
    first = await ps.start(ask("xhttp"), db, ADMIN)
    second = await ps.start(ask("tcp"), db, ADMIN)
    with pytest.raises(HTTPException) as error:
        await ps.rollback(first["id"], db, ADMIN)
    assert error.value.status_code == 409 and "более поздний" in error.value.detail
    await ps.rollback(second["id"], db, ADMIN)
    out = await ps.rollback(first["id"], db, ADMIN)
    assert out["status"] == "rolled_back" and "gRPC" in out["summary"] and (panel.profile, panel.hosts) == before
    with pytest.raises(HTTPException):
        await ps.rollback(first["id"], db, ADMIN)  # nothing left to roll back
    assert [r.action for r in db.rows][-2:] == ["rw.protocol_switch.rolled_back", "rw.protocol_switch.rolled_back"]


@pytest.mark.asyncio
async def test_refusals_before_anything_is_touched(env):
    panel, store, db = env
    for request, text in ((ask(tag="NOPE"), "нет inbound"), (ask(tag="HY2"), "не переключается"),
                          (ask(profile="00000009-0000-4000-8000-000000000000"), "не найден")):
        job = await ps.start(request, db, ADMIN)
        assert job["status"] == "failed" and text in job["summary"] and "ничего не изменено" in job["summary"]
    assert not [c for c in panel.calls if c[0] != "GET"]
    with pytest.raises(HTTPException) as error:
        await ps.check("no-such-run", db, ADMIN)
    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_a_second_run_waits_for_the_first(env):
    panel, store, db = env
    store["jobs"] = [{"id": "x", "status": "switching", "created_at": ps.now()}]
    with pytest.raises(HTTPException) as error:
        await ps.start(ask(), db, ADMIN)
    assert error.value.status_code == 409 and not panel.calls
    store["jobs"][0]["created_at"] = "2026-01-01T00:00:00+00:00"  # a run that died long ago does not block for ever
    assert (await ps.start(ask(), db, ADMIN))["status"] == "checking"


@pytest.mark.asyncio
async def test_overview_shows_real_inbounds_and_meta_works_without_the_panel(env):
    panel, store, db = env
    view = await ps.overview(db, ADMIN)
    rows = view["profiles"][0]["inbounds"]
    assert rows[0] == {"tag": "STEAL-T12", "protocol": "vless", "port": 8443, "network": "grpc", "security": "reality", "hosts": 1, "nodes": 3,
                       "nodes_online": 2, "switchable": True}
    assert rows[1]["switchable"] is False and view["jobs"] == []
    panel.calls.clear()
    panel.fail_on = lambda *a: True
    assert (await ps.meta(db, ADMIN))["stages"] == ["Чтение текущего транспорта", "Смена протокола inbound", "Обновление hosts", "Проверка реконнекта нод"]
    assert not panel.calls


def test_disabled_nodes_are_not_counted_and_no_nodes_is_not_a_success():
    rows = ps.matrix([{"uuid": "a", "name": "a", "isConnected": True, "isDisabled": True}, {"uuid": "b", "name": "b", "isConnected": True}], {}, "xhttp")
    assert ps._verdict(rows)[0] == "succeeded" and rows[0]["error"] == "Нода выключена в панели"
    assert ps._verdict([])[0] == "partial" and ps._verdict(rows[:1])[0] == "partial"
