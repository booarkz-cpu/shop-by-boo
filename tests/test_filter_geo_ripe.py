"""v28.54: the ad / children's filter (squad swap and reconcile), GeoLite2 regions, RIPE Atlas checks feeding the
block monitor."""
import io
import tarfile
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import block_monitor as bm
from app import dns_filter as df
from app import geoip
from app import ripe_atlas as ra
from app.models import Subscription
from test_subscription_commerce import database  # noqa: F401

ADMIN = SimpleNamespace(email="owner@example.com")


class Panel:
    def __init__(self, squads=None):
        self.squads = squads or []
        self.patches = []

    async def get_user(self, uuid):
        return {"response": {"uuid": uuid, "activeInternalSquads": [{"uuid": s} for s in self.squads]}}

    async def patch_user(self, uuid, body):
        self.patches.append(body)
        self.squads = list(body["activeInternalSquads"])


def test_filter_squad_mapping():
    cfg = {"enabled": True, "squads": {"plan-a": {"ads": "a-ads"}, "*": {"ads": "x-ads", "kids": "x-kids"}}}
    assert df.filter_squad(cfg, "plan-a", "ads") == "a-ads"
    assert df.filter_squad(cfg, "plan-a", "kids") == "x-kids"
    assert df.filter_squad(cfg, "plan-b", "ads") == "x-ads"
    assert df.filter_squad(cfg, "plan-b", None) is None
    assert df.modes(cfg, "plan-a") == ["ads", "kids"] and df.modes({**cfg, "enabled": False}, "plan-a") == []


@pytest.mark.asyncio
async def test_customer_switches_filter_and_reconcile_restores_it(database, monkeypatch):  # noqa: F811
    db = database
    sub = await db.get(Subscription, 1)
    sub.remnawave_profile_id_snapshot = "plan-a"
    await db.commit()
    panel = Panel(["plan-a"])
    monkeypatch.setattr(df, "_panel", lambda: panel)
    with pytest.raises(HTTPException):
        await df.put_my_filter(df.FilterIn(mode="ads"), SimpleNamespace(), db)  # no squads yet
    await df.admin_filter_config(df.FilterConfigIn(enabled=True, squads={"*": {"ads": "x-ads", "kids": "x-kids"}}), db, ADMIN)
    view = await df.my_filter(SimpleNamespace(), None, db)
    assert view["enabled"] and [m["key"] for m in view["modes"]] == ["ads", "kids"]
    assert (await df.put_my_filter(df.FilterIn(mode="kids"), SimpleNamespace(), db))["mode"] == "kids"
    assert panel.squads == ["x-kids"]
    panel.squads = ["plan-a"]  # a renewal put the plan squad back
    assert await df.reconcile(db, panel) == 1 and panel.squads == ["x-kids"]
    assert await df.reconcile(db, panel) == 0
    await df.put_my_filter(df.FilterIn(mode=""), SimpleNamespace(), db)
    assert panel.squads == ["plan-a"] and (await db.get(Subscription, 1)).dns_filter is None
    with pytest.raises(HTTPException):
        await df.admin_filter_config(df.FilterConfigIn(squads={"*": {"porn": "y"}}), db, ADMIN)


@pytest.mark.asyncio
async def test_panel_error_keeps_the_old_choice(database, monkeypatch):  # noqa: F811
    db = database
    await df.admin_filter_config(df.FilterConfigIn(enabled=True, squads={"*": {"ads": "x-ads"}}), db, ADMIN)

    class Broken(Panel):
        async def patch_user(self, uuid, body):
            raise RuntimeError("panel down")
    monkeypatch.setattr(df, "_panel", lambda: Broken())
    with pytest.raises(HTTPException) as exc:
        await df.put_my_filter(df.FilterIn(mode="ads"), SimpleNamespace(), db)
    assert exc.value.status_code == 502 and (await db.get(Subscription, 1)).dns_filter is None


def _archive(payload: bytes) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo("GeoLite2-City_20261027/GeoLite2-City.mmdb")
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
    return buf.getvalue()


