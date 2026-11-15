"""Expired store receipts cannot create a paid shop subscription."""
import importlib
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest


@pytest.fixture
def platform(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "services" / "backend"))
    return importlib.import_module("app.payment_platform")


@pytest.mark.asyncio
@pytest.mark.parametrize("offset,accepted", [(-60_000, False), (60_000, True)])
async def test_apple_subscription_expiry(platform, monkeypatch, offset, accepted):
    provider = platform.AppleStorePlatform()
    monkeypatch.setattr(platform.settings, "apple_bundle_id", "com.example.shop")
    monkeypatch.setattr(platform.settings, "apple_issuer_id", "issuer")
    monkeypatch.setattr(platform.settings, "apple_key_id", "key")
    monkeypatch.setattr(platform.settings, "apple_private_key", "private-key")
    monkeypatch.setattr(provider, "get_transaction", AsyncMock(return_value={"signedTransactionInfo": "server-jws"}))
    receipt = {"transactionId": "123", "bundleId": "com.example.shop", "expiresDate": int(time.time() * 1000) + offset}
    monkeypatch.setattr(platform.jwt, "decode", lambda *_args, **_kwargs: receipt)
    if accepted:
        assert (await provider.verify_transaction("client-jws"))["transactionId"] == "123"
    else:
        with pytest.raises(platform.PlatformProviderError, match="expired"):
            await provider.verify_transaction("client-jws")


@pytest.mark.asyncio
@pytest.mark.parametrize("days,accepted", [(-1, False), (1, True)])
async def test_google_subscription_expiry(platform, monkeypatch, days, accepted):
    provider = platform.GooglePlayPlatform()
    monkeypatch.setattr(provider, "_access_token", AsyncMock(return_value="token"))
    monkeypatch.setattr(platform.settings, "google_play_package", "com.example.shop")
    expiry = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
    payload = {"subscriptionState": "SUBSCRIPTION_STATE_ACTIVE", "lineItems": [{"productId": "monthly", "expiryTime": expiry}]}
    monkeypatch.setattr(platform, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))))
    if accepted:
        assert (await provider.verify_subscription("purchase-token"))["productId"] == "monthly"
    else:
        with pytest.raises(platform.PlatformProviderError, match="expired"):
            await provider.verify_subscription("purchase-token")
