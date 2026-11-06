"""Stage 19, C1: addresses the server itself contacts (staging gateways, monitoring) stay public, checked by running the code.

Replaces source-text checks of test_v2_1_0_ssrf_hardening.py (the staging settings and the staging payment) and
test_v44_5_20_dns_pinning.py (the pinned transport and the DNS answers, which were executed from an AST copy of the
source instead of the real module)."""
import asyncio
import socket
from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace

import httpcore
import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app import main as shop
from app import payments
from app.models import MonitoringCheck
from test_subscription_commerce import database  # noqa: F401

ADMIN = SimpleNamespace(email="owner@corgi.test", role="admin")
DNS = {"gateway.example": ["93.184.216.34"], "inside.example": ["10.0.0.7"], "mixed.example": ["93.184.216.34", "10.0.0.7"],
       "loop.example": ["127.0.0.1"]}


@pytest.fixture
def dns(monkeypatch):
    """A resolver with known answers; anything else does not resolve."""
    asked = []

    def getaddrinfo(host, port, type=None, *args, **kwargs):
        asked.append(host)
        if host not in DNS:
            raise socket.gaierror("no such host")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)) for ip in DNS[host]]
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    return asked


@pytest.mark.parametrize("url", ["http://gateway.example", "https://user:pw@gateway.example", "https://localhost/x",
                                 "https://api.localhost", "https://10.1.2.3", "https://127.0.0.1", "https://[::1]",
                                 "https://169.254.169.254/latest", "https://inside.example", "https://mixed.example",
                                 "https://loop.example", "https://nowhere.example", "https://gateway.example:99999", "gateway.example"])
def test_private_local_and_unsafe_urls_are_refused(dns, url):
    with pytest.raises(HTTPException) as err:
        shop.validate_public_url(url, allow_empty=False)
    assert err.value.status_code == 400


def test_public_https_urls_pass(dns):
    assert shop.validate_public_url("https://gateway.example/v3", allow_empty=False) == "https://gateway.example/v3"
    assert shop.validate_public_url("https://93.184.216.34", allow_empty=False)
    assert shop.validate_public_url("", allow_empty=True) == ""
    with pytest.raises(HTTPException):
        shop.validate_public_url("", allow_empty=False)


@pytest.mark.asyncio
async def test_the_connection_resolves_again_and_dials_the_checked_address(dns, monkeypatch):
    """DNS rebinding: a name that was public when checked and private when dialled is refused at connect time."""
    dialled = []

    async def connect(self, host, port, timeout=None, local_address=None, socket_options=None):
        dialled.append((host, port))
        return object()
    monkeypatch.setattr(httpcore.AnyIOBackend, "connect_tcp", connect)
    backend = shop._PinnedPublicDNSBackend()
    await backend.connect_tcp("gateway.example", 443, timeout=1)
    assert dialled == [("93.184.216.34", 443)], "the literal address is dialled, no second lookup"
    DNS["rebind.example"] = ["10.9.9.9"]
    try:
        for host in ("rebind.example", "mixed.example", "10.0.0.1", "nowhere.example"):
            with pytest.raises(OSError):
                await backend.connect_tcp(host, 443, timeout=1)
    finally:
        DNS.pop("rebind.example")
    assert dialled == [("93.184.216.34", 443)]


@pytest.mark.asyncio
async def test_the_pinned_client_ignores_proxy_settings_and_redirects(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:3128")
    async with shop._pinned_public_http_client(5) as client:
        assert client.follow_redirects is False
        transport = client._transport
        assert isinstance(transport._pool._network_backend, shop._PinnedPublicDNSBackend)
        assert client._mounts == {}, "no proxy mounts from the environment"


@pytest.fixture
def staging_client(monkeypatch):
    sent = []

    class Client:
        async def post(self, url, headers=None, json=None, auth=None):
            sent.append(url)
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"id": "p-1", "confirmation": {"confirmation_url": "https://pay.example/1"}})

    @asynccontextmanager
    async def client(timeout):
        yield Client()
    monkeypatch.setattr(shop, "_pinned_public_http_client", client)
    return sent


