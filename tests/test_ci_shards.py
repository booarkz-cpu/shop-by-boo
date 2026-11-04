"""v28.74.0: the two halves of the backend suite in CI together run every test file exactly once."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_shards_cover_every_test_file_once():
    spec = importlib.util.spec_from_file_location("test_shard", ROOT / "scripts/ci/test-shard.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    halves = mod.shards(2)
    every = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "tests").rglob("test_*.py") if "__pycache__" not in p.parts)
    assert sorted(halves[0] + halves[1]) == every and not set(halves[0]) & set(halves[1])
    assert all(halves) and "tests/test_ci_shards.py" in every
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()
    assert "shard: [1, 2]" in workflow and 'scripts/ci/test-shard.py "${{ matrix.shard }}" 2' in workflow
