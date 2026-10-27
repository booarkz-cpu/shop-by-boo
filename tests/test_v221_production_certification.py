import ast
from pathlib import Path

import pytest

from test_subscription_commerce import database  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]


def test_payment_provider_never_uses_unpinned_http_client():
    tree = ast.parse((ROOT / "backend/app/payments.py").read_text())
    offenders=[]
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "AsyncClient":
            offenders.append(node.lineno)
    assert offenders == [], f"Direct httpx.AsyncClient bypasses DNS pinning at lines {offenders}"


@pytest.mark.asyncio
async def test_payment_module_routes_outbound_http_through_pinned_helper():
    from app import payments
    from app.main import _PinnedPublicDNSBackend
    client = payments._public_client(20)
    try:
        assert client._transport._pool._network_backend.__class__ is _PinnedPublicDNSBackend and client.follow_redirects is False
        assert client.timeout.read == 20
    finally:
        await client.aclose()


def test_release_verifier_is_not_hardcoded_to_historical_artifact():
    text=(ROOT/"scripts/verify-release.sh").read_text()
    assert "remnawave_vpn_shop_v40_production.zip" not in text
    assert "find . -maxdepth 1 -type f -name 'remnawave_vpn_shop_*.zip'" in text
    assert "hashlib.sha256()" in text


@pytest.mark.asyncio
async def test_auto_renew_advertises_only_implemented_provider(database):
    from app import main as shop
    out = await shop.auto_renew_status(None, database)
    assert out["supported_providers"] == ["yookassa"]
