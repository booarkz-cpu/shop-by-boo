"""v28.67.0 (stage 11): Domain Manager, certificates, Caddy routes, the subscription portal and its protection.

* domains are typed; the shop's own domains and non-portal shop domains are refused; Caddy's on-demand question is
  answered only for an enabled portal domain and never through the proxy;
* the DNS check reports missing / other address / CAA; the TLS check reports valid / expiring / untrusted, and never
  connects to a private address;
* a domain becomes the customers' subscription address only with a valid certificate; Cloudflare A record upsert;
* a browser opening the subscription link gets the portal (status, link, QR, apps, devices) without personal data;
  VPN clients still get the subscription; unknown links pause the address; outdated apps can get a stub;
* a customer and an administrator can replace a leaked link (panel «revoke»), the customer once per 10 minutes;
* the wizard can close the panel's pages behind a secret link (Caddy cookie matcher)."""
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from starlette.requests import Request

from app import cabinet_security, rw_domains, rw_plan, sub_portal, sub_proxy
from app.config import settings
from app.models import AuditLog, RemnawaveDomain, Subscription
from test_subscription_commerce import database, request as plain_request  # noqa: F401

ADMIN = SimpleNamespace(email="owner@corgi.test", role="admin")
SHORT = "AbCdEfGh12345678"


class FakeResolver:
    zone: dict = {}

    def __init__(self, client):
        pass

    async def query(self, name, rtype):
        return list(self.zone.get((name, rtype), []))

    async def addresses(self, name):
        return [*(await self.query(name, "A")), *(await self.query(name, "AAAA"))]


class _Client:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        pass


@pytest.fixture
def dns(monkeypatch):
    FakeResolver.zone = {("api.shop.test", "A"): ["93.184.216.34"]}
    monkeypatch.setattr(rw_domains, "_resolver", lambda: (FakeResolver, _Client))
    monkeypatch.setattr(settings, "api_domain", "api.shop.test")
    probes = []

    async def connect(ip, port, domain):
        probes.append(ip)
        return {"issuer": "Let's Encrypt", "not_after": datetime.utcnow() + timedelta(days=60), "names": [domain]}, True, None

    async def http_get(domain, ip):
        return 200
    monkeypatch.setattr(rw_domains, "connect", connect)
    monkeypatch.setattr(rw_domains, "http_get", http_get)
    return SimpleNamespace(zone=FakeResolver.zone, probes=probes)


def test_domain_input_is_typed():
    with pytest.raises(ValidationError):
        rw_domains.DomainIn(domain="sub.example.com\nevil", purpose="subscription")
    with pytest.raises(ValidationError):
        rw_domains.DomainIn(domain="sub.example.com", purpose="subscription", expected_ip="10.0.0.5")
    with pytest.raises(ValidationError):
        rw_domains.DomainIn(domain="sub.example.com", purpose="mail")
    assert rw_domains.DomainIn(domain="SUB.Example.com.", purpose="subscription").domain == "sub.example.com"


