#!/usr/bin/env python3
"""Validate the table contract of new release notes; this is not a grammar or completeness proof."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# This release was already published before REQ-DOC-0038. Never rewrite its published notes/assets.
LEGACY_TAG = "v28.161.0"
COLUMNS = ("Область", "Изменение и причина", "Подробности", "Влияние и действия", "Проверка", "PR / коммит")
SECTIONS = ("Ломающие изменения", "Миграции", "Откат", "Известные ограничения", "Чем проверено")
SOURCE = re.compile(r"https://github\.com/booarkz-cpu/shop-by-boo/(?:pull/[1-9]\d*|commit/[0-9a-f]{7,40})(?=[\s)#]|$)")
PLACEHOLDER = re.compile(r"\b(?:TO[D]O|TBD)\b|<[^>]+>|\{\{[^{}]+\}\}|заполнить|уточнить", re.IGNORECASE)


def cells(line: str) -> tuple[str, ...]:
    return tuple(value.strip().replace(r"\|", "|")
                 for value in re.split(r"(?<!\\)\|", line.strip().strip("|")))


def release_section(changelog: str, tag: str) -> str:
    match = re.search(rf"^# {re.escape(tag)}\s*$", changelog, re.MULTILINE)
    if not match:
        raise ValueError(f"CHANGELOG.md: missing release heading {tag}")
    end = re.search(r"^# ", changelog[match.end():], re.MULTILINE)
    return changelog[match.end():match.end() + end.start()] if end else changelog[match.end():]


def table_rows(text: str, label: str) -> list[tuple[str, ...]]:
    lines = text.splitlines()
    rows = []
    for index, line in enumerate(lines):
        if not line.strip().startswith("|") or cells(line) != COLUMNS:
            continue
        if index + 1 >= len(lines) or not all(
            re.fullmatch(r":?-{3,}:?", value) for value in cells(lines[index + 1])
        ) or len(cells(lines[index + 1])) != len(COLUMNS):
            raise ValueError(f"{label}: invalid table separator")
        for item in lines[index + 2:]:
            if not item.strip().startswith("|"):
                break
            row = cells(item)
            if len(row) != len(COLUMNS) or any(not value or value in {"—", "-", "…"} for value in row):
                raise ValueError(f"{label}: incomplete table row")
            if any(PLACEHOLDER.search(value) for value in row):
                raise ValueError(f"{label}: unfinished placeholder in table")
            if len(row[1]) < 12 or len(row[2]) < 40 or len(row[3]) < 12 or len(row[4]) < 12:
                raise ValueError(f"{label}: describe the change, impact and verification in detail")
            if not SOURCE.search(row[5]):
                raise ValueError(f"{label}: a repository PR/commit link is required")
            rows.append(row)
    if not rows:
        raise ValueError(f"{label}: detailed change table is required")
    if len(rows) != len(set(rows)):
        raise ValueError(f"{label}: duplicate change rows")
    return rows


def validate(root: Path) -> str:
    manifest = json.loads((root / "release-manifest.template.json").read_text(encoding="utf-8"))
    tag = manifest["distribution_tag"]
    if not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        raise ValueError("Invalid distribution tag")
    if tag == LEGACY_TAG:
        return f"{tag}: published legacy notes preserved; table contract applies to future releases"
    notes_path = (root / manifest["release_notes"]).resolve()
    if not notes_path.is_relative_to(root.resolve()):
        raise ValueError("Release notes path escapes checkout")
    notes = notes_path.read_text(encoding="utf-8")
    if not re.search(rf"^# [^\n]*{re.escape(tag)}(?=\s|$)", notes, re.MULTILINE):
        raise ValueError("Release notes must name the exact release tag")
    for section in SECTIONS:
        if not re.search(rf"^## {re.escape(section)}\s*$", notes, re.MULTILINE):
            raise ValueError(f"Release notes: missing section {section}")
    changelog = release_section((root / "CHANGELOG.md").read_text(encoding="utf-8"), tag)
    if table_rows(changelog, "CHANGELOG.md") != table_rows(notes, "release notes"):
        raise ValueError("CHANGELOG.md and release notes must contain the same ordered change rows")
    return f"{tag}: release table structure OK; editorial review and diff coverage remain required"


def main() -> int:
    try:
        print(validate(ROOT))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Release changelog check failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
