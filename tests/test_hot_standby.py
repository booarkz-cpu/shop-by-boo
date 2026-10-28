"""Hot standby: replication is read from PostgreSQL itself, alerts when the standby is expected but not streaming,
falls behind, holds WAL or stops reporting; the agent's heartbeat needs its token; scripts stay self-contained."""
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app import hot_standby as hs
from app.config import settings
from test_subscription_commerce import database  # noqa: F401

ADMIN = SimpleNamespace(email="owner@corgi.test")
ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 28, 12, 0)


def beat_request(token):
    return Request({"type": "http", "method": "POST", "path": "/api/standby/heartbeat", "client": ("7.7.7.7", 1), "query_string": b"",
                    "headers": [(b"authorization", f"Bearer {token}".encode())]})


def test_assess_rules():
    off = {"enabled": False}
    assert hs.assess(off, {"supported": True, "replicas": []}, {}, NOW) == []
    on = {"enabled": True, "lag_alert_seconds": 60}
    fresh = {"at": (NOW - timedelta(minutes=1)).isoformat()}
    keys = [k for k, *_ in hs.assess(on, {"supported": True, "in_recovery": False, "replicas": [], "slots": []}, fresh, NOW)]
    assert keys == ["standby:down"]
    repl = {"supported": True, "in_recovery": False,
            "replicas": [{"address": "10.0.0.2", "state": "streaming", "lag_seconds": 120.0, "behind_bytes": 1}],
            "slots": [{"name": "old", "active": False, "retained_bytes": 6 * 1024 ** 3}]}
    found = {k: s for k, _, _, s in hs.assess(on, repl, {}, NOW)}
    assert found == {"standby:lag:10.0.0.2": "high", "standby:slot:old": "high", "standby:agent": "medium"}
    healthy = {**repl, "replicas": [{**repl["replicas"][0], "lag_seconds": 2.0}], "slots": []}
    assert hs.assess(on, healthy, fresh, NOW) == []
    failed = {**fresh, "drill": {"ok": False, "error": "no-space"}, "files": {"ok": False, "error": "ключ не настроен"}}
    assert {k for k, *_ in hs.assess(on, healthy, failed, NOW)} == {"standby:drill", "standby:files"}
    passed = {**fresh, "drill": {"ok": True, "users": 10}, "files": {"ok": True}}
    assert hs.assess(on, healthy, passed, NOW) == []
    # On the standby itself (in recovery) there are no replicas to expect.
    assert hs.assess(on, {"supported": True, "in_recovery": True, "replicas": [], "slots": []}, fresh, NOW) == []


@pytest.mark.asyncio
async def test_heartbeat_token_admin_view_and_alerts(database, monkeypatch):
    db = database

    async def quiet(*a, **k):
        return None
    import app.main as main
    monkeypatch.setattr(main, "audit", quiet)
    monkeypatch.setattr(settings, "api_domain", "api.corgi.test")
    payload = hs.HeartbeatIn(in_recovery=True, lag_seconds=1.5, primary_ok=True)
    with pytest.raises(HTTPException):
        await hs.heartbeat(payload, beat_request("anything"), db)  # no token issued yet
    issued = await hs.new_token(db, ADMIN)
    assert "corgi-standby install" in issued["install"] and issued["token"] in issued["install"]
    assert issued["token"] not in str(await hs._load(db, hs.CONFIG_KEY, {})), "only the hash is stored"
    with pytest.raises(HTTPException):
        await hs.heartbeat(payload, beat_request("wrong"), db)
    assert (await hs.heartbeat(payload, beat_request(issued["token"]), db))["ok"]
    await hs.put_standby(hs.ConfigIn(enabled=True, lag_alert_seconds=120), db, ADMIN)
    view = await hs.get_standby(db, ADMIN)
    assert view["token_set"] and "token_sha" not in view["config"] and view["heartbeat_fresh"]
    assert view["heartbeat"]["lag_seconds"] == 1.5
    keys = [p["key"] for p in view["problems"]]
    if view["replication"]["supported"]:  # PostgreSQL run: the real catalog says nobody streams
        assert view["replication"]["in_recovery"] is False and keys == ["standby:down"]
    else:
        assert keys == []
    from app import ops_alerts
    collected = [p.key for p in await ops_alerts.collect(db)]
    assert ("standby:down" in collected) == bool(view["replication"]["supported"])
    ready = {c["key"]: c for c in (await ops_alerts.readiness(db, None))["checks"]}
    assert ready["hot_standby"]["ok"] is False and ready["hot_standby"]["level"] == "recommended"


def test_scripts_are_valid_and_keep_secrets_out():
    subprocess.run(["bash", "-n", str(ROOT / "scripts/hot-standby.sh")], check=True)
    agent = (ROOT / "scripts/standby-agent.py").read_text()
    compile(agent, "standby-agent.py", "exec")
    assert "import requests" not in agent, "standard library only"
    assert "pg_basebackup" in agent and "5499" in agent and "rm -rf" in agent, "the drill uses a throwaway copy on a side port"
    script = (ROOT / "scripts/hot-standby.sh").read_text()
    for needed in ("hostssl replication", "DOCKER-USER", "pg_basebackup", "pg_promote", "sslmode=require", "/root/corgi-standby.secret",
                   "support_db", "rrsync -ro", "restrict", "files-sync"):
        assert needed in script
    assert "docker-compose.override.yml" in (ROOT / ".gitignore").read_text()