@pytest.mark.asyncio
async def test_add_check_primary_and_caddy_ask(database, dns, monkeypatch):
    db = database
    with pytest.raises(HTTPException) as err:  # the shop's own API domain is served already
        await rw_domains.add_domain(rw_domains.DomainIn(domain="api.shop.test", purpose="subscription"), db, ADMIN)
    assert err.value.status_code == 409
    with pytest.raises(HTTPException):  # the shop's Caddy serves only portal domains
        await rw_domains.add_domain(rw_domains.DomainIn(domain="panel.example.com", purpose="panel"), db, ADMIN)
    added = await rw_domains.add_domain(rw_domains.DomainIn(domain="sub.example.com", purpose="subscription"), db, ADMIN)
    assert added["dns_status"] == "unknown"

    def ask(domain, forwarded=False):
        headers = [(b"x-forwarded-for", b"203.0.113.5")] if forwarded else []
        return rw_domains.caddy_ask(domain, Request({"type": "http", "headers": headers}), db)
    assert (await ask("sub.example.com")).body == b"ok"
    for bad in (("other.example.com", False), ("sub.example.com", True)):
        with pytest.raises(HTTPException):
            await ask(*bad)

    with pytest.raises(HTTPException):  # no valid certificate checked yet
        await rw_domains.make_primary(added["id"], db, ADMIN)
    dns.zone[("sub.example.com", "A")] = ["93.184.216.35"]
    out = await rw_domains.check_domain(added["id"], db, ADMIN)
    assert out["domain"]["dns_status"] == "mismatch" and "93.184.216.34" in out["dns"]
    dns.zone[("sub.example.com", "A")] = ["93.184.216.34"]
    dns.zone[("sub.example.com", "CAA")] = ['0 issue "digicert.com"']
    assert (await rw_domains.check_domain(added["id"], db, ADMIN))["domain"]["dns_status"] == "caa"
    dns.zone[("sub.example.com", "CAA")] = ['0 issue "letsencrypt.org"']
    out = await rw_domains.check_domain(added["id"], db, ADMIN)
    assert out["domain"]["dns_status"] == "ok" and out["domain"]["cert_status"] == "valid" and out["http"] == 200

    saved = {}

    async def save(db_, key, value):
        saved[key] = value
    monkeypatch.setattr("app.node_health._save", save)
    primary = await rw_domains.make_primary(added["id"], db, ADMIN)
    assert primary["subscription_base"] == "https://sub.example.com" and saved[sub_proxy.CONFIG_KEY]["public_base"] == "https://sub.example.com"
    await rw_domains.patch_domain(added["id"], rw_domains.DomainPatch(enabled=False), db, ADMIN)
    with pytest.raises(HTTPException):  # a disabled domain gets no certificate
        await ask("sub.example.com")
    certs = await rw_domains.certificates(db, ADMIN)
    assert certs["certificates"][0]["domain"] == "sub.example.com" and "DNS-01" not in certs["challenges"]
    routes = await rw_domains.proxy_routes(db, ADMIN)
    assert routes["portal"][0]["domain"] == "sub.example.com" and any(r["target"] == "admin" for r in routes["shop"])
    actions = set((await db.execute(select(AuditLog.action).where(AuditLog.action.like("rw.domain.%")))).scalars())
    assert {"rw.domain.added", "rw.domain.primary", "rw.domain.updated"} <= actions


@pytest.mark.asyncio
async def test_tls_statuses_and_private_addresses(database, dns, monkeypatch):
    db = database
    row = RemnawaveDomain(domain="sub.example.com", purpose="subscription", served_by="shop", created_by="t")
    db.add(row)
    await db.commit()
    dns.zone[("sub.example.com", "A")] = ["10.1.2.3"]  # private: not connected to
    out = await rw_domains.run_check(db, row)
    assert out["domain"]["cert_status"] == "missing" and not dns.probes
    dns.zone[("sub.example.com", "A")] = ["93.184.216.34"]

    async def expiring(ip, port, domain):
        return {"issuer": "R11", "not_after": datetime.utcnow() + timedelta(days=5), "names": [domain]}, True, None
    monkeypatch.setattr(rw_domains, "connect", expiring)
    assert (await rw_domains.run_check(db, row))["domain"]["cert_status"] == "expiring"

    async def untrusted(ip, port, domain):
        return {"issuer": "Caddy Local Authority", "not_after": datetime.utcnow() + timedelta(days=5), "names": [domain]}, False, "self-signed"
    monkeypatch.setattr(rw_domains, "connect", untrusted)
    out = await rw_domains.run_check(db, row)
    assert out["domain"]["cert_status"] == "invalid" and "self-signed" in out["tls"]


@pytest.mark.asyncio
async def test_cloudflare_record(database, dns, monkeypatch):
    db = database
    row = RemnawaveDomain(domain="sub.example.com", purpose="subscription", served_by="shop", created_by="t")
    db.add(row)
    await db.commit()
    monkeypatch.setattr(settings, "cloudflare_api_token", "", raising=False)
    with pytest.raises(HTTPException) as err:
        await rw_domains.upsert_dns_record(row.id, db, ADMIN)
    assert err.value.status_code == 409
    monkeypatch.setattr(settings, "cloudflare_api_token", "cf-token", raising=False)
    calls = []

    async def cf(method, path, **kw):
        calls.append((method, path, kw.get("json"), kw.get("params")))
        if path == "/zones":
            return {"result": [{"id": "z1", "name": "example.com"}] if kw["params"]["name"] == "example.com" else []}
        if path.endswith("/dns_records") and method == "GET":
            return {"result": []}
        return {"result": {}}
    monkeypatch.setattr(rw_domains, "_cf", cf)
    out = await rw_domains.upsert_dns_record(row.id, db, ADMIN)
    assert out == {"action": "created", "type": "A", "content": "93.184.216.34", "zone": "example.com"}
    assert calls[-1][0] == "POST" and calls[-1][2] == {"type": "A", "name": "sub.example.com", "content": "93.184.216.34", "ttl": 300, "proxied": False}


