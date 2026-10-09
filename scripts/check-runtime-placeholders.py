#!/usr/bin/env python3
"""Reject placeholder constructs in production Python and migration sources."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOTS = (
    ROOT / "backend" / "app",
    ROOT / "backend" / "alembic",
    ROOT / "support-pro" / "app",
    ROOT / "scripts",
)


def is_allowed_pass(node: ast.Pass, parents: dict[ast.AST, ast.AST]) -> bool:
    """No production pass statements are allowed, including empty handlers."""
    return False


def scan(path: Path) -> list[str]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    failures: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Pass) and not is_allowed_pass(node, parents):
            failures.append(f"{path.relative_to(ROOT)}:{node.lineno}: pass")
        if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
            target = node.exc.func
            if isinstance(target, ast.Name) and target.id == "NotImplementedError":
                failures.append(f"{path.relative_to(ROOT)}:{node.lineno}: NotImplementedError")
    for marker in ("TODO", "FIXME", "// rest of code", "/* ... */"):
        if marker in source:
            failures.append(f"{path.relative_to(ROOT)}: contains {marker!r}")
    return failures


def main() -> None:
    failures: list[str] = []
    for source_root in SOURCE_ROOTS:
        for path in sorted(source_root.rglob("*.py")):
            if "tests" not in path.parts and path.resolve() != Path(__file__).resolve():
                failures.extend(scan(path))
    if failures:
        raise SystemExit("Runtime placeholders found:\n" + "\n".join(failures))
    print("runtime placeholder contract OK")


if __name__ == "__main__":
    main()
