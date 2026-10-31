#!/usr/bin/env python3
"""Report the Alembic revision graph heads without importing Alembic.

`alembic heads` needs the backend dependencies installed (asyncpg, aiogram,
Pillow and friends) because it imports the application environment. This script
only reads the revision identifiers out of the migration sources, so a CI job
can verify "exactly one head" in a second, with no network and no venv.

A revision is a head when no other revision names it as a parent. A branched
graph has more than one head and cannot be upgraded to a single state, which is
what this check exists to catch.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSIONS = ROOT / "backend" / "alembic" / "versions"


def _literal(node: ast.AST):
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError):
        return None


def read_revisions(folder: Path) -> dict[str, tuple[str, ...]]:
    """Map revision id -> tuple of parent revision ids, for every migration file."""
    graph: dict[str, tuple[str, ...]] = {}
    problems: list[str] = []
    for path in sorted(folder.glob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            problems.append(f"{path.name}: cannot parse ({exc})")
            continue
        revision = None
        down = None
        for node in tree.body:
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            if not isinstance(target, ast.Name):
                continue
            if target.id == "revision":
                revision = _literal(node.value)
            elif target.id == "down_revision":
                down = _literal(node.value)
        if not isinstance(revision, str) or not revision:
            problems.append(f"{path.name}: no module-level revision string")
            continue
        if isinstance(down, str):
            parents: tuple[str, ...] = (down,) if down else ()
        elif isinstance(down, (tuple, list)):
            parents = tuple(str(item) for item in down if item)
        elif down is None:
            parents = ()
        else:
            problems.append(f"{path.name}: down_revision is not a string, tuple or None")
            continue
        graph[revision] = parents
    if problems:
        raise SystemExit("Migration sources are unreadable:\n  " + "\n  ".join(problems))
    return graph


def heads(graph: dict[str, tuple[str, ...]]) -> list[str]:
    parents = {parent for value in graph.values() for parent in value}
    return sorted(revision for revision in graph if revision not in parents)


def missing_parents(graph: dict[str, tuple[str, ...]]) -> list[tuple[str, str]]:
    return sorted((child, parent) for child, values in graph.items() for parent in values if parent not in graph)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", default=str(VERSIONS), help="directory with migration files")
    parser.add_argument("--expect", type=int, default=1, help="required number of heads (default 1)")
    args = parser.parse_args()

    folder = Path(args.folder)
    if not folder.is_dir():
        raise SystemExit(f"Migration folder not found: {folder}")

    graph = read_revisions(folder)
    if not graph:
        raise SystemExit(f"No migration files found in {folder}")

    found = heads(graph)
    dangling = missing_parents(graph)
    print(f"revisions: {len(graph)}")
    for head in found:
        print(f"head: {head}")

    status = 0
    if dangling:
        for child, parent in dangling:
            print(f"::error title=Migration graph::revision {child} has unknown parent {parent}")
        status = 1
    if len(found) != args.expect:
        print(f"::error title=Migration heads::expected {args.expect} head, found {len(found)}: {', '.join(found)}")
        status = 1
    if not status:
        print(f"migration graph OK: {len(found)} head")
    return status


if __name__ == "__main__":
    sys.exit(main())