def browser(path="/sub/x", ua=b"Mozilla/5.0 (iPhone) Safari/605", accept=b"text/html,application/xhtml+xml"):
    return Request({"type": "http", "method": "GET", "path": path, "query_string": b"", "client": ("203.0.113.9", 1),
                    "headers": [(b"user-agent", ua), (b"accept", accept)]})


@pytest.fixture
def portal(database, monkeypatch):
    cfg = {**sub_proxy.DEFAULT, "enabled": True, "public_base": "https://sub.example.com", "origin": "https://panel.example.com/api/sub",
           "miss_limit": 5, "portal": {"apps": sub_portal.DEFAULT_APPS[:2]}}
    sub_proxy._state.update(cfg=cfg, at=10 ** 12)
    sub_proxy._index.clear()
    sub_proxy._local_blocks.clear()
    from app import runtime_security
    runtime_security._LOCAL.clear()
    monkeypatch.setattr(sub_proxy, "_client_ip", lambda r: r.client.host)
    import app.main as main
    monkeypatch.setattr(main, "redis_client", None)

    async def not_outdated(*a):
        return False
    monkeypatch.setattr("app.client_versions.is_outdated", not_outdated)

    async def facts(sub):
        return {"used": 3 * 1024 ** 3, "limit": 0, "device_limit": 2, "devices": [{"platform": "iOS", "model": "iPhone 16", "seen": ""}]}
    monkeypatch.setattr(sub_portal, "_panel_facts", facts)
    return cfg


@pytest.mark.asyncio
async def test_browser_gets_the_portal(database, portal):
    db = database
    sub = await db.get(Subscription, 1)
    sub.subscription_url = f"https://panel.example.com/api/sub/{SHORT}"
    await db.commit()
    page = await sub_proxy.serve(browser(), SHORT, db)
    text = page.body.decode()
    assert page.status_code == 200 and page.headers["cache-control"] == "no-store" and "noindex" in page.headers["x-robots-tag"]
    assert "Активна" in text and "Basic" in text and f"https://sub.example.com/{SHORT}" in text and "<svg" in text
    assert f"happ://add/https%3A%2F%2Fsub.example.com%2F{SHORT}" in text and "iPhone 16" in text and "из 2" in text
    assert "3.0 ГБ из без лимита" in text and "<script src='/sub/-/portal.js'" in text and "<script>" not in text
    js = await sub_proxy.serve(browser(), "-/portal.js", db)
    assert js.media_type.startswith("text/javascript") and b"clipboard" in js.body
    from app.models import SubRequest
    assert (await db.execute(select(SubRequest.decision))).scalars().all()[-1] == "portal"
    portal["portal"] = {"template": "minimal"}
    minimal = (await sub_proxy.serve(browser(), SHORT, db)).body.decode()
    assert "data-portal-apps" not in minimal and "data-portal-link" in minimal


@pytest.mark.asyncio
async def test_guessing_links_pauses_the_address(database, portal):
    db = database
    for i in range(5):
        answer = await sub_proxy.serve(browser(), f"Unknown{i:09d}", db)
        assert answer.status_code == 200 and b"<form" in answer.body  # the neutral page
    answer = await sub_proxy.serve(browser(), "Unknown999999999", db)
    paused = await sub_proxy.serve(browser(), SHORT, db)
    assert paused.status_code == 429 and int(paused.headers["retry-after"]) == 15 * 60
    other = Request({**browser().scope, "client": ("198.51.100.77", 1)})
    assert (await sub_proxy.serve(other, "Unknown000000000", db)).status_code == 200


@pytest.mark.asyncio
async def test_outdated_client_gets_a_stub(database, portal, monkeypatch):
    db = database
    portal["block_outdated"] = True

    async def outdated(*a):
        return True
    monkeypatch.setattr("app.client_versions.is_outdated", outdated)
    vpn = browser(ua=b"v2rayNG/1.8.0", accept=b"*/*")
    answer = await sub_proxy.serve(vpn, SHORT, db)
    import base64
    from urllib.parse import unquote
    assert answer.status_code == 200 and "Обновите" in unquote(base64.b64decode(answer.body).decode())


