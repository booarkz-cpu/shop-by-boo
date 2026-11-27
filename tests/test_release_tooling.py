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
    support_readme = (ROOT / "services/support-pro/README.md").read_text().split("\n# ", 1)[0]
    assert f"В рабочей ветке ревизия Alembic — `{support}`" in support_readme
    manifest = json.loads((ROOT / "release-manifest.template.json").read_text())
    if manifest["distribution_tag"] == PUBLISHED_TAG:
        published_row = f"| Опубликованный {PUBLISHED_TAG} | `{manifest['migration_head']}` | `{manifest['support_migration_head']}` |"
        assert published_row in table
        assert f"В выпуске `{PUBLISHED_TAG}` ревизия Support Pro — `{manifest['support_migration_head']}`" in support_readme
    else:
        assert (manifest["migration_head"], manifest["support_migration_head"]) == (shop, support)


def test_readmes_show_published_and_source_migrations():
    from scripts.audit.check_release_readiness import PUBLISHED_TAG

    table = (ROOT / "docs/EXTERNAL_DEPENDENCIES.md").read_text()
    published_shop, published_support = re.findall(
        rf"^\| Опубликованный {re.escape(PUBLISHED_TAG)} \| `([^`]+)` \| `([^`]+)` \|", table, re.M
    )[0]
    support = ScriptDirectory(str(ROOT / "services/support-pro/alembic")).get_current_head()
    shop = migration_head()
    row = f"| Support Pro · Alembic | `{published_support}` | `{support}` |"
    for name in ("README.md", "README.en.md", "README.uk.md"):
        text = (ROOT / name).read_text()
        assert row in text, name
        assert all(f"`{rev}`" in text for rev in (shop, published_shop)), name
    for language in ("ru", "en", "uk"):
        text = (ROOT / "docs" / language / "README.md").read_text()
        assert all(f"`{rev}`" in text for rev in (shop, published_shop, support, published_support)), language
