"""v28.58.0 (BUG-A5 / SEC-03): forms where a customer types a code are rate limited per IP.

Before, gift codes, gift cards, referral and company codes and guest access had no limit, so a script
could try codes as fast as the server answered. The 11th attempt in a minute now gets 429 before the
handler runs (the counter is the same Redis/local limiter as sign-in)."""
import uuid

import httpx
import pytest

from app import main as shop
from app import runtime_security

PATHS = ["/api/me/gifts/redeem", "/api/me/payment/gift-card/redeem", "/api/me/referral/apply",
         "/api/me/company/join", "/api/auth/guest", "/api/auth/guest/setup"]


@pytest.mark.asyncio
@pytest.mark.parametrize("path", PATHS)
async def test_eleventh_code_attempt_in_a_minute_is_refused(monkeypatch, path):
    monkeypatch.setattr(shop, "redis_client", None)
    runtime_security._LOCAL.clear()
    # A fresh address per test, so the buckets of other tests never interfere.
    ip = f"198.51.100.{uuid.uuid4().int % 250 + 1}"
    monkeypatch.setattr(shop, "_client_ip", lambda request: ip)
    transport = httpx.ASGITransport(app=shop.app)
    statuses = []
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
        for _ in range(11):
            statuses.append((await client.post(path, json={"code": "GIFT_X"})).status_code)
    assert shop.RATE_LIMITS[path] == 10
    assert 429 not in statuses[:10], statuses
    assert statuses[10] == 429