@pytest.mark.asyncio
async def test_replace_a_leaked_link(database, monkeypatch):
    db = database
    sub = await db.get(Subscription, 1)
    sub.remnawave_uuid, sub.subscription_url = "42", f"https://panel.example.com/api/sub/{SHORT}"
    await db.commit()
    calls = []

    class Panel:
        async def revoke_subscription(self, user_id):
            calls.append(user_id)
            return {"shortUuid": "NewShort12345678", "subscriptionUrl": "https://panel.example.com/api/sub/NewShort12345678"}
    import app.main as main
    import app.remnawave as remnawave
    monkeypatch.setattr(main, "RemnawaveClient", Panel)
    monkeypatch.setattr(remnawave, "RemnawaveClient", Panel)
    monkeypatch.setattr(main, "redis_client", None)
    from app import runtime_security
    runtime_security._LOCAL.clear()
    sub_proxy._index[SHORT] = (10 ** 12, {"subscription_id": 1})
    out = await cabinet_security.reset_my_subscription_link(plain_request(), db)
    assert out["ok"] and calls == [42] and SHORT not in sub_proxy._index
    assert (await db.get(Subscription, 1)).subscription_url.endswith("NewShort12345678")
    with pytest.raises(HTTPException) as err:  # once per 10 minutes
        await cabinet_security.reset_my_subscription_link(plain_request(), db)
    assert err.value.status_code == 429
    admin = await sub_proxy.reset_link(1, db, ADMIN)
    assert admin["ok"] and calls == [42, 42]
    actions = set((await db.execute(select(AuditLog.action))).scalars())
    assert {"cabinet.subscription.link_reset", "sub_proxy.link.reset"} <= actions


def test_portal_settings_are_validated():
    with pytest.raises(ValidationError):
        sub_proxy.PortalAppIn(name="Evil", deeplink="javascript:alert(1)")
    with pytest.raises(ValidationError):
        sub_proxy.PortalAppIn(name="Evil", deeplink="happ://add/{url}", download="http://insecure.example")
    with pytest.raises(ValidationError):
        sub_proxy.PortalIn(template="custom")
    assert sub_proxy.ProxyIn(portal={"title": "Подписка"}).portal.title == "Подписка"


def test_caddy_serves_portal_domains_on_demand_only_after_asking():
    from pathlib import Path
    text = (Path(__file__).resolve().parents[1] / "deploy/Caddyfile").read_text()
    assert "on_demand_tls" in text and "ask {$CADDY_ASK_URL" in text
    block = text.split("https:// {", 1)[1]
    assert "on_demand" in block and "rewrite * /sub{uri}" in block  # /caddy/ask becomes /sub/caddy/ask here
    assert text.count("respond /caddy/* 404") == 1  # the API domain
    compose = (Path(__file__).resolve().parents[1] / "docker-compose.yml").read_text()
    assert "CADDY_ASK_URL: http://${BACKEND_INGRESS_IP" in compose


def test_panel_access_behind_a_secret_link():
    caddy = rw_plan.caddyfile({"panel.example.com": 3000, "sub.example.com": 3010}, "acme", "a@example.com",
                              {"panel.example.com": ("rwabc123", "0123456789abcdef")})
    panel = caddy.split("panel.example.com {", 1)[1].split("}\n\n", 1)[0]
    assert "@key query rwabc123=0123456789abcdef" in panel and "abort @locked" in panel
    assert "not path /api/sub/*" in panel and 'header Authorization "Bearer *"' in panel
    assert "abort" not in caddy.split("sub.example.com {", 1)[1]
    with pytest.raises(ValueError):
        rw_plan.caddyfile({"panel.example.com": 3000}, "acme", None, {"panel.example.com": ("bad name", "x")})
    with pytest.raises(ValidationError):  # only for a panel the wizard installs
        rw_plan.PlanIn(mode="node", node_server_ids=[2], panel_access="cookie")
    plan = rw_plan.build_plan(rw_plan.PlanIn(mode="panel", panel_server_id=1, panel_domain="panel.example.com", tls="internal",
                                             panel_access="cookie"), {1: {"name": "s1", "host": "93.184.216.34"}}, None)
    assert any("секретной ссылке" in c for c in plan["servers"]["1"]["changes"])
    assert json.dumps(plan)  # the plan stays serialisable for its SHA-256


