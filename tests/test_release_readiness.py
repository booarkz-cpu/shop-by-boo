"""Readiness fixtures validate refusal behavior; they are not production verification evidence."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))
from scripts.audit.check_release_readiness import FLAGS, inspect, main  # noqa: E402


def write(root, *, state="PASS", flags=True, evidence=True, tag="v28.162.0"):
    path = root / "docs/requirements"
    path.mkdir(parents=True, exist_ok=True)
    (path / "register.json").write_text(json.dumps([{"id": "REQ-QA-0001"}]), encoding="utf-8")
    record = {"status": state, "evidence": ["evidence.txt"] if evidence else [], "note": "Fixture decision"}
    (path / "status.json").write_text(json.dumps({"REQ-QA-0001": record}), encoding="utf-8")
    (root / "evidence.txt").write_text("Parser fixture, not production evidence.", encoding="utf-8")
    (root / "release-manifest.template.json").write_text(
        json.dumps({"distribution_tag": tag, **dict.fromkeys(FLAGS, flags)}), encoding="utf-8")


@pytest.mark.parametrize("state", ["PARTIAL", "FAIL", "NOT_IMPLEMENTED", "NOT_TESTED",
                                 "BLOCKED_EXTERNAL", "BLOCKED_SECRETS", "SOURCE_UNAVAILABLE"])
def test_every_unfinished_or_blocked_requirement_prevents_a_new_release(tmp_path, state):
    write(tmp_path, state=state)
    assert not inspect(tmp_path)["ready"]
    assert main(["--require-ready"], tmp_path) == 1
    assert main(["--new-release-only"], tmp_path) == 1


def test_verification_flags_must_be_boolean_true_not_strings(tmp_path):
    write(tmp_path, flags="true")
    assert not inspect(tmp_path)["ready"]
    assert main(["--require-ready"], tmp_path) == 1


def test_missing_evidence_or_unknown_source_records_cannot_pass(tmp_path):
    write(tmp_path, evidence=False)
    with pytest.raises(ValueError, match="without evidence"):
        inspect(tmp_path)
    write(tmp_path)
    (tmp_path / "evidence.txt").unlink()
    with pytest.raises(ValueError, match="evidence path"):
        inspect(tmp_path)
    status = tmp_path / "docs/requirements/status.json"
    status.write_text(json.dumps({"REQ-QA-9999": {"status": "PASS"}}), encoding="utf-8")
    with pytest.raises(ValueError, match="without source"):
        inspect(tmp_path)


def test_duplicate_trace_ids_are_refused(tmp_path):
    write(tmp_path)
    (tmp_path / "docs/requirements/register.json").write_text(
        json.dumps([{"id": "REQ-QA-0001"}, {"id": "REQ-QA-0001"}]), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicated"):
        inspect(tmp_path)


def test_published_tag_exception_does_not_report_readiness(tmp_path):
    write(tmp_path, state="PARTIAL", flags=False, tag="v28.161.0")
    assert main(["--new-release-only"], tmp_path) == 0
    assert not inspect(tmp_path)["ready"]
    assert main(["--require-ready"], tmp_path) == 1


def test_complete_declarations_are_distinct_from_real_product_verification(tmp_path):
    write(tmp_path)
    assert inspect(tmp_path)["ready"]
    assert main(["--require-ready"], tmp_path) == 0


def test_missing_status_record_is_not_silently_treated_as_pass(tmp_path):
    write(tmp_path)
    status = tmp_path / "docs/requirements/status.json"
    status.write_text("{}", encoding="utf-8")
    report = inspect(tmp_path)
    assert report["counts"]["NOT_TESTED"] == 1
    assert report["pending"][0]["id"] == "REQ-QA-0001"
    assert not report["ready"]
    assert main(["--new-release-only"], tmp_path) == 1


def test_each_verification_flag_is_individually_required(tmp_path):
    for missing in FLAGS:
        write(tmp_path)
        manifest = tmp_path / "release-manifest.template.json"
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data[missing] = False
        manifest.write_text(json.dumps(data), encoding="utf-8")
        report = inspect(tmp_path)
        assert report["flags"][missing] is False
        assert not report["ready"]
        assert main(["--new-release-only"], tmp_path) == 1
