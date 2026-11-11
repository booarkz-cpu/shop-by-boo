#!/usr/bin/env python3
"""Licences of the dependencies that ship with the shop (master prompt v6, CI: «лицензии»).

The shop is distributed under its own source licence, so a dependency under a strong copyleft or a
source-available licence must not get in unnoticed. This reads the reports of the standard tools and fails on
such a licence; everything else is printed as a summary.

    pip-licenses --format=json > py.json
    npx license-checker --production --json > admin.json
    python3 scripts/ci/check-licenses.py py.json admin.json cabinet.json

An exception is a line in ALLOWED with the reason — never a silent skip.
"""
from __future__ import annotations

import collections
import json
import re
import sys

# Strong copyleft and source-available licences. LGPL and MPL are weak copyleft: allowed for a library used as is.
DENIED = re.compile(r"(?<![A-Za-z])(AGPL|GPL|SSPL|BUSL|Business Source|Commons Clause|Elastic License|RSAL|Affero)", re.I)
WEAK = re.compile(r"(?<![A-Za-z])(LGPL|Lesser General Public)", re.I)
# package name → reason. Keep it empty unless a human decided so.
ALLOWED: dict[str, str] = {}


def verdict(licence: str) -> str:
    """«denied», «unknown» or «ok» for one licence expression. With «OR» one acceptable choice is enough."""
    text = (licence or "").strip()
    if not text or text.upper() in {"UNKNOWN", "UNLICENSED", "NOASSERTION"}:
        return "unknown"
    choices = re.split(r"\s+OR\s+|;\s*", text.strip("()")) if re.search(r"\sOR\s|;", text) else [text]
    bad = [c for c in choices if DENIED.search(WEAK.sub("", c))]
    return "denied" if len(bad) == len(choices) else "ok"


def packages(report) -> list[tuple[str, str]]:
    """(name, licence) pairs from a pip-licenses list or a license-checker object."""
    if isinstance(report, list):
        return [(str(p.get("Name")), str(p.get("License") or "")) for p in report]
    rows = []
    for name, info in report.items():
        licence = info.get("licenses")
        rows.append((name.rsplit("@", 1)[0], " OR ".join(licence) if isinstance(licence, list) else str(licence or "")))
    return rows


def check(reports: list) -> tuple[list[str], list[str], collections.Counter]:
    denied, unknown, summary = [], [], collections.Counter()
    for report in reports:
        for name, licence in packages(report):
            summary[licence or "UNKNOWN"] += 1
            result = verdict(licence)
            if result == "denied" and name not in ALLOWED:
                denied.append(f"{name}: {licence}")
            elif result == "unknown" and name not in ALLOWED:
                unknown.append(name)
    return sorted(denied), sorted(unknown), summary


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    denied, unknown, summary = check([json.load(open(path, encoding="utf-8")) for path in argv])
    for licence, count in summary.most_common():
        print(f"{count:5d}  {licence}")
    if unknown:
        print(f"::warning::licence not stated by {len(unknown)} packages: {', '.join(unknown[:20])}")
    for line in denied:
        print(f"::error::copyleft or source-available licence: {line}")
    print(f"licences: {sum(summary.values())} packages, {len(denied)} denied, {len(unknown)} unknown")
    return 1 if denied else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
