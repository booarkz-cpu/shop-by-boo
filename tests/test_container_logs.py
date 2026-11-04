"""v28.75.0 (stage 16): container logs in the browser through the auto-update agent.

* the panel writes a request for one service of a closed list; the agent runs ``docker compose logs`` for it once,
  masks secret values of .env and writes the tail into .control/logs/;
* the backend reads the result back; a service outside the list is refused on both sides;
* the backend and the agent list the same services."""
import importlib.util
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app import container_logs

ROOT = Path(__file__).resolve().parents[1]
SECRET = "s3cr3t-telegram-token-value"


@pytest.fixture
def agent(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("auto_update_logs_test", ROOT / "scripts/auto_update.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    app = tmp_path / "app"
    app.mkdir()
    (app / ".env").write_text(f'BOT_TOKEN="{SECRET}"\nADMIN_DOMAIN=admin.example.com\nSHORT_KEY=abc\n')
    control = app / ".control"
    control.mkdir()
    monkeypatch.setattr(mod, "APP_DIR", app)
    monkeypatch.setattr(mod, "LOGS_REQUEST", control / "logs.request.json")
    monkeypatch.setattr(mod, "LOGS_DIR", control / "logs")
    runs = []

    def fake_run(cmd, **kw):
        runs.append(cmd)
        return type("P", (), {"returncode": 0, "stdout": f"2026-11-04T10:00:00Z started with token {SECRET} on admin.example.com\n",
                              "stderr": ""})()
    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setenv("AUTO_UPDATE_CONTROL_DIR", str(control))
    mod.runs, mod.control = runs, control
    return mod


def test_same_services_on_both_sides():
    spec = importlib.util.spec_from_file_location("auto_update_services", ROOT / "scripts/auto_update.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert tuple(mod.LOG_SERVICES) == container_logs.SERVICES
    with pytest.raises(ValidationError):
        container_logs.LogsIn(service="../../etc/passwd")


@pytest.mark.asyncio
async def test_request_agent_and_read_back(agent, monkeypatch):
    from types import SimpleNamespace

    from unittest.mock import AsyncMock
    import app.main as shop
    monkeypatch.setattr(shop, "audit", AsyncMock())
    db = SimpleNamespace(commit=AsyncMock())
    out = await container_logs.request_logs(container_logs.LogsIn(service="bot", lines=50), db, SimpleNamespace(email="owner@corgi.test"))
    assert (await container_logs.get_logs("bot", None))["pending"]
    agent.handle_logs()
    assert agent.runs == [["docker", "compose", "logs", "--no-color", "--timestamps", "--tail", "50", "bot"]]
    agent.handle_logs()  # the same request runs once
    assert len(agent.runs) == 1
    got = await container_logs.get_logs("bot", None)
    assert not got["pending"] and got["lines"] == 50 and got["at"]
    assert SECRET not in got["text"] and "***" in got["text"] and "admin.example.com" in got["text"]  # only secret-looking values
    assert out["service"] == "bot"


def test_agent_ignores_a_service_outside_the_list(agent):
    agent.LOGS_REQUEST.write_text(json.dumps({"service": "sh -c id", "mark": "x1", "lines": 10}))
    agent.handle_logs()
    assert agent.runs == []
