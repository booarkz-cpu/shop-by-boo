"""Node autoscaling: crowded nodes add one, quiet ones remove an autoscaled node only, cooldown and limits hold,
recommend mode only messages; auto mode creates the server at Hetzner and the node in the panel (mocked)."""
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

from app import node_autoscale as na
from test_subscription_commerce import database  # noqa: F401

ADMIN = SimpleNamespace(email="owner@corgi.test")
NOW = datetime(2026, 10, 28, 12, 0)
CFG = {**na.DEFAULT_CONFIG, "enabled": True, "up_at": 100, "down_at": 20, "min_nodes": 1, "max_nodes": 3,
       "sustain_minutes": 10, "cooldown_minutes": 30}


def nodes(*users, uuids=None):
    return [{"uuid": (uuids or [f"n{i}" for i in range(len(users))])[i], "name": f"node{i}", "status": "online", "users_online": u}
            for i, u in enumerate(users)]


def test_decide_up_after_sustain_and_cooldown():
    info, state = na.decide(CFG, nodes(150, 130), {}, NOW)
    assert info["action"] is None and info["load"] == 140.0 and state["high_since"]
    info, state = na.decide(CFG, nodes(150, 130), state, NOW + timedelta(minutes=10))
    assert info["action"] == "up" and "140.0" in info["reason"]
    info, _ = na.decide(CFG, nodes(150, 130), {**state, "last_action_at": NOW.isoformat()}, NOW + timedelta(minutes=10))
    assert info["action"] is None, "cooldown"
    info, _ = na.decide(CFG, nodes(150, 150, 150), state, NOW + timedelta(minutes=10))
    assert info["action"] is None and "максимум" in info["reason"]
    info, _ = na.decide(CFG, [], {}, NOW)
    assert info["action"] == "up" and "минимум" in info["reason"]


def test_decide_down_only_removes_own_nodes():
    state = {"low_since": (NOW - timedelta(minutes=11)).isoformat()}
    info, _ = na.decide(CFG, nodes(5, 3), state, NOW)
    assert info["action"] is None, "nodes made by hand are never removed"
    state["created"] = [{"node_uuid": "n1", "server_id": 9, "name": "auto-1"}]
    info, _ = na.decide(CFG, nodes(5, 3), state, NOW)
    assert info["action"] == "down" and info["node"]["uuid"] == "n1"
    info, _ = na.decide(CFG, nodes(5), state, NOW)
    assert info["action"] is None, "never below the minimum"


@pytest.mark.asyncio
async def test_recommend_mode_messages_once(database, monkeypatch):
    db = database

    async def quiet(*a, **k):
        return None
    import app.main as main
    monkeypatch.setattr(main, "audit", quiet)
    with pytest.raises(HTTPException):
        await na.put_autoscale(na.ConfigIn(enabled=True, up_at=10, down_at=10), db, ADMIN)
    await na.put_autoscale(na.ConfigIn(enabled=True, up_at=100, down_at=20, sustain_minutes=1, cooldown_minutes=30), db, ADMIN)
    sent = []

    async def sender(text):
        sent.append(text)
        return True
    crowded = nodes(300)
    await na.tick(db, NOW, nodes=crowded, sender=sender)
    await na.tick(db, NOW + timedelta(minutes=1), nodes=crowded, sender=sender)
    await na.tick(db, NOW + timedelta(minutes=2), nodes=crowded, sender=sender)
    assert len(sent) == 1 and "добавить ноду" in sent[0]
    view = await na.get_autoscale(db, ADMIN)
    assert view["last"]["load"] == 300.0 and view["created"] == [] and view["provider"] == {"hetzner_token": False, "node_secret": False}


@pytest.mark.asyncio
async def test_auto_mode_creates_and_removes_through_hetzner_and_panel(database, monkeypatch):
    db = database
    monkeypatch.setenv("HETZNER_API_TOKEN", "h-token")
    monkeypatch.setenv("REMNANODE_SECRET_KEY", "node-secret")

    async def quiet(*a, **k):
        return None
    import app.main as main
    monkeypatch.setattr(main, "audit", quiet)
    await na.put_autoscale(na.ConfigIn(enabled=True, mode="auto", up_at=100, down_at=20, sustain_minutes=1, cooldown_minutes=5,
                                       config_profile_uuid="aaaa-bbbb", inbound_uuids=["cccc"]), db, ADMIN)
    calls = []

    def handler(request: httpx.Request):
        calls.append((request.method, request.url.path, request.headers.get("authorization")))
        if request.method == "POST":
            body = json.loads(request.content)
            assert "node-secret" in body["user_data"] and body["labels"] == {"corgi": "autoscale"}
            return httpx.Response(201, json={"server": {"id": 77, "public_net": {"ipv4": {"ip": "203.0.113.7"}}}})
        return httpx.Response(204)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    class Panel:
        def __init__(self):
            self.created, self.deleted = [], []

        async def create_node(self, payload):
            self.created.append(payload)
            return {"uuid": "new-node"}

        async def delete_node(self, uuid):
            self.deleted.append(uuid)
    panel = Panel()
    sent = []

    async def sender(text):
        sent.append(text)
        return True
    await na.tick(db, NOW, nodes=nodes(300), sender=sender, panel=panel, client=client)
    await na.tick(db, NOW + timedelta(minutes=1), nodes=nodes(300), sender=sender, panel=panel, client=client)
    assert calls[0] == ("POST", "/v1/servers", "Bearer h-token")
    assert panel.created == [{"name": panel.created[0]["name"], "address": "203.0.113.7", "port": 2222, "countryCode": "FI",
                              "configProfile": {"activeConfigProfileUuid": "aaaa-bbbb", "activeInbounds": ["cccc"]}}]
    assert "Добавлена нода" in sent[-1]
    quiet_nodes = nodes(5, 2, uuids=["hand-made", "new-node"])
    later = NOW + timedelta(minutes=40)
    await na.tick(db, later, nodes=quiet_nodes, sender=sender, panel=panel, client=client)
    await na.tick(db, later + timedelta(minutes=1), nodes=quiet_nodes, sender=sender, panel=panel, client=client)
    assert panel.deleted == ["new-node"] and calls[-1][:2] == ("DELETE", "/v1/servers/77")
    view = await na.get_autoscale(db, ADMIN)
    assert view["created"] == [] and [h["action"] for h in view["history"]] == ["down", "up"]


@pytest.mark.asyncio
async def test_a_panel_failure_removes_the_new_server(monkeypatch):
    monkeypatch.setenv("HETZNER_API_TOKEN", "h-token")
    seen = []

    def handler(request):
        seen.append(request.method)
        if request.method == "POST":
            return httpx.Response(201, json={"server": {"id": 5, "public_net": {"ipv4": {"ip": "203.0.113.9"}}}})
        return httpx.Response(204)

    class Broken:
        async def create_node(self, payload):
            raise RuntimeError("panel 500")
    with pytest.raises(RuntimeError):
        await na.scale_up(dict(CFG), NOW, Broken(), httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert seen == ["POST", "DELETE"]
