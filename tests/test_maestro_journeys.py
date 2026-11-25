"""Exercise the emulator entry point and the launch contracts of its four demo journeys."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "shop.remnawave.user.preview"
RUNNER = Path("scripts/mobile/maestro-screens.sh")


def run_journeys(tmp_path, *, clear_exit=0, suite_exit=0):
    runner = tmp_path / RUNNER
    runner.parent.mkdir(parents=True)
    shutil.copy(ROOT / RUNNER, runner)
    (tmp_path / "mobile/maestro/flows").mkdir(parents=True)
    binaries = tmp_path / "bin"
    binaries.mkdir()
    trace = tmp_path / "commands"
    for name, body in {
        "adb": 'case "$*" in "shell pm clear "*) exit "$CLEAR_EXIT";; esac',
        "maestro": 'exit "$SUITE_EXIT"',
        "sleep": "exit 0",
    }.items():
        script = binaries / name
        script.write_text(f'#!/bin/sh\nprintf "%s %s\\n" "{name}" "$*" >> "$TRACE"\n{body}\n')
        script.chmod(0o755)
    env = dict(os.environ, HOME=str(tmp_path), PATH=f"{binaries}:{os.environ['PATH']}",
               TRACE=str(trace), CLEAR_EXIT=str(clear_exit), SUITE_EXIT=str(suite_exit))
    result = subprocess.run(["bash", str(runner)], env=env, capture_output=True, text=True, timeout=10)
    return result.returncode, trace.read_text().splitlines()


@pytest.mark.parametrize("clear_exit,suite_exit,expected_runs", [(0, 0, 1), (17, 0, 0), (0, 37, 1)])
def test_entrypoint_resets_preview_once_and_propagates_failure(tmp_path, clear_exit, suite_exit, expected_runs):
    status, commands = run_journeys(tmp_path, clear_exit=clear_exit, suite_exit=suite_exit)
    assert commands[:2] == [f"adb shell am force-stop {PACKAGE}", f"adb shell pm clear {PACKAGE}"]
    assert commands.count(f"adb shell pm clear {PACKAGE}") == 1
    assert sum(line.startswith("maestro test ") for line in commands) == expected_runs
    assert status == (clear_exit or suite_exit)


def test_each_demo_journey_cold_starts_its_fixture_without_removing_the_previous_task():
    expected = {
        "01_vpn_and_premium": ("vpn", False, "Подключить"),
        "02_connected": ("vpn", True, "VPN подключён"),
        "03_giveaways": ("giveaways", False, "Новогоднее колесо"),
        "04_settings": ("settings", False, "Документы"),
    }
    observed = {}
    for flow in sorted((ROOT / "mobile/maestro/flows").glob("*.yaml")):
        header, commands = yaml.safe_load_all(flow.read_text())
        if flow.stem not in expected:
            continue
        assert header["appId"] == PACKAGE
        launch = commands[0]["launchApp"]
        assert launch.get("stopApp", True) and not launch.get("clearState", False)
        assert not any("clearState" in step for step in commands)
        args = launch["arguments"]
        assert args["corgi_demo"] is True and args["corgi_lang"] == "ru"
        observed[flow.stem] = (args["corgi_tab"], args.get("corgi_vpn_on", False),
                               commands[1]["extendedWaitUntil"]["visible"])
    assert observed == expected
