"""A successful process exit must not turn missing, partial or skipped mobile tests into a green check."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location("verify_xcuitest_results", ROOT / "scripts/ci/verify_xcuitest_results.py")
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)
retry_spec = importlib.util.spec_from_file_location("xcuitest_retry", ROOT / "scripts/ci/xcuitest_retry.py")
retry = importlib.util.module_from_spec(retry_spec)
retry_spec.loader.exec_module(retry)

AX_TIMEOUT = 'Failed to initialize for UI testing: Error Domain=XCTDaemonErrorDomain Code=18 "Timed out waiting for AX loaded notification"'
AX_FUTURE_TIMEOUT = ('Failed to initialize for UI testing: Error Domain=com.apple.dt.XCTest.XCTFuture '
                     'Code=1000 "Timed out while loading Accessibility."')
RUNNER_KILLED = (
    "VpnShopUserUITests-Runner (27690) encountered an error (Early unexpected exit, "
    "operation never finished bootstrapping - no restart will be attempted. "
    "(Underlying Error: Test crashed with signal kill before establishing connection.))"
)


@pytest.mark.parametrize("log", [
    AX_TIMEOUT + "\nTesting failed:\n** TEST FAILED **\nTesting started",
    AX_FUTURE_TIMEOUT + "\nTesting failed:\n** TEST FAILED **\nTesting started",
    RUNNER_KILLED + "\n** TEST FAILED **\nTesting started",
    RUNNER_KILLED + "\n\t Executed 0 tests, with 0 failures (0 unexpected) in 0.000 seconds",
    "Application does not have a process ID",
    "Failed to get background assertion",
    "Failed to launch test application",
])
def test_simulator_startup_can_be_retried(log):
    assert retry.retry_reason(log)


@pytest.mark.parametrize("log", [
    "build failed",
    "Timed out waiting for AX loaded notification",
    AX_TIMEOUT.replace("Code=18", "Code=19"),
    AX_TIMEOUT + "\nXCTAssertEqual failed",
    "Failed to launch\nXCTFail(Unexpected result)",
    "Failed to launch\nTest Case '-[UITests testLogin]' failed (3.0 seconds).",
    "Test Case '-[UITests testLogin]' started.\n" + AX_TIMEOUT,
    "Test case 'UITests.testLogin()' passed on iPhone\n" + AX_TIMEOUT,
    AX_FUTURE_TIMEOUT.replace("Code=1000", "Code=10001"),
    AX_FUTURE_TIMEOUT.replace("XCTest.XCTFuture", "application.bootstrap"),
    "Timed out while loading Accessibility.",
    "Test Case '-[UITests testLogin]' started.\n" + AX_FUTURE_TIMEOUT,
    "Test case 'UITests.testLogin()' skipped on iPhone\n" + AX_FUTURE_TIMEOUT,
    AX_FUTURE_TIMEOUT + "\nXCTAssertEqual failed",
    RUNNER_KILLED.replace("VpnShopUserUITests-Runner", "VpnShopUser"),
    RUNNER_KILLED.replace("signal kill", "signal segv"),
    RUNNER_KILLED.replace("before establishing connection", "after establishing connection"),
    "Test crashed with signal kill before establishing connection.",
    "Test Case '-[UITests testLogin]' started.\n" + RUNNER_KILLED,
    RUNNER_KILLED + "\nTest case 'UITests.testLogin()' passed on 'iPhone'",
    "\t Executed 1 test, with 1 failure (0 unexpected) in 4.000 seconds\n" + RUNNER_KILLED,
    RUNNER_KILLED + "\n\t Executed 4 tests, with 0 failures (0 unexpected) in 127.291 (127.345) seconds",
    "Test Case '-[UITests testLogin]' skipped.\nFailed to launch test application",
    RUNNER_KILLED + "\nXCTFail(Unexpected)",
])
def test_ambiguous_or_test_case_failures_require_investigation(log):
    assert retry.retry_reason(log) is None


def complete():
    # The customer demo UI contains four mandatory test methods.
    return {"result": "Passed", "totalTestCount": 4, "passedTests": 4,
            "failedTests": 0, "skippedTests": 0, "expectedFailures": 0, "testFailures": []}


@pytest.mark.parametrize("summary,allowed", [
    (None, True),
    ({"totalTestCount": 0, "passedTests": 0}, True),
    ({"totalTestCount": 1, "passedTests": 0, "failedTests": 1}, False),
    ({"totalTestCount": 0, "passedTests": 0, "skippedTests": 1}, False),
    ({"totalTestCount": 0, "passedTests": 0, "testFailures": [{"testName": "testLogin"}]}, False),
    ({"totalTestCount": False, "passedTests": 0}, False),
    ("incomplete JSON", False),
])
def test_startup_retry_considers_the_result_bundle(tmp_path, summary, allowed):
    log = tmp_path / "xcuitest.log"
    log.write_text(RUNNER_KILLED)
    bundle = tmp_path / "first.xcresult"
    path = tmp_path / "first.xcresult.summary.json"
    if summary is not None:
        bundle.mkdir()
    if isinstance(summary, dict):
        path.write_text(json.dumps({**complete(), "result": "Failed", **summary}))
    elif summary is not None:
        path.write_text(summary)
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts/ci/xcuitest_retry.py"), str(log), str(bundle)],
        capture_output=True, text=True, check=False,
    )
    assert (proc.returncode == 0) == allowed, proc.stderr
    assert bool(proc.stdout.strip()) == allowed


def test_existing_bundle_with_no_export_cannot_be_retried(tmp_path):
    bundle = tmp_path / "first.xcresult"
    bundle.mkdir()
    assert not verifier.summary_allows_startup_retry(bundle)


RUNNER_AX_LOG = "VpnShopUserUITests-Runner[31426:89970] [Default] " + AX_FUTURE_TIMEOUT


@pytest.fixture
def accessibility_runner_summary():
    runner = "VpnShopUserUITests-Runner (31426) encountered an error"
    return {
        "result": "Failed", "totalTestCount": 1, "passedTests": 0,
        "failedTests": 1, "skippedTests": 0, "expectedFailures": 0,
        "testFailures": [{
            "targetName": "VpnShopUserUITests", "testName": runner,
            "testIdentifierString": runner,
            "failureText": ("The test runner failed to initialize for UI testing. "
                            "(Underlying Error: Timed out while loading Accessibility.)"),
        }],
    }


@pytest.mark.parametrize(("log", "allowed"), [
    (RUNNER_AX_LOG, True),
    ("Failed to launch test application", False),
    (RUNNER_KILLED, False),
    (AX_TIMEOUT, False),
    (RUNNER_AX_LOG.replace("31426", "31427"), False),
    (RUNNER_AX_LOG.replace("Code=1000", "Code=1001") + "\nFailed to launch", False),
    ("VpnShopUserUITests-Runner[31426:1]\n" + AX_FUTURE_TIMEOUT, False),
    (RUNNER_AX_LOG + "\nTest Case '-[UITests testLogin]' started.", False),
    (RUNNER_AX_LOG + "\nXCTAssertEqual failed", False),
])
def test_synthetic_runner_failure_requires_a_matching_log(tmp_path, accessibility_runner_summary, log, allowed):
    bundle = tmp_path / "first.xcresult"
    bundle.mkdir()
    Path(f"{bundle}.summary.json").write_text(json.dumps(accessibility_runner_summary), encoding="utf-8")
    log_path = tmp_path / "xcuitest.log"
    log_path.write_text(log, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/ci/xcuitest_retry.py"), str(log_path), str(bundle)],
        capture_output=True, text=True, check=False,
    )
    assert (result.returncode == 0) == allowed, result.stderr
    assert bool(result.stdout.strip()) == allowed


@pytest.mark.parametrize("patch", [
    {"targetName": "VpnShopUserUITests.testLogin"},
    {"testName": "testLogin"},
    {"testIdentifierString": "testLogin"},
    {"testIdentifierString": "VpnShopUserUITests-Runner (31427) encountered an error"},
    {"failureText": "XCTAssertEqual failed"},
])
def test_real_or_ambiguous_test_failure_cannot_use_runner_retry(tmp_path, accessibility_runner_summary, patch):
    bundle = tmp_path / "first.xcresult"
    bundle.mkdir()
    accessibility_runner_summary["testFailures"][0].update(patch)
    Path(f"{bundle}.summary.json").write_text(json.dumps(accessibility_runner_summary), encoding="utf-8")
    assert not verifier.summary_allows_startup_retry(bundle, RUNNER_AX_LOG)


@pytest.mark.parametrize("field", verifier.COUNTS)
@pytest.mark.parametrize("value", [None, True, "4", 4.0, -1])
def test_incomplete_or_untyped_counts_are_refused(field, value):
    data = complete()
    data[field] = value
    with pytest.raises(ValueError):
        verifier.validate(data, 4)


@pytest.mark.parametrize("patch", [
    {"totalTestCount": 0, "passedTests": 0},
    {"totalTestCount": 3, "passedTests": 3},
    {"totalTestCount": 5, "passedTests": 5},
    {"passedTests": 3, "failedTests": 1},
    {"passedTests": 3, "skippedTests": 1},
    {"expectedFailures": 1},
    {"result": "Failed"},
    {"testFailures": [{"failureText": "XCTAssertTrue failed"}]},
    {"testFailures": None},
])
def test_zero_missing_failed_skipped_or_extra_cases_do_not_pass(patch):
    data = {**complete(), **patch}
    with pytest.raises(ValueError):
        verifier.validate(data, 4)


def test_only_top_level_run_totals_are_used():
    data = complete()
    data["devicesAndConfigurations"] = [{"passedTests": 4, "failedTests": 0}]
    assert verifier.validate(data, 4) == {name: data[name] for name in verifier.COUNTS}


def test_failed_second_check_replaces_a_previous_success_artifact(tmp_path, monkeypatch):
    source, output = tmp_path / "summary.json", tmp_path / "verified.json"
    monkeypatch.setenv("GITHUB_SHA", "merge-commit-fixture")
    monkeypatch.setenv("CHECKED_HEAD_SHA", "head-commit-fixture")
    source.write_text(json.dumps(complete()), encoding="utf-8")
    args = [str(source), "--expected-tests", "4", "--output", str(output)]
    assert verifier.main(args) == 0
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["verified"] is True and data["head_sha"] == "head-commit-fixture"
    assert data["counts"]["passedTests"] == 4
    assert "demo UI" in data["scope"]
    source.write_text("incomplete JSON", encoding="utf-8")
    assert verifier.main(args) == 1
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["verified"] is False and "counts" not in data and "error" in data
    source.unlink()
    assert verifier.main(args) == 1
    assert json.loads(output.read_text(encoding="utf-8"))["verified"] is False


@pytest.mark.parametrize("summary", [None, [], True, "Passed"])
def test_a_non_object_report_is_not_a_test_result(summary):
    with pytest.raises(ValueError):
        verifier.validate(summary, 4)
