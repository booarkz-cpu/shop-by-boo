"""BitTorrent detection: Xray access-log counting on the node, hourly counters, abuse scoring, notices and retention."""
import importlib.util
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app import platform_api, torrent_detection as torrent
from app.models import AbuseViolation, AppSetting, NodeAgent, Notification, PlatformPlugin, Subscription, TorrentDetection
from test_subscription_commerce import database

TOKEN = "torrent-agent-token-0123456789abcdef"


def load_agent():
    spec = importlib.util.spec_from_file_location("node_agent_torrent", Path(__file__).resolve().parents[1] / "scripts/node-agent.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def line(client, route="VLESS_TCP_REALITY >> TORRENT", dest="tcp:198.51.100.20:6881", src="203.0.113.7:51234"):
    return f"2026/10/23 10:00:00.123456 from {src} accepted {dest} [{route}] email: {client}\n"


# ---------------------------------------------------------------- agent

def test_access_log_counts_only_torrent_routed_lines_and_follows_rotation(tmp_path):
    agent = load_agent()
    log_file = tmp_path / "access.log"
    log_file.write_text(line("user_1") * 5)
    reader = agent.XrayAccessLog(str(log_file), "TORRENT")
    assert reader.poll() == {}, "starts at the end: old lines are not re-counted"
    with log_file.open("a") as handle:
        handle.write(line("user_1") + line("user_1", route="VLESS -> TORRENT") + line("user_2", dest="udp:198.51.100.21:51413"))
        handle.write(line("user_3", route="VLESS >> DIRECT") + line("user_4", route="VLESS >> TORRENT_EXTRA"))
        handle.write("2026/10/23 10:00:01 from 203.0.113.9:1 rejected  proxy/vless: invalid user\n")
        handle.write(line("user_5").rstrip("\n"))  # unfinished line
    assert reader.poll() == {"user_1": 2, "user_2": 1}
    with log_file.open("a") as handle:
        handle.write("\n")
    assert reader.poll() == {"user_5": 1}, "the unfinished line is counted once it is complete"
    log_file.rename(tmp_path / "access.log.1")
    log_file.write_text(line("user_6") + line("user_6"))
    assert reader.poll() == {"user_6": 2}, "a rotated log is read from its start"
    log_file.write_text("")
    with log_file.open("a") as handle:
        handle.write(line("user_7"))
    assert reader.poll() == {"user_7": 1}, "a truncated log is read again"
    assert agent.XrayAccessLog(str(tmp_path / "missing.log"), "TORRENT").poll() == {}


def test_report_keeps_counts_when_the_shop_is_unreachable(tmp_path, monkeypatch):
    agent = load_agent()
    log_file = tmp_path / "access.log"
    log_file.write_text("")
    reader = agent.XrayAccessLog(str(log_file), "TORRENT")
    reader.poll()
    sent = []

    def down(base, path, token, body):
        raise agent.urllib.error.URLError("down")

    monkeypatch.setattr(agent, "_post", down)
    log_file.write_text(line("user_1") * 3)
    pending = {}
    with pytest.raises(agent.urllib.error.URLError):
        agent.torrent_report("https://shop", TOKEN, reader, pending)
    assert pending == {"user_1": 3}
    monkeypatch.setattr(agent, "_post", lambda base, path, token, body: sent.append((path, body)) or {})
    with log_file.open("a") as handle:
        handle.write(line("user_1"))
    assert agent.torrent_report("https://shop", TOKEN, reader, pending) == {}
    assert sent == [("/api/agent/torrent", {"items": [{"client": "user_1", "events": 4}]})]
    assert all("198.51.100" not in json.dumps(body) for _, body in sent), "no destinations leave the node"


# ---------------------------------------------------------------- shop

async def make_agent(database):
    agent = NodeAgent(name="nl-1", token_hash=platform_api._hash(TOKEN), enabled=True, created_at=datetime.utcnow())
    database.add(agent)
    await database.commit()
    return agent


@pytest.mark.asyncio
async def test_counts_resolve_clients_and_notify_once_a_day(database):
    agent = await make_agent(database)
    sub = await database.get(Subscription, 1)
    batch = torrent.TorrentBatch(items=[{"client": "user_1", "events": 3}, {"client": "user_1", "events": 2},
                                        {"client": "remote-1", "events": 1}, {"client": "user_999", "events": 4}, {"client": "someone", "events": 1}])
    assert sub.remnawave_uuid == "remote-1"
    result = await torrent.agent_torrent(batch, database, TOKEN)
    assert result == {"ok": True, "accepted": 4, "matched": 1, "enabled": True}
    rows = {r.client: r for r in (await database.scalars(select(TorrentDetection))).all()}
    assert rows["user_1"].events == 5 and rows["user_1"].user_id == 1
    assert rows["remote-1"].user_id == 1, "a Remnawave UUID in the email field is resolved too"
    assert rows["user_999"].user_id is None and rows["someone"].user_id is None
    assert rows["user_1"].hour.minute == 0 and rows["user_1"].agent_id == agent.id
    await torrent.agent_torrent(torrent.TorrentBatch(items=[{"client": "user_1", "events": 1}]), database, TOKEN)
    assert (await database.get(TorrentDetection, rows["user_1"].id)).events == 6, "the hourly bucket grows"
    notices = (await database.scalars(select(Notification).where(Notification.kind == "abuse.torrent"))).all()
    assert len(notices) == 1 and notices[0].user_id == 1, "one notice per day"
    assert "198.51.100" not in notices[0].body
    columns = set(TorrentDetection.__table__.columns.keys())
    assert columns == {"id", "hour", "agent_id", "client", "user_id", "events"}, "only counters are stored"


@pytest.mark.asyncio
async def test_notices_can_be_switched_off_and_the_module_disabled(database):
    await make_agent(database)
    from types import SimpleNamespace

    await torrent.admin_torrents_notify(torrent.NotifyIn(notify=False), database, SimpleNamespace(email="admin@example.test"))
    await torrent.agent_torrent(torrent.TorrentBatch(items=[{"client": "user_1", "events": 1}]), database, TOKEN)
    assert await database.scalar(select(func.count()).select_from(Notification).where(Notification.kind == "abuse.torrent")) == 0
    database.add(PlatformPlugin(key="torrents", enabled=False))
    await database.commit()
    result = await torrent.agent_torrent(torrent.TorrentBatch(items=[{"client": "user_1", "events": 9}]), database, TOKEN)
    assert result == {"ok": True, "accepted": 0, "enabled": False}
    assert await database.scalar(select(func.sum(TorrentDetection.events))) == 1


@pytest.mark.asyncio
async def test_detection_raises_the_abuse_score_for_a_day(database):
    await make_agent(database)
    database.add(AppSetting(key="abuse_policy", value=json.dumps({"min_score": 30})))
    await database.commit()
    observation = platform_api.ObservationBatch(items=[{"ip": "93.184.216.34", "remnawave_uuid": "remote-1"}])
    assert (await platform_api.agent_observations(observation, database, TOKEN))["scored"] == 0
    await torrent.agent_torrent(torrent.TorrentBatch(items=[{"client": "user_1", "events": 2}]), database, TOKEN)
    assert (await platform_api.agent_observations(observation, database, TOKEN))["scored"] == 1
    violation = await database.scalar(select(AbuseViolation).order_by(AbuseViolation.id.desc()))
    assert violation.user_id == 1 and any(h["name"] == "torrent" for h in violation.analyzers["hits"])
    for row in (await database.scalars(select(TorrentDetection))).all():
        row.hour = row.hour - timedelta(hours=30)
    await database.commit()
    assert (await platform_api.agent_observations(observation, database, TOKEN))["scored"] == 0, "the mark expires after 24 hours"


@pytest.mark.asyncio
async def test_overview_and_retention(database):
    await make_agent(database)
    await torrent.agent_torrent(torrent.TorrentBatch(items=[{"client": "user_1", "events": 7}, {"client": "stranger", "events": 2}]), database, TOKEN)
    view = await torrent.admin_torrents(30, database, None)
    assert view["enabled"] and view["notify"] and view["total"] == 9
    assert view["clients"][0]["client"] == "user_1" and view["clients"][0]["user"] == "Owner" and view["clients"][0]["events"] == 7
    assert view["nodes"] == [{"agent_id": view["nodes"][0]["agent_id"], "node": "nl-1", "events": 9}]
    old = TorrentDetection(hour=torrent.hour_of(datetime.utcnow() - timedelta(days=31)), agent_id=1, client="user_1", user_id=1, events=5)
    database.add(old)
    await database.commit()
    assert await torrent.enforce_retention(database) == 1
    assert await database.scalar(select(func.sum(TorrentDetection.events))) == 9
