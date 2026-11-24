"""Audit reports distinguish checked consistency from declared product acceptance."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))
from scripts.audit import run_full_audit as audit  # noqa: E402


def sample():
    item = {"id": "REQ-QA-0001", "lines": [1, 1], "sha": "a" * 12, "path": "Source",
            "text": "Full source wording without abbreviation.", "product": "Все три"}
    register = [{key: item[key] for key in ("id", "lines", "sha", "path")}]
    return item, register


def test_inventory_keeps_full_source_and_does_not_promote_declared_pass_to_execution():
    item, register = sample()
    rows = audit.checklist(ROOT, [item], register, {
        item["id"]: {"status": "PASS", "evidence": ["tests/example.py"], "note": "Historic declaration"}})
    assert len(rows) == 1
    assert rows[0]["source"]["text"] == item["text"]
    assert rows[0]["declared_status"] == "PASS"
    assert rows[0]["execution_in_this_audit"] is None
    assert rows[0]["acceptance_criteria"] is None
    assert rows[0]["dependencies"] is None


@pytest.mark.parametrize("mutation", ["missing", "hash", "range", "unknown", "duplicate"])
def test_missing_or_replaced_source_identity_cannot_produce_a_complete_checklist(mutation):
    item, register = sample()
    statuses = {}
    if mutation == "missing":
        register = []
    elif mutation == "hash":
        register[0]["sha"] = "b" * 12
    elif mutation == "range":
        register[0]["lines"] = [2, 2]
    elif mutation == "unknown":
        statuses = {"REQ-QA-9999": {"status": "PASS"}}
    else:
        register += register
    with pytest.raises(ValueError, match="Canonical requirements"):
        audit.checklist(ROOT, [item], register, statuses)


def test_command_failure_and_timeout_have_real_nonzero_results(tmp_path):
    failed = audit.run_check(tmp_path, [sys.executable, "-c", "print('failed check'); raise SystemExit(7)"])
    assert failed["exit_code"] == 7
    assert failed["status"] == "FAIL"
    assert "failed check" in failed["output"]
    timed = audit.run_check(tmp_path, [sys.executable, "-c", "import time; time.sleep(10)"], timeout=0.05)
    assert timed["exit_code"] == 124
    assert timed["reason"] == "timeout"
    assert timed["status"] == "FAIL"


def test_command_logs_remove_known_secrets_and_basic_http_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_FIXTURE_TOKEN", "fixture-secret-value-123")
    result = audit.run_check(tmp_path, [sys.executable, "-c",
        "print('fixture-secret-value-123 https://user:password@example.org/ Authorization: Bearer abc123')"])
    assert result["exit_code"] == 0
    assert "fixture-secret-value-123" not in result["output"]
    assert "user:password" not in result["output"]
    assert "abc123" not in result["output"]
    assert "[REDACTED]" in result["output"]


def fixture_run(tmp_path, monkeypatch, *, code=0, corrupt=False):
    item, register = sample()
    rows = audit.checklist(tmp_path, [item], register, {})
    (tmp_path / "fixture.py").write_text(f"print('consistency fixture'); raise SystemExit({code})", encoding="utf-8")
    monkeypatch.setattr(audit, "CHECKS", (("fixture", "fixture.py"),))
    def collect(root):
        if corrupt:
            raise ValueError("Broken source inventory")
        return rows, {"ready": False, "pending": [{"id": item["id"]}], "flags": {"signed": False}}
    monkeypatch.setattr(audit, "collect", collect)
    return tmp_path / "artifacts/audit"


def test_failed_check_still_retains_machine_readable_report_and_log(tmp_path, monkeypatch):
    output = fixture_run(tmp_path, monkeypatch, code=7)
    assert audit.main([], tmp_path) == 1
    report = json.loads((output / "checklist-results.json").read_text(encoding="utf-8"))
    assert report["checks"][0]["exit_code"] == 7
    assert not report["audit_passed"]
    assert report["checklist_complete"]
    assert (output / "logs/fixture.txt").read_text(encoding="utf-8").startswith("consistency fixture")
    assert "FAIL" in (output / "FULL_AUDIT_REPORT.md").read_text(encoding="utf-8")


def test_green_consistency_keeps_unfinished_products_and_strict_release_gate(tmp_path, monkeypatch):
    output = fixture_run(tmp_path, monkeypatch)
    assert audit.main([], tmp_path) == 0
    report = json.loads((output / "checklist-results.json").read_text(encoding="utf-8"))
    assert report["audit_passed"]
    assert not report["full_product_verification"]
    assert not report["release_readiness_declarations"]["ready"]
    assert report["requirements"][0]["declared_status"] == "NOT_TESTED"
    assert report["test_counts"] is None
    assert report["skipped_tests"] is None
    assert audit.main(["--require-ready"], tmp_path) == 1


def test_invalid_inventory_is_reported_as_failure_with_no_false_completeness(tmp_path, monkeypatch):
    output = fixture_run(tmp_path, monkeypatch, corrupt=True)
    assert audit.main([], tmp_path) == 1
    report = json.loads((output / "checklist-results.json").read_text(encoding="utf-8"))
    assert not report["checklist_complete"]
    assert not report["audit_passed"]
    assert report["errors"] == ["Broken source inventory"]


def test_runtime_report_creation_does_not_make_committed_source_metadata_stale(tmp_path, monkeypatch):
    from scripts.audit import requirements_register as register
    monkeypatch.setattr(register, "ROOT", tmp_path)
    item, _ = sample()
    item.update({"prefix": "QA", "files": ["artifacts/audit/FULL_AUDIT_REPORT.md"]})
    before = register.render([item], {})
    artifact = tmp_path / "artifacts/audit/FULL_AUDIT_REPORT.md"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("A real generated audit output.", encoding="utf-8")
    assert register.render([item], {}) == before


@pytest.mark.parametrize("mutation", ["valid", "missing", "duplicate", "wrong_id", "status", "evidence", "columns"])
def test_acceptance_inventory_rejects_drift(tmp_path, mutation):
    item, register = sample()
    requirements = audit.checklist(tmp_path, [item], register, {
        item["id"]: {"status": "PASS", "evidence": ["tests/example.py"]}})
    cells = [item["id"], r"Source \| wording", "Section", "Criteria", "—",
             "PASS", "tests/example.py", "—", "Note", "—", "—"]
    if mutation == "wrong_id":
        cells[0] = "REQ-QA-9999"
    elif mutation == "status":
        cells[5] = "PARTIAL"
    elif mutation == "evidence":
        cells[6] = "tests/other.py"
    elif mutation == "columns":
        cells.pop()
    row = "| " + " | ".join(cells) + " |\n"
    content = "" if mutation == "missing" else row * (2 if mutation == "duplicate" else 1)
    path = tmp_path / "docs/AUTONOMOUS_ACCEPTANCE_CHECKLIST.md"
    path.parent.mkdir()
    path.write_text(content, encoding="utf-8")
    if mutation == "valid":
        audit.validate_acceptance_inventory(tmp_path, requirements)
    else:
        with pytest.raises(ValueError, match="[Aa]cceptance inventory"):
            audit.validate_acceptance_inventory(tmp_path, requirements)
