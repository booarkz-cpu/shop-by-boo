"""The optional Android preflight must propagate Gradle failures to the engine job."""
import os
import subprocess
from pathlib import Path

import pytest


WARM = Path(__file__).resolve().parents[1] / "scripts/ci/gradle-warm.sh"
TASK = ":app:processDebugNavigationResources"


@pytest.fixture
def android_project(tmp_path):
    project = tmp_path / "Android app"
    project.mkdir()
    (project / "gradlew").write_text(
        'printf "%s\\n" "$1" >> calls\n'
        'if [[ $1 == --version ]]; then exit 0; fi\n'
        f'[[ $1 == "{TASK}" ]] || exit 64\n'
        'exit "$RESOLUTION_STATUS"\n',
        encoding="utf-8",
    )
    return project


def invoke(project, *options, resolution_status=0):
    return subprocess.run(
        ["bash", str(WARM), *options, str(project)],
        env={**os.environ, "RESOLUTION_STATUS": str(resolution_status)},
        capture_output=True,
        text=True,
        check=False,
    )


def test_default_mode_only_downloads_wrapper(android_project):
    result = invoke(android_project, resolution_status=27)
    assert result.returncode == 0, result.stderr
    assert (android_project / "calls").read_text().splitlines() == ["--version"]


@pytest.mark.parametrize("resolution_status", [0, 27])
def test_android_runtime_requires_the_resource_task(android_project, resolution_status):
    result = invoke(android_project, "--android-runtime", resolution_status=resolution_status)
    assert (android_project / "calls").read_text().splitlines() == ["--version", TASK]
    assert result.returncode == resolution_status
    assert ("debug navigation resources ready" in result.stdout) == (resolution_status == 0)
