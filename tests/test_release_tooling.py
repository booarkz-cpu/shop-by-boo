"""Release tooling states the real Alembic head."""
import json
import re

from alembic.script import ScriptDirectory

from app_contract import ROOT, migration_head


def test_build_release_names_the_current_migration_head():
    text = (ROOT / "scripts/build-release.sh").read_text()
    stated = re.search(r"^# Current migration head: (\S+)", text, re.M).group(1)
    assert stated == migration_head()


def test_migration_table_identifies_both_source_and_published_revisions():
    from scripts.audit.check_release_readiness import PUBLISHED_TAG

    support = ScriptDirectory(str(ROOT / "services/support-pro/alembic")).get_current_head()
    shop = migration_head()
    table = (ROOT / "docs/EXTERNAL_DEPENDENCIES.md").read_text()
    assert f"| Текущая рабочая ветка main | `{shop}` | `{support}` |" in table
    manifest = json.loads((ROOT / "release-manifest.template.json").read_text())
    if manifest["distribution_tag"] == PUBLISHED_TAG:
        published_row = f"| Опубликованный {PUBLISHED_TAG} | `{manifest['migration_head']}` | `{manifest['support_migration_head']}` |"
        assert published_row in table
    else:
        assert (manifest["migration_head"], manifest["support_migration_head"]) == (shop, support)
