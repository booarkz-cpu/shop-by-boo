"""Агент автообновления на сервере (scripts/auto_update.py): настройки из админ-панели, «Обновить сейчас»,
защита от повторной установки неудачного выпуска, состояние для панели. systemd и обновление подменены."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def agent(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("auto_update_under_test", ROOT / "scripts/auto_update.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    app = tmp_path / "app"
    (app / "scripts").mkdir(parents=True)
    (app / ".env").write_text("BOT_TOKEN=\n")
    for name, value in {"APP_DIR": app, "CONF_DIR": tmp_path / "etc", "SYSTEMD_DIR": tmp_path / "systemd",
                        "CONTROL_DIR": app / ".control"}.items():
        monkeypatch.setattr(mod, name, value)
    (tmp_path / "systemd").mkdir()
    monkeypatch.setattr(mod, "CONFIG", mod.CONF_DIR / "auto-update.json")
    monkeypatch.setattr(mod, "FAILED", mod.CONF_DIR / "auto-update.failed")
    monkeypatch.setattr(mod, "HANDLED", mod.CONF_DIR / "auto-update.handled")
    monkeypatch.setattr(mod, "REQUEST", mod.CONTROL_DIR / "auto-update.request.json")
    monkeypatch.setattr(mod, "STATUS", mod.CONTROL_DIR / "auto-update.status.json")
    calls = []
    monkeypatch.setattr(mod, "systemctl", lambda *a: calls.append(a) or type("R", (), {"stdout": "Wed 2026-10-28 03:07:00 MSK"})())
    state = {"installed": "28.33.0", "latest": "28.34.0", "result": 0, "runs": 0}
    monkeypatch.setattr(mod, "installed_version", lambda: state["installed"])
    monkeypatch.setattr(mod, "latest_release", lambda: state["latest"])
    notes = []
    monkeypatch.setattr(mod, "notify", notes.append)

    def fake_run(cmd, **kw):
        state["runs"] += 1
        if state["result"] == 0:
            state["installed"] = state["latest"]
        return type("P", (), {"returncode": state["result"], "stdout": "Проверен релиз\nUpdate completed.\n", "stderr": ""})()
    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    mod.calls, mod.state, mod.notes = calls, state, notes
    return mod


def status(mod):
    return json.loads(mod.STATUS.read_text())


def request(mod, **fields):
    mod.CONTROL_DIR.mkdir(parents=True, exist_ok=True)
    mod.REQUEST.write_text(json.dumps(fields))


def test_install_writes_units_and_turns_on_both_timers(agent):
    agent.cmd_install()
    timer = (agent.SYSTEMD_DIR / "vpn-shop-update.timer").read_text()
    assert "OnCalendar=*-*-* 03:00:00 Europe/Moscow" in timer
    assert "python3" in (agent.SYSTEMD_DIR / "vpn-shop-update-agent.service").read_text()
    assert ("enable", "--now", "vpn-shop-update-agent.timer") in agent.calls
    assert ("enable", "vpn-shop-update.timer") in agent.calls
    assert status(agent)["enabled"] is True and status(agent)["installed"] == "28.33.0"


def test_panel_changes_time_and_switches_off(agent):
    agent.cmd_install()
    request(agent, enabled=False, time="05:30")
    agent.cmd_agent()
    assert json.loads(agent.CONFIG.read_text()) == {"enabled": False, "time": "05:30"}
    assert "05:30:00" in (agent.SYSTEMD_DIR / "vpn-shop-update.timer").read_text()
    assert ("disable", "--now", "vpn-shop-update.timer") in agent.calls
    assert status(agent)["enabled"] is False and status(agent)["next_run"] is None
    assert agent.state["runs"] == 0, "changing settings does not update"


def test_only_known_and_valid_fields_are_accepted(agent):
    agent.cmd_install()
    request(agent, enabled="yes", time="25:00; rm -rf /", check_now="x; reboot", command="reboot")
    agent.cmd_agent()
    assert json.loads(agent.CONFIG.read_text()) == {"enabled": True, "time": "03:00"}
    assert agent.state["runs"] == 0


def test_update_now_runs_once_per_request(agent):
    agent.cmd_install()
    request(agent, check_now="2026-10-27T12:00:00Z")
    agent.cmd_agent()
    agent.cmd_agent()
    assert agent.state["runs"] == 1, "the same request is handled once"
    s = status(agent)
    assert (s["last_result"], s["installed"], s["trigger"], s["running"]) == ("updated", "28.34.0", "panel", False)
    assert s["handled_check_now"] == "2026-10-27T12:00:00Z"
    assert agent.notes and "28.33.0 → 28.34.0" in agent.notes[0]
    request(agent, check_now="2026-10-27T12:05:00Z")
    agent.cmd_agent()
    assert agent.state["runs"] == 2 and status(agent)["last_result"] == "current"


def test_a_failed_release_is_not_retried_every_night(agent):
    agent.cmd_install()
    agent.state["result"] = 1
    assert agent.run_update() == "failed"
    assert agent.FAILED.read_text() == "28.34.0" and status(agent)["last_result"] == "failed"
    assert "не удалось" in agent.notes[-1]
    assert agent.run_update() == "skipped" and agent.state["runs"] == 1, "the nightly run waits for a newer release"
    agent.state["latest"] = "28.34.1"
    agent.state["result"] = 0
    assert agent.run_update() == "updated" and not agent.FAILED.exists()


def test_the_owner_can_retry_a_failed_release_from_the_panel(agent):
    agent.cmd_install()
    agent.state["result"] = 1
    agent.run_update()
    agent.state["result"] = 0
    assert agent.run_update(trigger="panel") == "updated"


def test_recovery_mode_stops_all_updates(agent):
    agent.cmd_install()
    (agent.APP_DIR / ".rollback").mkdir()
    (agent.APP_DIR / ".rollback" / "RECOVERY_MODE").touch()
    assert agent.run_update(trigger="panel") == "skipped" and agent.state["runs"] == 0
    assert status(agent)["recovery_mode"] is True


def test_old_snapshots_are_pruned_after_an_update(agent):
    import os
    import time
    folder = agent.APP_DIR / ".rollback"
    folder.mkdir()
    for i in range(8):
        for kind in ("tar.gz", "sql"):
            path = folder / f"pre-update-2026{i:02d}.{kind}"
            path.write_text("x")
            os.utime(path, (time.time() + i, time.time() + i))
    agent.cmd_install()
    agent.run_update()
    assert len(list(folder.glob("pre-update-*.tar.gz"))) == 5 and len(list(folder.glob("pre-update-*.sql"))) == 5
    assert (folder / "pre-update-202607.sql").exists(), "the newest are kept"


def test_disable_removes_the_units(agent):
    agent.cmd_install()
    agent.cmd_disable()
    assert not list(agent.SYSTEMD_DIR.iterdir())
    assert json.loads(agent.CONFIG.read_text())["enabled"] is False
