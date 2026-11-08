"""Every GitHub Actions workflow is valid YAML with triggers and jobs.

A workflow file GitHub cannot parse does not fail a pull request: it only records a «startup failure» run with no
jobs, so its checks are simply missing and the rest of the CI looks green. In v28.100.0 a `: ` inside an unquoted
`script:` value did exactly that to «Android client app». This test catches it before the merge."""
from __future__ import annotations

import pathlib

import pytest
import yaml

WORKFLOWS = sorted((pathlib.Path(__file__).resolve().parents[1] / ".github/workflows").glob("*.y*ml"))


def test_there_are_workflows():
    assert len(WORKFLOWS) > 10


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_workflow_parses_with_triggers_and_jobs(path: pathlib.Path):
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), path.name
    # PyYAML reads the bare key `on` as the boolean True.
    assert "on" in data or True in data, f"{path.name}: no triggers"
    jobs = data.get("jobs")
    assert isinstance(jobs, dict) and jobs, f"{path.name}: no jobs"
    for name, job in jobs.items():
        assert isinstance(job, dict), f"{path.name}: job {name}"
        assert "steps" in job or "uses" in job, f"{path.name}: job {name} has neither steps nor uses"
