"""A successful process exit must not turn missing, partial or skipped mobile tests into a green check."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location("verify_xcuitest_results", ROOT / "scripts/ci/verify_xcuitest_results.py")
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


def complete():
    # The customer demo UI contains four mandatory test methods.
    return {"result": "Passed", "totalTestCount": 4, "passedTests": 4,
            "failedTests": 0, "skippedTests": 0, "expectedFailures": 0, "testFailures": []}


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
