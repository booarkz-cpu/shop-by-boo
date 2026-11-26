"""The Android runtime preflight retries a repository miss and still fails a real one."""
import hashlib
import os
import re
import subprocess
from pathlib import Path

import pytest


WARM = Path(__file__).resolve().parents[1] / "scripts/ci/gradle-warm.sh"
TASK = ":app:processDebugNavigationResources"
MIRROR = "https://maven-central.storage-download.googleapis.com/maven2/"


@pytest.mark.parametrize("project", ["vpn-shop", "vpn-client", "lucy-admin"])
def test_distribution_checksum_is_configured(project):
    wrapper_dir = WARM.parents[2] / "apps" / project / "android/gradle/wrapper"
    entries = dict(
        line.split("=", 1)
        for line in (wrapper_dir / "gradle-wrapper.properties").read_text().splitlines()
        if "=" in line
    )
    assert entries["distributionUrl"].endswith("/gradle-9.9.2-bin.zip"), project
    assert entries.get("distributionSha256Sum") == (
        "971fcd7150ca4ba04852c0b2ca0d2d0ab9468e14b03473eab19528809914c76b"
    ), project
    assert hashlib.sha256((wrapper_dir / "gradle-wrapper.jar").read_bytes()).hexdigest() == (
        "621008afc4f5d59357fcf06ffa644dd5aade5e091bdc363742710445f73cdaf8"
    ), project


@pytest.mark.parametrize("project", ["vpn-shop", "vpn-client", "lucy-admin"])
def test_documented_android_versions_match_the_project(project):
    root = WARM.parents[2]
    path = Path("apps") / project / "android"
    plugin = (root / path / "build.gradle.kts").read_text()
    app = (root / path / "app/build.gradle.kts").read_text()
    agp, = re.findall(r'id\("com\.android\.application"\)\s+version\s+"([^"]+)"', plugin)
    version, = re.findall(r'^\s*versionName\s*=\s*"([^"]+)"', app, re.MULTILINE)
    table = (root / "docs/TECH_STACK.md").read_text().splitlines()
    row, = [line for line in table if line.endswith(f"`{path.as_posix()}` |")]
    assert f"Android {version} |" in row
    assert f"AGP {agp}," in row


def test_lucy_admin_uses_current_stable_agp():
    build = WARM.parents[2] / "apps/lucy-admin/android/build.gradle.kts"
    assert 'id("com.android.application") version "9.5.3" apply false' in build.read_text()


@pytest.fixture
def android_project(tmp_path):
    project = tmp_path / "Android app"
    project.mkdir()
    (project / "gradlew").write_text(
        """#!/bin/bash
printf '%s\\n' "$*" >> calls
prev=
for arg in "$@"; do
  if [[ $prev == --init-script ]]; then cp "$arg" init-used.gradle; fi
  prev=$arg
done
if [[ $1 == --version ]]; then exit 0; fi
if [[ ${GRADLE_ACCEPT_ANY:-} != 1 && $1 != "__TASK__" ]]; then exit 64; fi
runs=0
if [[ -f task_runs ]]; then runs=$(cat task_runs); fi
runs=$((runs + 1))
printf '%s\\n' "$runs" > task_runs
if [[ -n ${GRADLE_USER_HOME:-} && ! -d ${GRADLE_USER_HOME}/caches ]]; then
  printf '%s\\n' "NO_MODULE_CACHE $runs" >> calls
fi
fail_first=${FAIL_FIRST:-0}
if (( runs <= fail_first )); then
  echo "${FAIL_MESSAGE:-Could not find example.group:missing:1.0.}" >&2
  exit 27
fi
exit 0
""".replace("__TASK__", TASK),
        encoding="utf-8",
    )
    return project


def invoke(project, *options, fail_first=0, home=None, accept_any=False):
    env = {**os.environ, "FAIL_FIRST": str(fail_first), "GRADLE_WARM_NO_SLEEP": "1"}
    if accept_any:
        env["GRADLE_ACCEPT_ANY"] = "1"
    if home is not None:
        env["GRADLE_USER_HOME"] = str(home)
    command = ["bash", str(WARM), *options]
    if not options or options[0] != "--exec":
        command.append(str(project))
    return subprocess.run(command, env=env, capture_output=True, text=True, check=False)


def calls(project):
    return (project / "calls").read_text().splitlines()


def task_calls(project):
    return [line for line in calls(project) if line.startswith(TASK)]


