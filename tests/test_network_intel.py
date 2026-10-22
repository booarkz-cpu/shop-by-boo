"""Network intelligence: DNS, private addresses, IPv6, RIPEstat/AbuseIPDB, cache freshness, rate limits."""
from datetime import datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app import network_intel as intel
from app.config import settings
from app.models import ConnectionObservation, NetworkIntel, NetworkIntelSourceState
from test_subscription_commerce import database

ADMIN = SimpleNamespace(email="admin@example.test", role="admin")
NODES = [
    {"uuid": "n1", "name": "Amsterdam-1", "status": "online", "country": "NL", "address": "nl1.vpn.example"},
    {"uuid": "n2", "name": "Amsterdam-2", "status": "online", "country": "DE", "address": "93.184.216.34"},
    {"uuid": "n3", "name": "Lab", "status": "offline", "country": None, "address": "10.0.0.5"},
    {"uuid": "n4", "name": "Broken", "status": "offline", "country": None, "address": "missing.vpn.example"},
]
DNS = {"nl1.vpn.example": ["93.184.216.35", "2001:db8::1", "2a00:1450:4001:80b::200e"]}


class Sources:
    def __init__(self):
        self.calls = []
        self.status = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        ip = request.url.params.get("resource") or request.url.params.get("ipAddress")
        host = request.url.host
        status = self.status.get(host, 200)
        if status != 200:
            return httpx.Response(status, headers={"Retry-After": "120"})
        if request.url.path.endswith("prefix-overview/data.json"):
            return httpx.Response(200, json={"data": {"resource": ip.rsplit(".", 1)[0] + ".0/24" if "." in ip else ip + "/48", "announced": True, "asns": [{"asn": 15133, "holder": "EDGECAST"}]}})
        if request.url.path.endswith("rir-stats-country/data.json"):
            return httpx.Response(200, json={"data": {"located_resources": [{"resource": ip, "location": "US"}]}})
        score = 80 if ip == "93.184.216.34" else 0
        return httpx.Response(200, json={"data": {"abuseConfidenceScore": score, "totalReports": 12 if score else 0, "usageType": "Data Center/Web Hosting/Transit", "isTor": False}})


@pytest.fixture
def world(monkeypatch):
    sources = Sources()
    monkeypatch.setattr(settings, "network_intel_enabled", True)
    monkeypatch.setattr(settings, "abuseipdb_api_key", "test-key")
    monkeypatch.setattr(intel, "resolver", lambda host: DNS.get(host, []))
    monkeypatch.setattr(intel, "client_factory", lambda: httpx.AsyncClient(transport=httpx.MockTransport(sources.handler)))

    async def nodes():
        return NODES, None

    monkeypatch.setattr(intel, "list_nodes", nodes)
    intel._manual.clear()
    return sources


def test_public_ip_excludes_private_reserved_and_documentation_ranges():
    for value in ("10.0.0.5", "192.168.1.1", "127.0.0.1", "100.64.0.1", "169.254.1.1", "::1", "fe80::1", "2001:db8::1", "fc00::1", "not-an-ip"):
        assert not intel.public_ip(value), value
    for value in ("93.184.216.34", "2a00:1450:4001:80b::200e"):
        assert intel.public_ip(value), value


@pytest.mark.asyncio
async def test_resolve_handles_literals_ports_ipv6_and_dns_errors(world):
    assert await intel.resolve("93.184.216.34:443") == (["93.184.216.34"], None)
    assert await intel.resolve("[2a00:1450:4001:80b::200e]:443") == (["2a00:1450:4001:80b::200e"], None)
    assert (await intel.resolve("nl1.vpn.example"))[0] == DNS["nl1.vpn.example"]
    assert await intel.resolve("missing.vpn.example") == ([], "DNS не вернул адресов")
    assert (await intel.resolve(""))[1]


@pytest.mark.asyncio
async def test_refresh_fetches_only_public_addresses_and_builds_warnings(database, world):
    stats = await intel.refresh_due(database, NODES)
    assert stats == {"fetched": 6}
    queried = {c.url.params.get("resource") or c.url.params.get("ipAddress") for c in world.calls}
    assert queried == {"93.184.216.34", "93.184.216.35", "2a00:1450:4001:80b::200e"}
    assert all(c.url.params.get("sourceapp") == "corgi-vpn-shop" for c in world.calls if c.url.host == "stat.ripe.net")
    assert all(c.headers.get("key") == "test-key" for c in world.calls if c.url.host == "api.abuseipdb.com")
    report = await intel.build_report(database, NODES)
    by_name = {n["name"]: n for n in report["nodes"]}
    nl = by_name["Amsterdam-1"]
    assert [a["ip"] for a in nl["addresses"] if a["private"]] == ["2001:db8::1"]
    v6 = next(a for a in nl["addresses"] if a["version"] == 6 and not a["private"])
    assert v6["registry"]["freshness"] == "fresh" and v6["registry"]["data"]["asn"] == 15133
    texts = [w["text"] for w in by_name["Amsterdam-2"]["warnings"]]
    assert any("репутация 80/100" in t for t in texts)
    assert any("страна в панели DE, по RIR US" in t for t in texts)
    assert any("AS15133" in t for t in texts)
    assert report["asn_concentration"] == [{"asn": 15133, "nodes": ["Amsterdam-1", "Amsterdam-2"]}]
    assert any("внутренние адреса" in w["text"] for w in by_name["Lab"]["warnings"])
    assert any("DNS" in w["text"] for w in by_name["Broken"]["warnings"])
    assert await intel.refresh_due(database, NODES) == {}, "fresh cache is not refetched"


