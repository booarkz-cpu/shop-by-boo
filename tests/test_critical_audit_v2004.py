"""20.0.4 version identity and unauthenticated control-plane routes."""
from pathlib import Path

import pytest

from app_contract import permissions

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.asyncio
async def test_node_control_and_public_release_are_closed():
    from fastapi import HTTPException

    from app import main as shop
    from app import production_launch_api as launch
    for path in ("/api/admin/v16/nodes/register", "/api/admin/v16/nodes/{node_name}/failover"):
        assert permissions("POST", path) == {"provision_nodes"}
    for call in (launch.register_node(None), launch.node_failover("de-1", None)):
        with pytest.raises(HTTPException) as gone:
            await call
        assert gone.value.status_code == 410, "the old routes say where the real mechanism is"
    public = await launch.release()
    assert public["release"] == shop.APP_VERSION and "token" not in str(public).lower()
    assert (await shop.health_live())["version"] == shop.APP_VERSION


def test_updater_points_at_this_repository():
    import importlib.util

    from app import github_update
    spec = importlib.util.spec_from_file_location("release_fetch_2004", ROOT / "scripts/github_release_fetch.py")
    fetch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fetch)
    assert github_update.GITHUB_REPO == fetch.REPO == "booarkz-cpu/shop-by-boo"
    assert github_update.DOWNLOAD_PREFIX.startswith("https://github.com/booarkz-cpu/shop-by-boo/releases/download/")
    assert "https://github.com/booarkz-cpu/shop-by-boo.git" in (ROOT / "install.sh").read_text()


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
