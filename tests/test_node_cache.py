"""Node status is fetched from Remnawave once per 30 s for all processes (Redis) and never shows addresses to customers."""
import pytest

from app import node_health
from app.tariff_api import remnawave_server_status

RAW = {"response": [{"uuid": "n-1", "name": "Frankfurt", "address": "203.0.113.7", "countryCode": "DE", "isConnected": True, "usersOnline": 3,
                     "xrayVersion": "25.9.11"},
                    {"uuid": "n-2", "name": "Helsinki", "address": "198.51.100.2", "countryCode": "FI", "isConnected": False}]}


class Redis:
    def __init__(self):
        self.data, self.ttl = {}, {}

    async def get(self, key):
        return self.data.get(key)

    async def set(self, key, value, ex=None):
        self.data[key], self.ttl[key] = value, ex


class Panel:
    calls = 0

    async def list_nodes(self, start=0, size=25):
        Panel.calls += 1
        return RAW


@pytest.mark.asyncio
async def test_one_remnawave_request_serves_every_reader(monkeypatch):
    redis = Redis()
    monkeypatch.setattr(node_health, "_redis", lambda: redis)
    monkeypatch.setattr("app.remnawave.RemnawaveClient", Panel)
    Panel.calls = 0
    first = await node_health.node_snapshot()
    second = await node_health.node_snapshot()
    assert Panel.calls == 1 and (first["cached"], second["cached"]) == (False, True)
    assert redis.ttl[node_health.CACHE_KEY] == node_health.CACHE_TTL
    assert second["nodes"][0] == {**second["nodes"][0], "uuid": "n-1", "status": "online", "xray_version": "25.9.11", "address": "203.0.113.7"}
    await node_health.node_snapshot(force=True)
    assert Panel.calls == 2, "the monitor can force a fresh read"


@pytest.mark.asyncio
async def test_customers_get_the_cached_list_without_addresses(monkeypatch):
    monkeypatch.setattr(node_health, "_redis", lambda: Redis())
    monkeypatch.setattr("app.remnawave.RemnawaveClient", Panel)
    out = await remnawave_server_status("public")
    assert (out["ok"], out["total"], out["online"], out["offline"]) == (True, 2, 1, 1)
    assert "203.0.113.7" not in str(out) and "n-1" not in str(out)


@pytest.mark.asyncio
async def test_remnawave_down_is_reported_not_cached(monkeypatch):
    redis = Redis()

    class Down:
        async def list_nodes(self, **kw):
            raise RuntimeError("timeout")
    monkeypatch.setattr(node_health, "_redis", lambda: redis)
    monkeypatch.setattr("app.remnawave.RemnawaveClient", Down)
    snap = await node_health.node_snapshot()
    assert snap["error"] and snap["nodes"] == [] and node_health.CACHE_KEY not in redis.data
    assert (await remnawave_server_status("public"))["ok"] is False