@pytest.mark.asyncio
async def test_geoip_key_update_and_region(database, monkeypatch, tmp_path):  # noqa: F811
    db = database
    monkeypatch.setenv("GEOIP_DIR", str(tmp_path))
    assert geoip.region("8.8.8.8") == ""  # no database: no regions
    with pytest.raises(HTTPException):
        await geoip.update(db)
    state = await geoip.put_geoip(geoip.GeoIpIn(account_id="12345", license_key="secret-key"), db, ADMIN)
    assert state["key_set"] and "secret" not in str(state)
    seen = []

    async def fetch(account, key):
        seen.append((account, key))
        return _archive(b"MMDB-BYTES")
    state = await geoip.update(db, fetch)
    assert seen == [("12345", "secret-key")] and state["database"] and (tmp_path / "GeoLite2-City.mmdb").read_bytes() == b"MMDB-BYTES"

    class Reader:
        def get(self, ip):
            return {"subdivisions": [{"names": {"ru": "Москва", "en": "Moscow"}}]} if ip == "77.88.8.8" else None
    monkeypatch.setattr(geoip, "_open", lambda: Reader())
    assert geoip.region("77.88.8.8") == "Москва" and geoip.region("1.1.1.1") == ""
    with pytest.raises(Exception):  # noqa: B017 — a broken archive
        geoip.extract(_archive(b"x")[:20])

    async def bad(account, key):
        raise ValueError("MaxMind не принял ID аккаунта или ключ")
    with pytest.raises(HTTPException):
        await geoip.update(db, bad)
    assert "MaxMind" in (await geoip.get_geoip(db, ADMIN))["error"]


def test_ripe_targets_and_verdict():
    assert ra.host_port("https://api.example.com/health/live") == ("api.example.com", 443)
    assert ra.host_port("tcp://203.0.113.7:8443") == ("203.0.113.7", 8443)
    assert ra.host_port("udp://x") is None
    defs = ra.definitions([{"target": "tcp://203.0.113.7:8443", "label": "DE-1"}])
    assert defs[0]["type"] == "sslcert" and defs[0]["port"] == 8443 and defs[0]["is_oneoff"]
    assert ra.verdict([{"cert": ["x"]}, {"err": "timeout"}, {"alert": 40}], 0.5) == (False, 1, 3)
    assert ra.verdict([{"cert": ["x"]}, {"cert": ["y"]}, {"err": "x"}], 0.5) == (True, 2, 3)


@pytest.mark.asyncio
async def test_ripe_passes_feed_the_block_monitor(database, monkeypatch):  # noqa: F811
    db = database
    known = [{"target": "tcp://203.0.113.7:443", "kind": "node", "label": "DE-1", "node_uuid": "n1", "node_online": True}]

    async def targets(session, config=None):
        return known
    monkeypatch.setattr(bm, "targets", targets)
    reacted = []

    async def react(session, config, state, k, panel=None):
        reacted.append(sorted(state.get("blocked", {})))
        return {}
    monkeypatch.setattr(bm, "react", react)
    await bm.put_monitor(bm.ConfigIn(enabled=True, fail_streak=2), db, ADMIN)
    assert await ra.tick(db) == "off"
    with pytest.raises(HTTPException):
        await ra.put_ripe(ra.RipeIn(enabled=True), db, ADMIN)
    await ra.put_ripe(ra.RipeIn(enabled=True, api_key="atlas-key", probes=3, interval_hours=1, wait_minutes=10), db, ADMIN)
    calls = []

    async def call(method, path, key, body=None):
        calls.append((method, path, key))
        if method == "POST":
            assert body["probes"][0] == {"type": "country", "value": "RU", "requested": 3}
            return {"measurements": [101]}
        return [{"err": "connect: timeout"}, {"err": "reset"}, {"cert": ["c"]}]
    now = datetime.utcnow()
    for cycle in range(2):
        start = now + timedelta(hours=2 * cycle)
        assert await ra.tick(db, start, call) == "started"
        assert await ra.tick(db, start + timedelta(minutes=5), call) == "waiting"
        assert await ra.tick(db, start + timedelta(minutes=11), call) == "collected"
    assert calls[0] == ("POST", "/measurements/", "atlas-key") and calls[1][1] == "/measurements/101/results/?format=json"
    state = await bm._load(db, bm.STATE_KEY, {})
    assert "tcp://203.0.113.7:443" in state["blocked"] and state["blocked"]["tcp://203.0.113.7:443"]["regions"] == ["RU (RIPE Atlas)"]
    assert reacted[-1] == ["tcp://203.0.113.7:443"]
    probes = await bm._load(db, bm.PROBES_KEY, {})
    assert probes["ripe-atlas-ru"]["virtual"] and probes["ripe-atlas-ru"]["stale_minutes"] == 130
    shown = await ra.get_ripe(db, ADMIN)
    assert shown["key_set"] and "api_key" not in shown and shown["last_results"]["tcp://203.0.113.7:443"]["ok"] == 1
