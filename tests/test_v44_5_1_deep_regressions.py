from main_source import main_source
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = main_source()


def test_release_version_bumped():
    assert 'APP_VERSION = "44.5.5-enterprise"' in MAIN


def test_provider_routing_honors_admin_enabled_flag():
    start = MAIN.index('async def _payment_provider_order')
    end = MAIN.index('@app.post("/api/payments/create")', start)
    section = MAIN[start:end]
    assert 'and x.enabled' in section


def test_provider_routing_requires_creation_credentials():
    start = MAIN.index('async def _payment_provider_order')
    end = MAIN.index('@app.post("/api/payments/create")', start)
    section = MAIN[start:end]
    assert 'configured = {' in section
    assert '"yookassa": bool(settings.yookassa_shop_id and settings.yookassa_secret_key and settings.yookassa_webhook_ip_allowlist)' in section
    assert '"platega": bool(settings.platega_merchant_id and settings.platega_secret)' in section
    assert '"rollypay": bool(settings.rollypay_api_key and settings.rollypay_signing_secret)' in section
    assert 'and configured.get(x.provider, False)' in section
