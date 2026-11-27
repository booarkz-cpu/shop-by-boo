#!/usr/bin/env python3
"""Validate the table contract of new release notes; this is not a grammar or completeness proof."""
from __future__ import annotations

import argparse
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
    return validate_notes(root, tag, manifest["release_notes"])


def validate_notes(root: Path, tag: str, relative: str) -> str:
    notes_path = (root / relative).resolve()
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



def validate_client(root: Path, version: str) -> str:
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("Invalid client version")
    return validate_notes(root, f"client-v{version}", f"docs/releases/client-v{version}.md")


def validate_current_client(root: Path) -> str:
    gradle = (root / "apps/vpn-client/android/app/build.gradle.kts").read_text(encoding="utf-8")
    match = re.search(r'versionName\s*=\s*"(\d+\.\d+\.\d+)"', gradle)
    if not match:
        raise ValueError("Client version was not found")
    # This exact version was already published before the new owner requirement.
    if match.group(1) == "1.10.1":
        return "client-v1.10.1: published legacy notes preserved"
    return validate_client(root, match.group(1))


def gradle_version(gradle: str) -> tuple[str, int]:
    names = re.findall(r'^\s*versionName\s*=\s*"(\d+\.\d+\.\d+)"[ \t]*$', gradle, re.MULTILINE)
    codes = re.findall(r"^\s*versionCode\s*=\s*([1-9]\d*)[ \t]*$", gradle, re.MULTILINE)
    if len(names) != 1 or len(codes) != 1:
        raise ValueError("Expected one release version in Gradle settings")
    return names[0], int(codes[0])


def mobile_version(root: Path, app: str) -> tuple[str, int]:
    return gradle_version((root / "apps" / app / "android/app/build.gradle.kts").read_text(encoding="utf-8"))


def current_mobile_tag(root: Path) -> str:
    family, code = mobile_version(root, "vpn-shop")
    if mobile_version(root, "lucy-admin") != (family, code):
        raise ValueError("Shop and admin mobile versions differ")
    client, client_code = mobile_version(root, "vpn-client")
    return f"mobile-v{family}-{code}-client-v{client}-{client_code}"


def validate_mobile(root: Path, tag: str) -> str:
    if tag != current_mobile_tag(root):
        raise ValueError("Mobile release tag must match the source versions and build numbers")
    return validate_notes(root, tag, f"docs/releases/{tag}.md")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--client-version")
    selection.add_argument("--mobile-tag")
    args = parser.parse_args()
    try:
        if args.client_version is not None:
            print(validate_client(ROOT, args.client_version))
        elif args.mobile_tag is not None:
            print(validate_mobile(ROOT, args.mobile_tag))
        else:
            print(validate(ROOT))
            print(validate_current_client(ROOT))
            print(validate_mobile(ROOT, current_mobile_tag(ROOT)))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Release changelog check failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