def test_default_mode_only_downloads_wrapper(android_project):
    result = invoke(android_project, fail_first=9)
    assert result.returncode == 0, result.stderr
    assert calls(android_project) == ["--version --no-daemon -q"]


def test_first_resolution_does_not_refresh(android_project, tmp_path):
    home = tmp_path / "gradle-home"
    (home / "caches").mkdir(parents=True)
    result = invoke(android_project, "--android-runtime", home=home)
    assert result.returncode == 0, result.stderr
    resolved = task_calls(android_project)
    assert len(resolved) == 1
    assert "--refresh-dependencies" not in resolved[0]
    assert "--info" in resolved[0]
    assert MIRROR in (android_project / "init-used.gradle").read_text(encoding="utf-8")
    assert "debug navigation resources ready" in result.stdout
    assert (home / "caches").is_dir()


def test_a_miss_is_asked_again_without_the_recorded_failure(android_project, tmp_path):
    home = tmp_path / "gradle-home"
    (home / "caches").mkdir(parents=True)
    result = invoke(android_project, "--android-runtime", fail_first=1, home=home)
    assert result.returncode == 0, result.stderr
    resolved = task_calls(android_project)
    assert len(resolved) == 2
    assert "--refresh-dependencies" not in resolved[0]
    assert "--refresh-dependencies" in resolved[1]
    assert "NO_MODULE_CACHE 2" in calls(android_project)
    assert "gradle: backoff 5s" in result.stdout
    assert "debug navigation resources ready" in result.stdout


def test_exec_retries_the_requested_gradle_command(android_project, tmp_path):
    home = tmp_path / "gradle-home"
    (home / "caches").mkdir(parents=True)
    result = invoke(
        android_project, "--exec", str(android_project), "--", "assembleDebug", "--no-daemon",
        fail_first=1, home=home, accept_any=True,
    )
    assert result.returncode == 0, result.stderr
    resolved = [line for line in calls(android_project) if line.startswith("assembleDebug")]
    assert len(resolved) == 2
    assert "--refresh-dependencies" not in resolved[0]
    assert "--refresh-dependencies" in resolved[1]
    assert "command ready" in result.stdout


def test_http_429_keeps_downloaded_modules(android_project, tmp_path, monkeypatch):
    home = tmp_path / "gradle-home"
    (home / "caches").mkdir(parents=True)
    monkeypatch.setenv("FAIL_MESSAGE", "Received status code 429 from server: Too Many Requests")
    result = invoke(android_project, "--android-runtime", fail_first=1, home=home)
    assert result.returncode == 0, result.stderr
    resolved = task_calls(android_project)
    assert len(resolved) == 2
    assert "--refresh-dependencies" not in resolved[1]
    assert "NO_MODULE_CACHE" not in calls(android_project)
    assert (home / "caches").is_dir()
    assert "gradle: backoff 20s" in result.stdout


def test_android_apps_ask_the_mirror_before_maven_central():
    root = WARM.parents[2]
    for name in ("vpn-shop", "lucy-admin", "vpn-client"):
        text = (root / "apps" / name / "android" / "settings.gradle.kts").read_text(encoding="utf-8")
        assert text.index("maven-central.storage-download.googleapis.com") < text.index("mavenCentral()")
        assert text.index("google()") < text.index("maven-central.storage-download.googleapis.com")


def test_a_persistent_miss_is_still_a_failure(android_project, tmp_path):
    home = tmp_path / "gradle-home"
    result = invoke(android_project, "--android-runtime", fail_first=9, home=home)
    assert result.returncode == 27
    assert len(task_calls(android_project)) == 6
    assert "debug navigation resources ready" not in result.stdout
    assert "did not resolve" in result.stderr


def test_unit_test_failure_is_not_retried(android_project, tmp_path, monkeypatch):
    home = tmp_path / "gradle-home"
    (home / "caches").mkdir(parents=True)
    monkeypatch.setenv("FAIL_MESSAGE", "Could not find example.group:missing:1.0.\nThere were failing tests.")
    result = invoke(
        android_project, "--exec", str(android_project), "--", ":app:testDebugUnitTest",
        fail_first=1, home=home, accept_any=True,
    )
    assert result.returncode == 27
    assert (android_project / "task_runs").read_text().strip() == "1"
    assert (home / "caches").is_dir()
    assert "There were failing tests." in result.stdout
