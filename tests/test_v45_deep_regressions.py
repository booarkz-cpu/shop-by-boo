import asyncio
from pathlib import Path

import pytest

from app import main as shop
from test_behaviour_payments_v2 import FakeRedis
from test_subscription_commerce import database  # noqa: F401

ROOT=Path(__file__).resolve().parents[1]
MANIFEST=(ROOT/'release-manifest.template.json').read_text()


def test_release_is_v45():
    assert '"version": "1.0.0-realise"' in MANIFEST


@pytest.mark.asyncio
async def test_distributed_locks_are_renewed_until_release(monkeypatch):
    class Redis(FakeRedis):
        renewals = 0

        async def eval(self, script, n, key, token, *ttl):
            if ttl:
                Redis.renewals += 1
            return await super().eval(script, n, key, token, *ttl)
    redis = Redis()
    monkeypatch.setattr(shop, "redis_client", redis)
    real_sleep = asyncio.sleep

    async def fast(seconds):
        await real_sleep(0)
    monkeypatch.setattr(shop.asyncio, "sleep", fast)
    key, token = await shop._acquire_redis_lock("lock:long", ttl=3, conflict_message="busy")
    for _ in range(5):
        await real_sleep(0)
    assert Redis.renewals >= 2, "a long side effect keeps its lease"
    task = shop._LOCK_RENEW_TASKS[token]
    await shop._release_payment_side_effect_lock(key, token)
    await real_sleep(0)
    assert task.cancelled() or task.done(), "the renewal stops with the release"


# The trial and the lifecycle stop for deleted accounts: test_integration_billing_vpn.py,
# test_v2_0_0_product_and_critical_audit.py; refund paths take user → payment locks: test_v2_0_0….
@pytest.mark.asyncio
async def test_auto_renew_never_charges_a_deleted_account(database, monkeypatch):
    from datetime import datetime

    from app.models import User
    from test_money_review import _renewable, _scheduler_env
    charges = []
    _scheduler_env(monkeypatch, database, charges)
    await _renewable(database)
    (await database.get(User, 1)).deleted_at = datetime.utcnow()
    await database.commit()
    await shop.run_auto_renew_pass(database)
    assert charges == []


@pytest.mark.asyncio
async def test_monitoring_connections_are_pinned_to_the_checked_public_address(monkeypatch):
    client = shop._pinned_public_http_client(5)
    assert client.follow_redirects is False and client._transport._pool._network_backend.__class__ is shop._PinnedPublicDNSBackend
    await client.aclose()
    backend = shop._PinnedPublicDNSBackend()
    connected = []

    class Inner:
        async def connect_tcp(self, host, port, *a):
            connected.append(host)
    backend._backend = Inner()
    monkeypatch.setattr(shop.socket, "getaddrinfo", lambda host, port, type=None: [(2, 1, 6, "", ("93.184.215.14", port))])
    await backend.connect_tcp("status.example.com", 443)
    assert connected == ["93.184.215.14"], "the socket goes to the checked IP, no second lookup"
    monkeypatch.setattr(shop.socket, "getaddrinfo", lambda host, port, type=None: [(2, 1, 6, "", ("10.0.0.5", port))])
    with pytest.raises(OSError):
        await backend.connect_tcp("rebind.example.com", 443)
    with pytest.raises(OSError):
        await backend.connect_tcp("127.0.0.1", 443)


@pytest.mark.asyncio
async def test_chunked_requests_are_bounded_without_content_length():
    import httpx

    async def body():
        chunk = b"x" * (1024 * 1024)
        for _ in range(14):
            yield chunk
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=shop.app), base_url="http://localhost") as client:
        answer = await client.post("/api/payments/create", content=body(), headers={"content-type": "application/json"})
    assert answer.status_code == 413
