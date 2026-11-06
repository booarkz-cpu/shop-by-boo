"""The staging runner never follows redirects. The staging settings, the staging payment and the pinned DNS transport
are checked by running them in tests/test_behaviour_public_urls.py (C1, stage 19)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAGING = (ROOT / 'scripts/staging-e2e.sh').read_text()


def test_staging_runner_does_not_follow_redirects():
    assert '--max-redirs 0' in STAGING
    assert '--proto-redir "=https"' in STAGING
