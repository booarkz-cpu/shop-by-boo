#!/usr/bin/env python3
"""Require a complete, passing xcresulttool summary; xcodebuild's exit status alone is insufficient."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

COUNTS = ("totalTestCount", "passedTests", "failedTests", "skippedTests", "expectedFailures")


def summary_allows_startup_retry(bundle: Path) -> bool:
    """Only a failure before XCTest ran any cases is eligible for a clean simulator."""
    path = Path(f"{bundle}.summary.json")
    try:
        summary = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        # A missing export from an existing bundle leaves the number of executed tests unknown.
        return not bundle.exists()
    except (OSError, ValueError):
        return False
    return (isinstance(summary, dict) and summary.get("testFailures") == []
            and all(type(summary.get(name)) is int and summary[name] == 0 for name in COUNTS))


def validate(summary: object, expected: int) -> dict:
    if type(expected) is not int or expected < 1:
        raise ValueError("Expected test count must be a positive integer")
    if not isinstance(summary, dict):
        raise ValueError("XCUITest summary must be a JSON object")
    for name in COUNTS:
        if type(summary.get(name)) is not int or summary[name] < 0:
            raise ValueError(f"{name}: a non-negative integer is required")
    counts = {name: summary[name] for name in COUNTS}
    if summary.get("result") != "Passed":
        raise ValueError("XCUITest overall result is not Passed")
    if counts["totalTestCount"] != expected or counts["passedTests"] != expected:
        raise ValueError(f"All {expected} expected XCUITest cases must run and pass")
    if any(counts[name] for name in ("failedTests", "skippedTests", "expectedFailures")):
        raise ValueError("Failed, skipped or expected-failure XCUITest cases are not accepted")
    if not isinstance(summary.get("testFailures"), list) or summary["testFailures"]:
        raise ValueError("A complete, empty testFailures list is required")
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("summary", type=Path)
    parser.add_argument("--expected-tests", type=int, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = {
        "verified": False, "expected_tests": args.expected_tests,
        "commit": os.environ.get("GITHUB_SHA"), "head_sha": os.environ.get("CHECKED_HEAD_SHA"),
        "branch": os.environ.get("GITHUB_HEAD_REF") or os.environ.get("GITHUB_REF_NAME"),
        "run_id": os.environ.get("GITHUB_RUN_ID"), "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "scope": "Customer app demo UI on a simulator; no real VPN, payment, device or signing verification.",
    }
    try:
        counts = validate(json.loads(args.summary.read_text(encoding="utf-8")), args.expected_tests)
        report.update({"verified": True, "counts": counts})
        print(f"XCUITest result verified: {counts['passedTests']} passed, 0 failed, 0 skipped.")
    except (OSError, ValueError, TypeError) as exc:
        report["error"] = str(exc)
        print(f"XCUITest result refused: {exc}", file=sys.stderr)
    if args.output:
        # Write both verdicts: an unsuccessful second check must replace a previous success proof.
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if report["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
