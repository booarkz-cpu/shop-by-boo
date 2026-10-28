"""Block monitor: probes in a region report, a target failing for every fresh probe of a region is blocked (not when
the shop sees it down), the signed mirror list puts it last, alerts go out and the reserve squad follows."""
import importlib.util
import socket
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Response
from starlette.requests import Request

from app import block_monitor as bm
from app import mobile_mirrors, node_health
from app.config import settings
from test_subscription_commerce import database  # noqa: F401

ADMIN = SimpleNamespace(email="owner@corgi.test")
ROOT = Path(__file__).resolve().parents[1]
NODES = {"nodes": [{"uuid": "n1", "name": "Германия", "address": "de.corgi.test", "status": "online"},
                   {"uuid": "n2", "name": "Финляндия", "address": "fi.corgi.test", "status": "offline"}]}


def probe_request(token):
    return Request({"type": "http", "method": "GET", "path": "/api/probe/targets", "client": ("5.5.5.5", 1), "query_string": b"",
                    "headers": [(b"authorization", f"Bearer {token}".encode())]})


@pytest.fixture
def env(database, monkeypatch):
    async def snapshot():
        return NODES

    async def quiet(*a, **k):
        return None
    monkeypatch.setattr(node_health, "node_snapshot", snapshot)
    monkeypatch.setattr(settings, "api_domain", "api.corgi.test")
    monkeypatch.setattr(settings, "api_mirror_domains", "api2.corgi.test")
    import app.main as main
    monkeypatch.setattr(main, "audit", quiet)
    published = []

    async def publish(db, client=None):
        published.append(True)
        return await mobile_mirrors.load(db)
    monkeypatch.setattr(mobile_mirrors, "publish", publish)
    return SimpleNamespace(db=database, published=published)


async def report(db, token, failing):
    pid, _ = await bm._probe(probe_request(token), db)
    known = (await bm.probe_targets(probe_request(token), db))["targets"]
    return await bm.apply_report(db, pid, [bm.ResultIn(target=t, ok=t not in failing, ms=10) for t in known])


@pytest.mark.asyncio
async def test_a_target_blocked_for_the_whole_region_is_acted_on(env):
    db = env.db
    await bm.put_monitor(bm.ConfigIn(enabled=True, fail_streak=3), db, ADMIN)
    one = await bm.add_probe(bm.ProbeIn(name="Москва", region="RU"), db, ADMIN)
    two = await bm.add_probe(bm.ProbeIn(name="Питер", region="RU"), db, ADMIN)
    assert one["token"] not in str(await bm._load(db, bm.PROBES_KEY, {})), "only a hash of the token is stored"
    assert "corgi-probe install" in one["install"] and one["token"] in one["install"]
    with pytest.raises(HTTPException):
        await bm.probe_targets(probe_request("wrong"), db)
    targets = (await bm.probe_targets(probe_request(one["token"]), db))["targets"]
    assert targets == ["https://api.corgi.test/health/live", "https://api2.corgi.test/health/live",
                       "tcp://de.corgi.test:443", "tcp://fi.corgi.test:443"]
    api, node, down_node = targets[0], "tcp://de.corgi.test:443", "tcp://fi.corgi.test:443"
    for _ in range(3):
        await report(db, one["token"], {api, node, down_node})
        out = await report(db, two["token"], {api, down_node})
    assert out["blocked"] == [api], "the node works for one probe of the region; Remnawave says Финляндия is down, not blocked"
    assert env.published, "the reserve list is republished"
    doc = await mobile_mirrors.public_mirrors(Response(), db)
    assert mobile_mirrors.verify(doc, doc["key"])["mirrors"] == ["https://api2.corgi.test", "https://api.corgi.test"]
    alerts = await bm.problems(db)
    assert len(alerts) == 1 and "RU" in alerts[0][1] and "резервный адрес" in alerts[0][2]
    # The block ends: one good round clears it.
    await report(db, one["token"], set())
    assert (await report(db, two["token"], set()))["blocked"] == []


@pytest.mark.asyncio
async def test_while_a_node_is_blocked_everyone_gets_the_reserve_squad(env, monkeypatch):
    db = env.db
    calls = []

    class Panel:
        async def squad_add_all_users(self, squad):
            calls.append(("add", squad))

        async def squad_remove_all_users(self, squad):
            calls.append(("remove", squad))
    from app import remnawave
    monkeypatch.setattr(remnawave, "RemnawaveClient", Panel)
    await bm.put_monitor(bm.ConfigIn(enabled=True, fail_streak=1, fallback_squad_uuid="aaaa-bbbb", auto_fallback_squad=True), db, ADMIN)
    probe = await bm.add_probe(bm.ProbeIn(name="Москва", region="RU"), db, ADMIN)
    await report(db, probe["token"], {"tcp://de.corgi.test:443"})
    assert calls == [("add", "aaaa-bbbb")]
    assert (await bm.get_monitor(db, ADMIN))["fallback_active"] is True
    await report(db, probe["token"], set())
    assert calls == [("add", "aaaa-bbbb"), ("remove", "aaaa-bbbb")]


@pytest.mark.asyncio
async def test_a_disabled_monitor_only_records(env):
    db = env.db
    probe = await bm.add_probe(bm.ProbeIn(name="Москва", region="RU"), db, ADMIN)
    await bm.put_monitor(bm.ConfigIn(enabled=False, fail_streak=1), db, ADMIN)
    await report(db, probe["token"], {"https://api.corgi.test/health/live"})
    assert not env.published and await bm.problems(db) == []
    await bm.delete_probe(probe["id"], db, ADMIN)
    with pytest.raises(HTTPException):
        await bm.probe_targets(probe_request(probe["token"]), db)


def test_the_probe_checks_tcp_and_reports_failures():
    spec = importlib.util.spec_from_file_location("probe", ROOT / "scripts/block-probe.py")
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen()
    port = server.getsockname()[1]
    try:
        assert probe.check(f"tcp://127.0.0.1:{port}")["ok"] is True
    finally:
        server.close()
    failed = probe.check(f"tcp://127.0.0.1:{port}")
    assert failed["ok"] is False and failed["error"]
    assert probe.check("ftp://x")["ok"] is False
