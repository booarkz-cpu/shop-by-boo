"""Release tooling states the real Alembic head."""
import re

from app_contract import ROOT, migration_head


def test_build_release_names_the_current_migration_head():
    text = (ROOT / "scripts/build-release.sh").read_text()
    stated = re.search(r"^# Current migration head: (\S+)", text, re.M).group(1)
    assert stated == migration_head()
