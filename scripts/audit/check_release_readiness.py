#!/usr/bin/env python3
"""Report every release requirement; never infer production verification from a successful build."""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PUBLISHED_TAG = "v28.161.0"
ACCEPTED = {"PASS", "NOT_APPLICABLE", "RETIRED_BY_OWNER"}
STATES = ACCEPTED | {"PARTIAL", "FAIL", "NOT_IMPLEMENTED", "NOT_TESTED", "BLOCKED_EXTERNAL",
                     "BLOCKED_SECRETS", "SOURCE_UNAVAILABLE"}
FLAGS = ("production_ready", "full_function_transfer", "production_e2e_verified", "signed")


def inspect(root: Path) -> dict:
    register = json.loads((root / "docs/requirements/register.json").read_text(encoding="utf-8"))
    status = json.loads((root / "docs/requirements/status.json").read_text(encoding="utf-8"))
    manifest = json.loads((root / "release-manifest.template.json").read_text(encoding="utf-8"))
    ids = [item["id"] for item in register]
    if not ids or len(ids) != len(set(ids)) or any(not re.fullmatch(r"REQ-[A-Z]+-\d{4}", item) for item in ids):
        raise ValueError("Requirement IDs are empty, duplicated or invalid")
    if set(status) - set(ids):
        raise ValueError("Status records without source requirements")
    counts = Counter()
    pending = []
    for identity in ids:
        record = status.get(identity, {})
        state = record.get("status", "NOT_TESTED")
        if state not in STATES:
            raise ValueError(f"{identity}: unknown status")
        counts[state] += 1
        if state == "PASS":
            if not record.get("evidence"):
                raise ValueError(f"{identity}: PASS without evidence")
            for name in record["evidence"]:
                path = (root / name.split("::")[0].split("#")[0]).resolve()
                if not path.is_relative_to(root.resolve()) or not path.exists():
                    raise ValueError(f"{identity}: missing or external evidence path")
        elif state in ACCEPTED and not record.get("note"):
            raise ValueError(f"{identity}: owner decision/reason is required")
        if state not in ACCEPTED:
            pending.append({"id": identity, "status": state, "note": record.get("note", "")})
    flags = {name: manifest.get(name) is True for name in FLAGS}
    return {"distribution_tag": manifest["distribution_tag"], "requirements": len(ids),
            "counts": dict(sorted(counts.items())), "pending": pending, "flags": flags,
            "ready": not pending and all(flags.values())}


def main(argv: list[str] | None = None, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--require-ready", action="store_true")
    mode.add_argument("--new-release-only", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = inspect(root)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Release readiness check failed: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Release readiness: {'READY' if report['ready'] else 'NOT READY'}; "
              f"{report['requirements']} requirements; {report['counts']}")
        print("Declared verification flags: " + json.dumps(report["flags"], sort_keys=True))
        for item in report["pending"]:
            print(f"{item['id']}: {item['status']}: {item['note']}")
    if args.new_release_only and report["distribution_tag"] == PUBLISHED_TAG:
        print("Existing immutable published tag: no new release is authorized by this exception.")
        return 0
    if (args.require_ready or args.new_release_only) and not report["ready"]:
        print("New release refused: mandatory requirements or factual verification flags are incomplete.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
