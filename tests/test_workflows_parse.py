"""Every GitHub Actions workflow is valid YAML with triggers and jobs.

A workflow file GitHub cannot parse does not fail a pull request: it only records a «startup failure» run with no
jobs, so its checks are simply missing and the rest of the CI looks green. In v28.100.0 a `: ` inside an unquoted
`script:` value did exactly that to «Android client app». This test catches it before the merge."""
from __future__ import annotations

import pathlib
import re

import pytest
import yaml

WORKFLOWS = sorted((pathlib.Path(__file__).resolve().parents[1] / ".github/workflows").glob("*.y*ml"))


def test_there_are_workflows():
    assert len(WORKFLOWS) > 10


def test_artifact_uploaders_share_one_immutable_revision():
    uses = {}
    for path in WORKFLOWS:
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job in workflow["jobs"].values():
            for step in job.get("steps", []):
                action, _, revision = step.get("uses", "").partition("@")
                if action == "actions/upload-artifact":
                    uses.setdefault(revision, set()).add(path.name)
    assert len(uses) == 1, uses
    revision, workflows = next(iter(uses.items()))
    assert re.fullmatch(r"[0-9a-f]{40}", revision)
    assert {"ci.yml", "load-security.yml"} <= workflows


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


def test_ios_ui_retries_simulator_accessibility_startup_failures():
    """A simulator that times out loading Accessibility never starts the test process.

    This is a runner startup failure, not an XCTest assertion, so the existing
    clean-simulator retry must cover it while still refusing to retry assertions.
    """
    ci = pathlib.Path(__file__).resolve().parents[1] / ".github/workflows/ci.yml"
    ios_ui = "\n".join(
        str(step.get("run", "")) for step in yaml.safe_load(ci.read_text(encoding="utf-8"))["jobs"]["ios-ui"]["steps"]
    )
    assert "Timed out while loading Accessibility" in ios_ui
    assert "failed to initialize for UI testing" in ios_ui
    assert 'grep -qE "XCTAssert"' in ios_ui
    assert 'xcrun simctl erase "$device"' in ios_ui


def test_every_action_is_pinned_to_a_commit():
    """A tag of an action can be moved to other code; a commit cannot (master prompt v6, «pin action versions»).

    Every `uses:` names the full commit SHA and keeps the version in a comment, which Dependabot updates together.
    """
    import re

    pinned = re.compile(r"^\s*(?:- )?uses:\s*[\w.-]+/[\w./-]+@[0-9a-f]{40} # v\d[\w.]*$")
    loose = [f"{path.name}: {line.strip()}" for path in WORKFLOWS for line in path.read_text(encoding="utf-8").splitlines()
             if re.match(r"^\s*(?:- )?uses:", line) and not re.match(r"^\s*(?:- )?uses:\s*\./", line) and not pinned.match(line)]
    assert loose == [], "pin these actions to a commit SHA with the version in a comment"


def test_security_scanners_block_the_merge():
    """Secret, dependency and container scanning and the SBOM are part of the required CI (master prompt v6, security)."""
    ci = (pathlib.Path(__file__).resolve().parents[1] / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    jobs = yaml.safe_load(ci)["jobs"]
    security = "\n".join(str(step.get("run", "")) for step in jobs["security"]["steps"])
    containers = "\n".join(str(step.get("run", "")) for step in jobs["containers"]["steps"])
    assert "fs --quiet --scanners vuln,secret --severity HIGH,CRITICAL --exit-code 1" in security
    assert "--format cyclonedx" in security and "pip-audit" in security and "bandit" in security and "npm audit" in security
    assert "image --quiet --scanners vuln --severity HIGH,CRITICAL --ignore-unfixed --ignorefile /.trivyignore --exit-code 1" in containers
    # Every exception has an expiry date: it cannot stay forever unnoticed.
    ignored = [line for line in (pathlib.Path(__file__).resolve().parents[1] / ".trivyignore").read_text().splitlines()
               if line.strip() and not line.startswith("#")]
    assert ignored and all(" exp:20" in line for line in ignored) and len(ignored) <= 3
    # The scanner itself is pinned: a moved tag must not change what is run.
    assert ci.count("aquasec/trivy@sha256:") == 3 and "aquasec/trivy:" not in ci
    for job in ("security", "containers"):
        assert not any(step.get("continue-on-error") for step in jobs[job]["steps"]), job
