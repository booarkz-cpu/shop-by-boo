from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[1]

def test_staging_e2e_runner_exists_and_is_safe():
    p=ROOT/'scripts'/'staging-e2e.sh'
    s=p.read_text()
    assert p.exists() and p.stat().st_mode & 0o111
    assert 'STAGING_REMNAWAVE_TOKEN' in s
    assert 'STAGING_RUNNER_TOKEN' in s
    assert all(x in s for x in ('yookassa','platega','rollypay'))
    assert 'https://*)' in s
    assert 'set -Eeuo pipefail' in s

def test_provider_endpoints_are_configurable():
    from app.config import Settings
    assert {'yookassa_api_url', 'platega_api_url', 'rollypay_api_url', 'rollypay_test_mode'} <= set(Settings.model_fields)


@pytest.mark.asyncio
async def test_staging_rollypay_payments_are_always_test_payments(monkeypatch):
    from app import main, payments
    sent = []

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None, auth=None):
            sent.append((url, json))
            return type("R", (), {"raise_for_status": lambda self: None,
                                  "json": lambda self: {"id": "rp-1", "url": "https://rollypay.example/pay"}})()
    monkeypatch.setattr(main, "_pinned_public_http_client", lambda timeout: Client())
    monkeypatch.setattr(main, "validate_public_url", lambda value, **kw: value)
    await payments.staging_create_payment("rollypay", {"api_url": "https://sandbox.rollypay.example", "api_key": "k"},
                                          payments.Decimal("10"), "stage-1", "test", "https://staging.example/paid")
    url, body = sent[0]
    assert url == "https://sandbox.rollypay.example/api/v1/payments" and body["test"] is True and body["order_id"] == "stage-1"
