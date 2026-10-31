#!/usr/bin/env python3
"""Fail on broken relative links, images and Markdown anchors in README and live docs.

CI runs this on every push: a link to a file that was moved, renamed or never created breaks the
first thing a new operator opens.

Two sets of documents are historical records rather than live instructions, so they are counted and
reported but do not fail the run — rewriting a released note would falsify the record:

* ``docs/archive`` — snapshots copied with flattened file names, so their relative links point at paths
  that never existed in that layout;
* ``.github/release-v*.md`` — release notes of the v20/v21 line, whose referenced guides were moved
  when the documentation was reorganised. The current release notes live in ``docs/ru/RELEASE_*.md``
  and are checked like every other live document.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {"node_modules", ".git", "dist", ".next"}
DOCS = [ROOT / "README.md"] + sorted(
    p for p in ROOT.rglob("*.md")
    if p.is_file() and not any(part in SKIP_DIRS for part in p.relative_to(ROOT).parts)
)

# `[text](target)` and `![alt](target)`; the target may carry a title in quotes.
LINK = re.compile(r"!?\[[^\]]*\]\(\s*([^)\s]+?)(?:\s+\"[^\"]*\")?\s*\)")
ANCHOR_LINK = re.compile(r"\[[^\]]*\]\(#([^)]+)\)")
HEADING = re.compile(r"^#{1,6}\s+(.*)$", re.M)


def slug(text: str) -> str:
    """GitHub's heading anchor: lower-case, punctuation dropped, spaces to dashes."""
    text = text.strip().lower()
    text = re.sub(r"`|\*|_", "", text)
    text = re.sub(r"[^\w\s\u0400-\u04FF-]", "", text)
    return text.replace(" ", "-")


def check(path: Path) -> list[str]:
    problems: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [f"{path.relative_to(ROOT)}: unreadable ({exc})"]
    anchors = {slug(m.group(1)) for m in HEADING.finditer(text)}
    for match in LINK.finditer(text):
        target = match.group(1)
        if target.startswith(("http://", "https://", "mailto:", "#", "data:")):
            continue
        file_part = unquote(target.split("#")[0])
        if not file_part:
            continue
        resolved = (path.parent / file_part).resolve()
        if not resolved.exists():
            problems.append(f"{path.relative_to(ROOT)}: missing {target}")
    for match in ANCHOR_LINK.finditer(text):
        if match.group(1) not in anchors:
            problems.append(f"{path.relative_to(ROOT)}: missing anchor #{match.group(1)}")
    return problems


def main() -> None:
    def historical(path: Path) -> bool:
        rel = path.relative_to(ROOT)
        return "archive" in rel.parts or (rel.parts[0] == ".github" and rel.name.startswith("release-"))

    live = [p for p in DOCS if not historical(p)]
    archived = [p for p in DOCS if historical(p)]
    problems: list[str] = []
    for path in live:
        problems.extend(check(path))
    if problems:
        for problem in problems[:80]:
            print(problem)
        print(f"\n{len(problems)} broken reference(s) in {len(live)} live Markdown files")
        raise SystemExit(1)
    known = sum(len(check(path)) for path in archived)
    print(f"documentation links OK: {len(live)} live Markdown files, no broken links or anchors")
    print(f"archive: {len(archived)} historical files, {known} stale relative links (not fixed on purpose)")


if __name__ == "__main__":
    main()
