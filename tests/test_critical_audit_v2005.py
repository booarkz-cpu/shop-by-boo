"""20.0.5: a lost YooKassa response must not open a second charge."""
from main_source import main_source
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_live_version_is_20_0_5():
    main = main_source()
    installer = (ROOT / "deploy/install-vps.sh").read_text()
    builder = (ROOT / "scripts/build-release.sh").read_text()
    assert main.index('APP_VERSION = "20.0.5"') < main.index('APP_VERSION = "20.0.4"')
    assert main.index('APP_VERSION = "3.1.6"') < main.index('APP_VERSION = "3.1.5"')
    assert installer.index('INSTALLER_VERSION="20.0.5"') < installer.index('INSTALLER_VERSION="20.0.4"')
    assert installer.index('INSTALLER_VERSION="3.1.6"') < installer.index('INSTALLER_VERSION="3.1.5"')
    assert builder.index('VERSION="20.0.5"') < builder.index('VERSION="20.0.4"')
    assert builder.index('VERSION="3.1.6"') < builder.index('VERSION="3.1.5"')
    assert main.index('APP_VERSION = "20.0.6"') < main.index('APP_VERSION = "20.0.5"')


def test_reconciliation_looks_up_yookassa_instead_of_creating():
    main = main_source()
    payments = (ROOT / "backend/app/payments.py").read_text()
    assert main.count("find_by_order_id(p.order_id, p.created_at)") == 2
    assert 'provider.create(Decimal(str(p.amount)),p.order_id' not in main
    start = payments.index("class YooKassaProvider")
    create = payments[start:payments.index("async def get_payment_status", start)]
    assert 'idempotence_key = str(metadata.get("order_id") or uuid.uuid4())' in create
    start_find = payments.index("async def find_by_order_id")
    finder = payments[start_find:payments.index("async def refund", start_find)]
    assert "created_at.gte" in finder
    assert "next_cursor" in finder


def test_changelog_is_in_the_root_readme():
    readme = (ROOT / "docs/archive/README_BEFORE_WORKSPACE.md").read_text()
    assert "## Changelog" in readme
    assert "### 20.0.5" in readme
    assert "## Русский" in readme and "## English" in readme and "## Українська" in readme
    assert "find_by_order_id" in readme
    assert "Ниже сохранена история релизов." in readme
    assert "20.0.5" in (ROOT / "docs/archive/SECURITY_BEFORE_ALPHA_6.md").read_text()
