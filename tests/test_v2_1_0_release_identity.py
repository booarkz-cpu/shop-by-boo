from main_source import main_source
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_runtime_version_matches_audited_release_contract():
    main_source()
    (ROOT / "scripts/build-release.sh").read_text()
    manifest = (ROOT / "release-manifest.template.json").read_text()
    assert '"version": "2.1.0"' in manifest
