#!/usr/bin/env python3
"""Print the test files of one half of the backend suite (CI job «Backend», v28.139.0).

    python scripts/ci/test-shard.py 1 2   # files of shard 1 of 2, one per line

Every ``tests/**/test_*.py`` goes to exactly one shard. Files are spread by size (lines of code, a stand-in for
running time), largest first onto the lightest shard, so the split is deterministic and roughly even. Together
the shards run the same files as ``pytest tests``."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def shards(count: int, root: Path = ROOT) -> list[list[str]]:
    files = sorted(p.relative_to(root).as_posix() for p in (root / "tests").rglob("test_*.py") if "__pycache__" not in p.parts)
    weight = {f: max(1, sum(1 for _ in (root / f).open(encoding="utf-8", errors="replace"))) for f in files}
    out: list[list[str]] = [[] for _ in range(count)]
    load = [0] * count
    for f in sorted(files, key=lambda f: (-weight[f], f)):
        i = load.index(min(load))
        out[i].append(f)
        load[i] += weight[f]
    return [sorted(s) for s in out]


def main(argv: list[str]) -> int:
    index, count = int(argv[1]), int(argv[2])
    if not 1 <= index <= count:
        print("shard index out of range", file=sys.stderr)
        return 2
    print("\n".join(shards(count)[index - 1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
