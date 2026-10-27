"""Node monitoring: a node that stays offline is restarted through Remnawave, the owner is alerted after the
alert time and once more when it is back, silent node agents are reported, the planned restart and node
update run once a Moscow day."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app import node_health
from app.models import AgentAction, NodeAgent
from app_contract import permissions
from test_subscription_commerce import database  # noqa: F401

T0 = datetime(2026, 10, 27, 9, 0, tzinfo=timezone.utc)  # 12:00 in Moscow


class Panel:
    def __init__(self):
        self.status = {"n-1": False, "n-2": True}
        self.restarts, self.restart_all = [], 0

    async def list_nodes(self, start=0, size=25):
        return {"response": [{"uuid": u, "name": {"n-1": "Frankfurt", "n-2": "Helsinki"}[u], "isConnected": up, "isDisabled": False}
                             for u, up in self.status.items()]}

    async def restart_node(self, uuid):
        self.restarts.append(uuid)

    async def restart_all_nodes(self):
        self.restart_all += 1


@pytest.fixture
def world(monkeypatch):
    monkeypatch.setattr(node_health, "_redis", lambda: None)
    sent = []

    async def sender(text):
        sent.append(text)
        return True
    return Panel(), sent, sender


@pytest.mark.asyncio
async def test_an_offline_node_is_restarted_then_reported_then_welcomed_back(database, world):
    panel, sent, sender = world
    run = lambda minutes: node_health.monitor_pass(database, T0 + timedelta(minutes=minutes), panel=panel, sender=sender)  # noqa: E731
    assert (await run(0))["restarted"] == [], "the first sighting only starts the clock"
    assert (await run(2))["restarted"] == []
    assert (await run(3))["restarted"] == ["n-1"] and panel.restarts == ["n-1"]
    assert (await run(5))["restarted"] == [], "cooldown between restarts"
    assert sent == []
    out = await run(10)
    assert out["alerts"] == ["n-1"] and "Frankfurt" in sent[0] and "10 мин" in sent[0]
    await run(11)
    assert len(sent) == 1, "one alert per outage"
    assert (await run(18))["restarted"] == ["n-1"], "a new restart after the cooldown"
    panel.status["n-1"] = True
    assert (await run(20))["recovered"] == ["n-1"] and "снова в сети" in sent[-1]
    panel.status["n-1"] = False
    await run(21)
    assert (await run(23))["alerts"] == [], "a new outage starts a new clock"


@pytest.mark.asyncio
async def test_silent_node_agents_are_reported_once(database, world):
    panel, sent, sender = world
    database.add(NodeAgent(name="de-1", token_hash="h" * 64, last_seen_at=(T0 - timedelta(minutes=11)).replace(tzinfo=None)))
    await database.commit()
    await node_health.monitor_pass(database, T0, panel=panel, sender=sender)
    await node_health.monitor_pass(database, T0 + timedelta(minutes=1), panel=panel, sender=sender)
    agent_alerts = [t for t in sent if "Агент ноды" in t]
    assert len(agent_alerts) == 1 and "de-1" in agent_alerts[0]
    agent = await database.scalar(select(NodeAgent))
    agent.last_seen_at = T0.replace(tzinfo=None) + timedelta(minutes=2)
    await database.commit()
    await node_health.monitor_pass(database, T0 + timedelta(minutes=3), panel=panel, sender=sender)
    assert "снова на связи" in sent[-1]


@pytest.mark.asyncio
async def test_planned_restart_and_node_update_run_once_a_moscow_day(database, world):
    panel, sent, sender = world
    database.add(NodeAgent(name="de-1", token_hash="g" * 64, last_seen_at=T0.replace(tzinfo=None)))
    await database.commit()
    await node_health.nodes_health_config(node_health.MonitorConfigIn(scheduled_restart=True, restart_time="04:30", auto_update=True,
                                                                      update_time="05:00"), database, SimpleNamespace(email="a@b.c"))
    morning = datetime(2026, 10, 28, 1, 0, tzinfo=timezone.utc)  # 04:00 MSK
    assert (await node_health.monitor_pass(database, morning, panel=panel, sender=sender))["scheduled_restart"] is False
    out = await node_health.monitor_pass(database, morning + timedelta(hours=2), panel=panel, sender=sender)  # 06:00 MSK
    assert out["scheduled_restart"] is True and out["update_queued"] == 1 and panel.restart_all == 1
    again = await node_health.monitor_pass(database, morning + timedelta(hours=3), panel=panel, sender=sender)
    assert again["scheduled_restart"] is False and again["update_queued"] == 0 and panel.restart_all == 1
    assert [a.kind for a in (await database.execute(select(AgentAction))).scalars()] == ["update_node"]


@pytest.mark.asyncio
async def test_monitoring_can_be_switched_off(database, world):
    panel, sent, sender = world
    await node_health.nodes_health_config(node_health.MonitorConfigIn(enabled=False), database, SimpleNamespace(email="a@b.c"))
    for minutes in (0, 30):
        await node_health.monitor_pass(database, T0 + timedelta(minutes=minutes), panel=panel, sender=sender)
    assert panel.restarts == [] and sent == []


def test_node_controls_need_admin_rights():
    assert permissions("GET", "/api/admin/nodes/health") == {"ops.diagnostics"}
    assert permissions("PUT", "/api/admin/nodes/health/config") == {"settings.runtime.write"}
    assert permissions("POST", "/api/admin/nodes/{node_uuid}/restart") == {"provision_nodes"}
    assert permissions("POST", "/api/admin/nodes/update") == {"provision_nodes"}
