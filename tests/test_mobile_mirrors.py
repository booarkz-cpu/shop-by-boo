"""Reserve API addresses for the apps: signed, verifiable, republished to a Gist on their own."""
import base64
import json

import httpx
import pytest
from fastapi import Response
from pydantic import ValidationError

from app import mobile_mirrors as mm
from app.config import settings
from test_subscription_commerce import database  # noqa: F401


class Admin:
    email = "owner@corgi.test"


@pytest.mark.asyncio
async def test_the_document_is_signed_with_one_stable_key_and_a_forgery_fails(database, monkeypatch):
    monkeypatch.setattr(settings, "api_domain", "api.corgi.test")
    await mm.put_mirrors(mm.MirrorsIn(mirrors=["https://api2.corgi.test/", "https://api2.corgi.test"], bootstrap=["https://gist.githubusercontent.com/x/raw/m.json"]), database, Admin())
    doc = await mm.public_mirrors(Response(), database)
    again = await mm.public_mirrors(Response(), database)
    assert doc["key"] == again["key"], "the key is generated once"
    payload = mm.verify(doc, doc["key"])
    assert payload["mirrors"] == ["https://api.corgi.test", "https://api2.corgi.test"] and payload["shop"] == "https://api.corgi.test"
    forged = {**doc, "payload": doc["payload"].replace("api2.corgi.test", "evil.example")}
    with pytest.raises(Exception):
        mm.verify(forged, doc["key"])
    with pytest.raises(ValueError):
        mm.verify({**doc, "key": base64.b64encode(b"other").decode()}, doc["key"])


def test_only_plain_https_addresses_are_accepted():
    for bad in ("http://api.corgi.test", "https://user:pw@api.corgi.test", "https://api.corgi.test/?x=1", "javascript:alert(1)"):
        with pytest.raises(ValidationError):
            mm.MirrorsIn(mirrors=[bad])


@pytest.mark.asyncio
async def test_the_gist_is_republished_and_its_raw_link_becomes_a_bootstrap_source(database, monkeypatch):
    monkeypatch.setattr(settings, "api_domain", "api.corgi.test")
    seen = {}

    def handle(request: httpx.Request):
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"files": {mm.GIST_FILE: {"raw_url": f"https://gist.githubusercontent.com/corgi/abc123/raw/rev1/{mm.GIST_FILE}"}}})
    real_publish = mm.publish

    async def offline(db, client=None):
        return await mm.load(db)
    monkeypatch.setattr(mm, "publish", offline)
    await mm.put_mirrors(mm.MirrorsIn(gist_id="abc123", gist_token="ghp_secret"), database, Admin())
    cfg = await real_publish(database, client=httpx.AsyncClient(transport=httpx.MockTransport(handle)))
    assert seen["auth"] == "Bearer ghp_secret"
    published = json.loads(seen["body"]["files"][mm.GIST_FILE]["content"])
    assert mm.verify(published, published["key"])["shop"] == "https://api.corgi.test"
    assert cfg["bootstrap"] == [f"https://gist.githubusercontent.com/corgi/abc123/raw/{mm.GIST_FILE}"] and cfg["publish_error"] is None
    shown = await mm.get_mirrors(database, Admin())
    assert shown["gist_token_set"] and "ghp_secret" not in json.dumps(shown), "the token never leaves the server"


@pytest.mark.asyncio
async def test_direct_domains_are_normalised_and_signed_into_the_list(database, monkeypatch):
    monkeypatch.setattr(settings, "api_domain", "localhost")
    await mm.put_mirrors(mm.MirrorsIn(direct_domains=["https://Online.Sberbank.com/", "online.sberbank.com", "esia.gosuslugi.ru"]), database, Admin())
    doc = await mm.public_mirrors(Response(), database)
    payload = mm.verify(doc, doc["key"])
    assert payload["direct"] == ["online.sberbank.com", "esia.gosuslugi.ru"] and payload["mirrors"] == [], "no public address on a development stand"
    with pytest.raises(ValidationError):
        mm.MirrorsIn(direct_domains=["regexp:.*"])


@pytest.mark.asyncio
async def test_reserve_domains_served_by_caddy_are_listed_and_accepted(database, monkeypatch):
    from types import SimpleNamespace

    from fastapi import HTTPException

    from app import mobile_auth
    monkeypatch.setattr(settings, "api_domain", "api.corgi.test")
    monkeypatch.setattr(settings, "api_mirror_domains", "API2.corgi.test, api3.corgi.test")
    assert settings.api_domains() == ["api.corgi.test", "api2.corgi.test", "api3.corgi.test"]
    doc = await mm.public_mirrors(Response(), database)
    assert mm.verify(doc, doc["key"])["mirrors"] == ["https://api.corgi.test", "https://api2.corgi.test", "https://api3.corgi.test"]
    monkeypatch.setattr(settings, "app_env", "production")

    def native(host):
        return SimpleNamespace(headers={}, url=SimpleNamespace(hostname=host))
    mobile_auth.require_native_transport(native("api2.corgi.test"))
    with pytest.raises(HTTPException):
        mobile_auth.require_native_transport(native("evil.example"))