@pytest.mark.asyncio
async def test_every_text_language_and_colour_is_the_owners(database, portal):
    """v28.68.0: every text of the portal per language, the template's colours and the neutral page are set in the
    admin panel; the browser's language picks ru / en / uk."""
    db = database
    sub = await db.get(Subscription, 1)
    sub.subscription_url = f"https://panel.example.com/api/sub/{SHORT}"
    await db.commit()
    portal["portal"] = {"apps": sub_portal.DEFAULT_APPS[:1], "colors": {"accent": "#FF8800"},
                        "texts": {"ru": {"copy": "Скопировать ссылку", "traffic": "Израсходовано {used} (лимит {limit})", "footer": "Корги Люси ♥"}}}
    ru = (await sub_proxy.serve(browser(), SHORT, db)).body.decode()
    assert "Скопировать ссылку" in ru and "Израсходовано 3.0 ГБ (лимит без лимита)" in ru and "Корги Люси ♥" in ru and "--accent:#FF8800" in ru
    assert "data-copied='Скопировано'" in ru and "<html lang=ru>" in ru
    en_request = Request({**browser().scope, "headers": [*browser().scope["headers"], (b"accept-language", b"en-US,en;q=0.9")]})
    en = await sub_proxy.serve(en_request, SHORT, db)
    assert "Active" in en.body.decode() and "Copy" in en.body.decode() and en.headers["content-language"] == "en"
    uk_request = Request({**browser().scope, "headers": [*browser().scope["headers"], (b"accept-language", b"uk-UA")]})
    assert "Посилання підписки" in (await sub_proxy.serve(uk_request, SHORT, db)).body.decode()
    de_request = Request({**browser().scope, "headers": [*browser().scope["headers"], (b"accept-language", b"de-DE")]})
    portal["portal"]["language"] = "en"
    assert "Subscription link" in (await sub_proxy.serve(de_request, SHORT, db)).body.decode()
    js = (await sub_proxy.serve(browser(), "-/portal.js", db)).body
    assert b"data-copied" in js and "Скопировано".encode() not in js
    # the neutral page
    portal.update(mask_title="Добро пожаловать", mask_login="Email", mask_password="Код", mask_button="Далее")
    masked = (await sub_proxy.serve(browser(), "x", db)).body.decode()
    assert all(x in masked for x in ("Добро пожаловать", "placeholder='Email'", "placeholder='Код'", ">Далее<"))


def test_texts_are_validated_and_previewed():
    with pytest.raises(ValidationError):  # an unknown placeholder
        sub_proxy.PortalIn(texts={"ru": {"traffic": "{password}"}})
    with pytest.raises(ValidationError):  # an unknown key
        sub_proxy.PortalIn(texts={"ru": {"script": "<b>"}})
    with pytest.raises(ValidationError):
        sub_proxy.PortalIn(texts={"de": {"copy": "Kopieren"}})
    with pytest.raises(ValidationError):
        sub_proxy.PortalIn(colors={"accent": "red;}body{display:none"})
    same = sub_proxy.PortalIn(texts={"ru": {"copy": "Копировать"}}, colors={"accent": "#3b82f6"})
    assert same.texts == {} and same.colors == {}, "values equal to the defaults are not stored"
    html_text = sub_portal.preview(sub_proxy.PortalIn(texts={"ru": {"step1": "<script>alert(1)</script>"}},
                                                     apps=[{"name": "Happ", "deeplink": "happ://add/{url}"}]).model_dump(),
                                   {"name": "Корги Люси", "logo_url": ""}, "ru")
    assert "&lt;script&gt;" in html_text and "<script>alert" not in html_text and "Lucy Max" in html_text
    assert set(sub_portal.TEXTS["ru"]) == set(sub_portal.TEXTS["en"]) == set(sub_portal.TEXTS["uk"])


@pytest.mark.asyncio
async def test_preview_endpoint(database):
    out = await sub_proxy.portal_preview(sub_proxy.PreviewIn(portal={"title": "Проверка"}, language="en"), database, ADMIN)
    assert "Проверка" in out["html"] and "Subscription link" in out["html"]
    meta = await sub_proxy.portal_texts(ADMIN)
    assert meta["languages"] == ["ru", "en", "uk"] and "copy" in meta["defaults"]["ru"] and meta["placeholders"]["traffic"] == ["limit", "used"]