@pytest.mark.asyncio
async def test_expired_cache_is_stale_until_refetched_and_errors_keep_last_good_data(database, world):
    await intel.refresh_due(database, NODES)
    later = datetime.utcnow() + timedelta(days=8)
    world.status["stat.ripe.net"] = 503
    stats = await intel.refresh_due(database, NODES, now=later)
    assert stats.get("error") == 3
    row = await database.scalar(select(NetworkIntel).where(NetworkIntel.ip == "93.184.216.34", NetworkIntel.source == "ripestat"))
    assert row.data["asn"] == 15133 and row.error == "HTTP 503" and row.next_attempt_at > later
    report = await intel.build_report(database, NODES, now=later)
    entry = next(a for n in report["nodes"] if n["name"] == "Amsterdam-2" for a in n["addresses"])["registry"]
    assert entry["freshness"] == "stale" and entry["data"]["asn"] == 15133 and entry["error"] == "HTTP 503"
    # Backoff: the failing entry is not retried immediately.
    assert (await intel.refresh_due(database, NODES, now=later + timedelta(minutes=1))).get("error") is None


@pytest.mark.asyncio
async def test_http_429_pauses_the_source_and_budget_caps_requests(database, world, monkeypatch):
    world.status["api.abuseipdb.com"] = 429
    stats = await intel.refresh_due(database, NODES)
    assert stats.get("rate_limited") == 1
    state = await database.get(NetworkIntelSourceState, "abuseipdb")
    assert state.blocked_until > datetime.utcnow() + timedelta(seconds=100) and "429" in state.last_error
    calls = len([c for c in world.calls if c.url.host == "api.abuseipdb.com"])
    await intel.refresh_due(database, NODES)
    assert len([c for c in world.calls if c.url.host == "api.abuseipdb.com"]) == calls, "paused source is not called"
    monkeypatch.setitem(intel.SOURCES["ripestat"], "limit", 1)
    await database.execute(NetworkIntel.__table__.delete())
    await database.commit()
    assert (await intel.refresh_due(database, NODES, now=datetime.utcnow() + timedelta(hours=1))).get("budget") == 1


@pytest.mark.asyncio
async def test_without_key_only_ripestat_and_disabled_means_no_calls(database, world, monkeypatch):
    monkeypatch.setattr(settings, "abuseipdb_api_key", "")
    await intel.refresh_due(database, NODES)
    assert {c.url.host for c in world.calls} == {"stat.ripe.net"}
    report = await intel.build_report(database, NODES)
    assert all(a["reputation"] is None for n in report["nodes"] for a in n["addresses"])
    monkeypatch.setattr(settings, "network_intel_enabled", False)
    world.calls.clear()
    await database.execute(NetworkIntel.__table__.delete())
    await database.commit()
    assert await intel.refresh_due(database, NODES) == {}
    assert world.calls == [] and (await intel.build_report(database, NODES))["enabled"] is False


@pytest.mark.asyncio
async def test_manual_refresh_only_for_node_addresses_and_is_throttled(database, world):
    with pytest.raises(HTTPException) as error:
        await intel.admin_network_refresh(intel.RefreshIn(ip="8.8.8.8"), database, ADMIN)
    assert error.value.status_code == 404
    with pytest.raises(HTTPException) as error:
        await intel.admin_network_refresh(intel.RefreshIn(ip="10.0.0.5"), database, ADMIN)
    assert error.value.status_code == 422
    result = await intel.admin_network_refresh(intel.RefreshIn(ip="93.184.216.34"), database, ADMIN)
    assert result["results"] == {"ripestat": "fetched", "abuseipdb": "fetched"}
    with pytest.raises(HTTPException) as error:
        await intel.admin_network_refresh(intel.RefreshIn(ip="93.184.216.34"), database, ADMIN)
    assert error.value.status_code == 429


@pytest.mark.asyncio
async def test_admin_report_includes_aggregated_customer_networks_without_ips(database, world):
    now = datetime.utcnow()
    for user, asn in ((1, "AS12389"), (2, "AS12389"), (1, "AS8359")):
        database.add(ConnectionObservation(user_id=user, ip="203.0.113.7", prefix="203.0.113.0/24", asn=asn, asn_org="ISP " + asn, country="RU", seen_at=now))
    database.add(ConnectionObservation(user_id=2, ip="198.51.100.1", prefix="198.51.100.0/24", asn="AS1", country="RU", seen_at=now - timedelta(days=30)))
    await database.commit()
    report = await intel.admin_network_intel(database, ADMIN)
    assert report["customers"]["asns"][0] == {"asn": "AS12389", "org": "ISP AS12389", "users": 2}
    assert {"asn": "AS1", "org": None, "users": 1} not in report["customers"]["asns"]
    assert "203.0.113.7" not in str(report["customers"])
    assert report["remnawave_error"] is None and len(report["nodes"]) == 4


@pytest.mark.asyncio
async def test_remnawave_failure_is_reported(database, monkeypatch):
    from app import remnawave

    class Down:
        async def list_nodes(self, **kwargs):
            raise RuntimeError("down")

    monkeypatch.setattr(remnawave, "RemnawaveClient", Down)
    nodes, error = await intel.list_nodes()
    assert nodes == [] and error == "Remnawave недоступен"
