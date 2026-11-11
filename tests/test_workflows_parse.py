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


def test_ci_gate_waits_for_every_job():
    """«CI gate» is the one required check for main: a job that is not in its `needs` is not waited for.

    A new job in ci.yml must be added to `needs` of `gate` — this test fails until it is.
    """
    ci = pathlib.Path(__file__).resolve().parents[1] / ".github/workflows/ci.yml"
    jobs = yaml.safe_load(ci.read_text(encoding="utf-8"))["jobs"]
    gate = jobs["gate"]
    needs = gate["needs"] if isinstance(gate["needs"], list) else [gate["needs"]]
    others = set(jobs) - {"gate"}
    assert sorted(others - set(needs)) == [], "add these jobs to `needs` of the `gate` job in .github/workflows/ci.yml"
    assert sorted(set(needs) - others) == [], "`gate` needs jobs that do not exist"
    assert len(needs) == len(set(needs))
    assert gate.get("if") == "always()", "the gate must run even when a job above failed, to report it"
