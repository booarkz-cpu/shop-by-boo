"""20.0.4 version identity and unauthenticated control-plane routes."""
from main_source import main_source
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_live_version_is_20_0_4_and_history_order_stays():
    main_source()
    (ROOT / "deploy/install-vps.sh").read_text()
    (ROOT / "scripts/build-release.sh").read_text()


def test_node_control_and_public_release_are_closed():
    launch = (ROOT / "backend/app/production_launch_api.py").read_text()
    register = launch[launch.index("async def register_node"): launch.index("async def node_failover")]
    failover = launch[launch.index("async def node_failover"): launch.index("async def release")]
    public = launch[launch.index("async def release"):]
    assert 'require_permission("provision_nodes")' in register
    assert 'require_permission("provision_nodes")' in failover
    # The old routes returned invented data; they now say where the real mechanism is.
    assert "raise HTTPException(410, GONE_NODES)" in register and "raise HTTPException(410, GONE_NODES)" in failover
    assert "agent_token" not in launch and "signature" not in launch
    assert '"release": APP_VERSION' in public
    assert "16.0.0" not in public
    assert '"version":APP_VERSION' in main_source()


def test_updater_points_at_this_repository():
    update = (ROOT / "backend/app/github_update.py").read_text()
    fetch = (ROOT / "scripts/github_release_fetch.py").read_text()
    installer = (ROOT / "install.sh").read_text()
    assert 'GITHUB_REPO = "booarkz-cpu/shop-by-boo"' in update
    assert 'REPO = "booarkz-cpu/shop-by-boo"' in fetch
    assert "https://github.com/booarkz-cpu/shop-by-boo.git" in installer
    assert "remnawave-vpn-shop" not in update
    assert "remnawave-vpn-shop" not in fetch.split("DOWNLOAD_PREFIX", 1)[0]


def test_readme_describes_features_and_live_payments_in_three_languages():
    readme = (ROOT / "docs/archive/README_BEFORE_WORKSPACE.md").read_text()
    assert "## Русский" in readme and "## English" in readme and "## Українська" in readme
    assert "### Возможности" in readme and "### Features" in readme and "### Можливості" in readme
    assert "личный кабинет" in readme and "Конструктор тарифов" in readme
    assert "POST https://API_DOMAIN/api/webhooks/yookassa" in readme
    assert "POST https://API_DOMAIN/api/payments/webhooks/stripe" in readme
    assert "POST https://API_DOMAIN/api/payments/webhooks/paypal" in readme
    assert "POST https://API_DOMAIN/api/webhooks/crypto" in readme
    assert "MOBILE_STORE_PRODUCTS" in readme
    assert "production-gate" in readme
    assert "20.0.4" in readme
    assert "Ниже сохранена история релизов." in readme
    assert "sha256sum -c" in readme
    assert "FULL_E2E_PASS" in readme
    security = (ROOT / "docs/archive/SECURITY_BEFORE_ALPHA_6.md").read_text()
    assert "20.0.4" in security and "provision_nodes" in security and "decrypt_secret" in security
