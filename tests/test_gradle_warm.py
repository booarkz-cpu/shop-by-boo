"""The Android runtime preflight retries a repository miss and still fails a real one."""
import os
import subprocess
from pathlib import Path

import pytest


WARM = Path(__file__).resolve().parents[1] / "scripts/ci/gradle-warm.sh"
TASK = ":app:processDebugNavigationResources"
MIRROR = "https://maven-central.storage-download.googleapis.com/maven2/"


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
[[ $1 == "__TASK__" ]] || exit 64
runs=0
if [[ -f task_runs ]]; then runs=$(cat task_runs); fi
runs=$((runs + 1))
printf '%s\\n' "$runs" > task_runs
if [[ -n ${GRADLE_USER_HOME:-} && ! -d ${GRADLE_USER_HOME}/caches ]]; then
  printf '%s\\n' "NO_MODULE_CACHE $runs" >> calls
fi
fail_first=${FAIL_FIRST:-0}
if (( runs <= fail_first )); then exit 27; fi
exit 0
""".replace("__TASK__", TASK),
        encoding="utf-8",
    )
    return project


def invoke(project, *options, fail_first=0, home=None):
    env = {**os.environ, "FAIL_FIRST": str(fail_first), "GRADLE_WARM_NO_SLEEP": "1"}
    if home is not None:
        env["GRADLE_USER_HOME"] = str(home)
    return subprocess.run(
        ["bash", str(WARM), *options, str(project)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


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


def test_a_persistent_miss_is_still_a_failure(android_project, tmp_path):
    home = tmp_path / "gradle-home"
    result = invoke(android_project, "--android-runtime", fail_first=9, home=home)
    assert result.returncode == 27
    assert len(task_calls(android_project)) == 6
    assert "debug navigation resources ready" not in result.stdout
    assert "did not resolve" in result.stderr
