"""20.0.5: a lost YooKassa response must not open a second charge."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_live_version_is_20_0_5():
    (ROOT / "deploy/install-vps.sh").read_text()
    (ROOT / "scripts/build-release.sh").read_text()


def test_reconciliation_uses_the_lookup_not_a_new_payment():
    # The admin reconciliation: behaviour in tests/test_behaviour_payments_v2.py (BACKLOG A1). The background scheduler is an
    # endless loop, so here only that it calls the same lookup and never create().
    scheduler = (ROOT / "backend/app/schedulers.py").read_text()
    assert scheduler.count("find_by_order_id(p.order_id, p.created_at)") == 1
    assert "provider.create(" not in scheduler


def test_changelog_is_in_the_root_readme():
    readme = (ROOT / "docs/archive/README_BEFORE_WORKSPACE.md").read_text()
    assert "## Changelog" in readme
    assert "### 20.0.5" in readme
    assert "## Русский" in readme and "## English" in readme and "## Українська" in readme
    assert "find_by_order_id" in readme
    assert "Ниже сохранена история релизов." in readme
    assert "20.0.5" in (ROOT / "docs/archive/SECURITY_BEFORE_ALPHA_6.md").read_text()