@pytest.mark.asyncio
@pytest.mark.parametrize("provider, creds, path", [
    ("yookassa", {"shop_id": "1", "secret_key": "s"}, "/v3/payments"),
    ("platega", {"merchant_id": "m", "secret": "s"}, "/v2/transaction/process"),
    ("rollypay", {"api_key": "k"}, "/api/v1/payments"),
])
async def test_a_staging_payment_goes_only_to_a_public_gateway(dns, staging_client, provider, creds, path):
    for bad in ("https://inside.example", "http://gateway.example", "https://127.0.0.1", None):
        with pytest.raises(HTTPException):
            await payments.staging_create_payment(provider, {**creds, "api_url": bad}, Decimal("10"), "o-1", "test", "https://shop.example/r")
    assert staging_client == [], "nothing is sent to a refused address"
    await payments.staging_create_payment(provider, {**creds, "api_url": "https://gateway.example/"}, Decimal("10"), "o-1", "test",
                                          "https://shop.example/r")
    assert staging_client == ["https://gateway.example" + path]


def staging_config(**changes):
    values = dict(public_base_url="https://gateway.example", remnawave_url="https://gateway.example", remnawave_token="rw-token",
                  yookassa_api_url="https://gateway.example", platega_api_url="https://gateway.example",
                  rollypay_api_url="https://gateway.example", plan_id=1, providers=["yookassa"], yookassa_enabled=True, platega_enabled=False, rollypay_enabled=False,
                  yookassa_shop_id="sandbox", yookassa_secret_key="sandbox-key", staging_confirmed=True)
    values.update(changes)
    return shop.StagingE2EConfigIn(**values)


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["public_base_url", "remnawave_url", "yookassa_api_url", "platega_api_url", "rollypay_api_url"])
async def test_staging_settings_with_an_internal_address_are_not_saved(database, dns, field):
    with pytest.raises(HTTPException) as err:
        await shop.update_staging_e2e_config(staging_config(**{field: "https://inside.example"}), database, ADMIN)
    assert err.value.status_code == 400
    assert await shop._staging_config(database) is None, "nothing was stored"


@pytest.mark.asyncio
async def test_staging_settings_with_public_addresses_are_saved(database, dns):
    await shop.update_staging_e2e_config(staging_config(), database, ADMIN)
    saved = await shop._staging_config(database)
    assert saved["remnawave_url"] == "https://gateway.example" and saved["providers"] == ["yookassa"]


@pytest.mark.asyncio
async def test_monitoring_never_requests_an_internal_address(database, dns, monkeypatch):
    database.add_all([MonitoringCheck(name="inside", url="https://inside.example/health"),
                      MonitoringCheck(name="public", url="https://gateway.example/health")])
    await database.commit()
    monkeypatch.setattr(shop, "engine", database.bind)
    requested = []

    class Client:
        async def request(self, method, url):
            requested.append(url)
            return SimpleNamespace(status_code=200)

    @asynccontextmanager
    async def client(timeout):
        yield Client()
    monkeypatch.setattr(shop, "_pinned_public_http_client", client)

    async def sleep(seconds):
        raise asyncio.CancelledError  # one pass is enough
    monkeypatch.setattr(shop, "asyncio", SimpleNamespace(**{**vars(asyncio), "sleep": sleep}))
    with pytest.raises(asyncio.CancelledError):
        await shop.monitor_checks_scheduler()
    assert requested == ["https://gateway.example/health"]
    rows = {x.name: x for x in (await database.execute(select(MonitoringCheck))).scalars()}
    for row in rows.values():
        await database.refresh(row)
    assert rows["inside"].last_status == "down" and "private" in rows["inside"].last_error
    assert rows["public"].last_status == "ok"
