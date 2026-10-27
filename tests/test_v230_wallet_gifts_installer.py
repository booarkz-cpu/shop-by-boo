from main_source import main_source
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_one_step_installer_delegates_and_does_not_publish_app_ports():
    text = (ROOT / "install.sh").read_text()
    assert "deploy/install-vps.sh" in text
    assert "exec bash" in text
    assert "8000/tcp" not in text
    assert "3000/tcp" not in text


def test_vps_installer_collects_operator_settings():
    text = (ROOT / "deploy/install-vps.sh").read_text()
    for key in (
        "BOT_USERNAME",
        "DEFAULT_LANGUAGE",
        "REQUIRED_TELEGRAM_CHANNEL",
        "AUTO_RENEW_LEAD_DAYS",
        "WEBHOOK_BASE_URL",
        "INSTALL_NONINTERACTIVE",
    ):
        assert key in text
    assert "ufw allow 80/tcp" in text
    assert "8000/tcp" not in text


def test_wallet_gifts_and_days_promo_are_wired():
    from decimal import Decimal

    from app import main as shop
    from app_contract import columns, missing_routes, revision
    assert not missing_routes("POST /api/me/wallet/topup", "POST /api/me/wallet/spend", "POST /api/me/gifts/purchase", "POST /api/me/gifts/redeem")
    assert "wallet_balance" in columns("users") and "purchaser_user_id" in columns("gift_codes")
    assert revision("0035_v2_3_0_wallet_gifts").down_revision == "0034_v2_2_0_platform_features"
    # A «days» promo adds time, it is never a cash discount; percent and fixed are capped by the price.
    assert shop.discounted_amount(100, "days", 7) == Decimal("0.00")
    assert shop.discounted_amount(199, "percent", 15) == Decimal("29.85")
    assert shop.discounted_amount(100, "fixed", 500) == Decimal("100.00")
    assert shop.discounted_amount(100, "fixed", -5) == Decimal("0.00")
    # The purchaser cannot redeem their own gift: test_v2_0_0_product_and_critical_audit.py.


def test_v230_release_markers_remain_as_history():
    main_source()
