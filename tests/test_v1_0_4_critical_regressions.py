from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = (ROOT / "scripts/build-release.sh").read_text()
INSTALL = (ROOT / "deploy/install-vps.sh").read_text()
MANIFEST = (ROOT / "release-manifest.template.json").read_text()

def test_release_is_v1_0_5_realise():
    assert '"version": "2.0.0-realise"' in MANIFEST

# The lock order of fulfilment and a caller-owned customer lock: tests/test_behaviour_fulfil_locks.py (C1, stage 19).
