"""Админ-панель → агент автообновления: панель пишет запрос, агент его принимает, панель показывает состояние."""
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app import auto_update_api as api

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 27, 9, 0, tzinfo=timezone.utc)
ADMIN = SimpleNamespace(email="owner@example.com")


class FakeDb:
    def __init__(self):
        self.commits = 0

    async def commit(self):
        self.commits += 1


@pytest.fixture
def audits(monkeypatch):
    records = []

    async def fake_audit(db, action, actor, target=None, details=None):
        records.append((action, actor, details))
    import app.main as main
    monkeypatch.setattr(main, "audit", fake_audit)
    return records


@pytest.fixture
def control(tmp_path, monkeypatch, audits):
    folder = tmp_path / "control"
    folder.mkdir()
    monkeypatch.setenv("AUTO_UPDATE_CONTROL_DIR", str(folder))
    return folder


def agent_status(folder, **fields):
    data = {"agent_seen_at": NOW.isoformat(), "installed": "28.33.0", "enabled": True, "time": "03:00"}
    data.update(fields)
    (folder / "auto-update.status.json").write_text(json.dumps(data))


def test_without_the_agent_the_panel_explains_how_to_install_it(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTO_UPDATE_CONTROL_DIR", str(tmp_path / "missing"))
    state = api.read_state(NOW)
    assert (state["available"], state["agent_alive"]) == (False, False)
    assert "auto-update.sh install" in state["setup_hint"]
    with pytest.raises(HTTPException) as err:
        api.write_request({"enabled": False}, "a@b.c")
    assert err.value.status_code == 503


def test_a_silent_agent_is_reported_as_not_running(control):
    agent_status(control, agent_seen_at=(NOW - timedelta(minutes=12)).isoformat())
    state = api.read_state(NOW)
    assert state["available"] and not state["agent_alive"] and state["setup_hint"]
    agent_status(control)
    assert api.read_state(NOW)["agent_alive"] is True
    assert api.read_state(NOW)["status"]["installed"] == "28.33.0"


def test_schedule_time_must_be_hh_mm():
    assert api.AutoUpdateIn(enabled=True, time="04:30").time == "04:30"
    for bad in ("4:30", "24:00", "03:60", "03:00; reboot"):
        with pytest.raises(ValidationError):
            api.AutoUpdateIn(enabled=True, time=bad)


@pytest.mark.asyncio
async def test_settings_are_written_for_the_agent_and_audited(control, audits):
    agent_status(control)
    db = FakeDb()
    state = await api.put_auto_update(api.AutoUpdateIn(enabled=False, time="05:15"), db, ADMIN)
    request = json.loads((control / "auto-update.request.json").read_text())
    assert (request["enabled"], request["time"], request["updated_by"]) == (False, "05:15", ADMIN.email)
    assert state["request"]["time"] == "05:15"
    assert audits == [("auto_update.settings", ADMIN.email, {"enabled": False, "time": "05:15"})]
    assert db.commits == 1


@pytest.mark.asyncio
async def test_update_now_is_requested_once_until_the_agent_takes_it(control, audits):
    agent_status(control)
    first = await api.run_auto_update(FakeDb(), ADMIN)
    assert first["pending_run"] is True and first["requested"]
    with pytest.raises(HTTPException) as err:
        await api.run_auto_update(FakeDb(), ADMIN)
    assert err.value.status_code == 409
    # The agent took the request and is installing: still 409, now because it is running.
    agent_status(control, handled_check_now=first["requested"], running=True)
    with pytest.raises(HTTPException) as err:
        await api.run_auto_update(FakeDb(), ADMIN)
    assert "уже идёт" in err.value.detail
    agent_status(control, handled_check_now=first["requested"], running=False, last_result="updated")
    assert api.read_state()["pending_run"] is False
    assert [a[0] for a in audits] == ["auto_update.run_requested"]


@pytest.mark.asyncio
async def test_the_agent_accepts_what_the_panel_writes(control, monkeypatch):
    spec = importlib.util.spec_from_file_location("auto_update_for_panel", ROOT / "scripts/auto_update.py")
    agent = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(agent)
    monkeypatch.setattr(agent, "REQUEST", control / "auto-update.request.json")
    await api.put_auto_update(api.AutoUpdateIn(enabled=True, time="02:45"), FakeDb(), ADMIN)
    result = await api.run_auto_update(FakeDb(), ADMIN)
    assert agent.read_request() == {"enabled": True, "time": "02:45", "check_now": result["requested"]}


def test_only_admins_change_settings_operators_may_look():
    from app.security import PERMISSIONS
    assert "ops.releases" in PERMISSIONS["operator"]
    assert "settings.runtime.write" not in PERMISSIONS["operator"]
    assert "settings.runtime.write" in PERMISSIONS["admin"]
    routes = {(r.path, m) for r in api.router.routes for m in r.methods}
    assert {("/api/admin/auto-update", "GET"), ("/api/admin/auto-update", "PUT"), ("/api/admin/auto-update/run", "POST")} <= routes
