"""v28.47: the public status page with outage news, and prices / gateways by the customer's country."""
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from starlette.requests import Request

from app import main as shop
from app import regional_pricing as rp
from app import status_page as sp
from app.models import Notification, SecurityIncidentEvent, StatusSubscriber, User
from test_subscription_commerce import database  # noqa: F401

NODES_UP = [{"name": "de-1", "country": "DE", "status": "online"}, {"name": "de-2", "country": "DE", "status": "online"},
            {"name": "nl-1", "country": "NL", "status": "online"}, {"name": "old", "country": "FI", "status": "disabled"}]


def test_regions_hide_names_and_disabled_servers():
    nodes = [*NODES_UP[:1], {"name": "de-2", "country": "DE", "status": "offline"}, NODES_UP[2], NODES_UP[3]]
    regions = sp.regions_from(nodes)
    assert regions == [{"country": "DE", "total": 2, "online": 1, "status": "degraded", "label": "частично"},
                       {"country": "NL", "total": 1, "online": 1, "status": "operational", "label": "работает"}]
    assert all("name" not in r and "address" not in r for r in regions)


@pytest.mark.asyncio
async def test_a_region_down_opens_an_incident_tells_subscribers_and_closes(database, monkeypatch):  # noqa: F811
    db = database
    user = await db.get(User, 1)
    user.telegram_id = 5550001
    db.add(StatusSubscriber(user_id=1))
    await db.commit()
    sent = []

    async def sender(chat, text):
        sent.append((chat, text))
    down = [{"name": "nl-1", "country": "NL", "status": "offline"}, *NODES_UP[:2]]
    now = datetime(2026, 10, 29, 12, 0)
    assert (await sp.watch(db, down, now, sender))["opened"] == [], "not before outage_minutes"
    out = await sp.watch(db, down, now + timedelta(minutes=6), sender)
    inc = await db.get(SecurityIncidentEvent, out["opened"][0])
    assert inc.category == "service" and inc.status == "open" and "NL" in inc.title
    assert sent and sent[0][0] == 5550001 and "NL" in sent[0][1]
    notes = (await db.execute(select(Notification).where(Notification.kind == "status"))).scalars().all()
    assert len(notes) == 1 and notes[0].user_id == 1
    page = await sp.build(db, down, now + timedelta(minutes=7))
    assert page["overall"] == "degraded" and page["incidents"][0]["status"] == "open"
    assert (await sp.watch(db, down, now + timedelta(minutes=9), sender))["opened"] == [], "one incident per outage"
    closed = await sp.watch(db, NODES_UP, now + timedelta(minutes=20), sender)
    await db.refresh(inc)
    assert closed["closed"] == [inc.id] and inc.status == "resolved" and "Восстановлено" in sent[-1][1]


@pytest.mark.asyncio
async def test_page_html_and_subscription_endpoints(database, monkeypatch):  # noqa: F811
    db = database

    async def snapshot(**kw):
        return {"nodes": NODES_UP}
    monkeypatch.setattr("app.node_health.node_snapshot", snapshot)
    data = await sp.public_status_page(db=db)
    assert data["overall"] in {"operational", "degraded"} and {r["country"] for r in data["regions"]} == {"DE", "NL"}
    page = await sp.status_html(db=db)
    assert b"<!DOCTYPE html>" in page.body and b"/api/public/status-page" in page.body and b'src="http' not in page.body, "no outside assets"
    req = Request({"type": "http", "method": "POST", "path": "/api/me/status/subscription", "headers": [], "query_string": b"", "client": ("10.0.0.1", 1)})
    assert (await sp.subscribe(req, db))["subscribed"] is True and (await sp.subscribe(req, db))["subscribed"] is True
    assert (await sp.my_subscription(req, db))["subscribed"] is True
    assert (await sp.unsubscribe(req, db))["subscribed"] is False


CFG = {"enabled": True, "regions": [{"name": "Казахстан", "countries": ["KZ"], "percent": -20, "plan_prices": {"2": "150.00"}, "providers": ["cloudpayments"]},
                                    {"name": "Европа", "countries": ["DE", "NL"], "percent": 50, "plan_prices": {}, "providers": []}]}


def test_region_prices_and_gateway_order():
    kz = rp.region_for(CFG, "kz")
    assert rp.price_for(kz, 1, Decimal("100")) == Decimal("80.00") and rp.price_for(kz, 2, Decimal("200")) == Decimal("150.00")
    assert rp.price_for(rp.region_for(CFG, "DE"), 1, Decimal("99.99")) == Decimal("149.99")
    assert rp.region_for(CFG, "RU") is None and rp.price_for(None, 1, Decimal("100")) == Decimal("100")
    assert rp.region_for({**CFG, "enabled": False}, "KZ") is None
    assert rp.order_providers(kz, ["yookassa", "platega", "cloudpayments"]) == ["cloudpayments", "yookassa", "platega"]
    with pytest.raises(ValueError):
        rp.RegionIn(name="x", countries=["Kazakhstan"])


@pytest.mark.asyncio
async def test_country_from_cloudflare_or_address_but_not_from_own_servers(database, monkeypatch):  # noqa: F811
    db = database
    cf = Request({"type": "http", "method": "GET", "path": "/api/plans", "headers": [(b"cf-ipcountry", b"kz")], "query_string": b"", "client": ("203.0.113.9", 1)})
    assert await rp.country_of(cf, db) == "KZ"

    async def geo(session, ip, budget):
        return ("1", "Holder", "DE")
    monkeypatch.setattr("app.vpn_sessions._geo", geo)
    monkeypatch.setattr(shop, "_client_ip", lambda request: request.client.host)

    async def own():
        return {"198.51.100.7"}
    monkeypatch.setattr(rp, "_own_addresses", own)
    plain = Request({"type": "http", "method": "GET", "path": "/", "headers": [], "query_string": b"", "client": ("203.0.113.9", 1)})
    assert await rp.country_of(plain, db) == "DE"
    via_vpn = Request({"type": "http", "method": "GET", "path": "/", "headers": [], "query_string": b"", "client": ("198.51.100.7", 1)})
    assert await rp.country_of(via_vpn, db) is None, "a customer on our own server gets the base price"


@pytest.mark.asyncio
async def test_plans_list_shows_the_regional_price(database, monkeypatch):  # noqa: F811
    db = database
    from app.node_health import _save
    await _save(db, rp.CONFIG_KEY, CFG)
    await db.commit()
    cf = Request({"type": "http", "method": "GET", "path": "/api/plans", "headers": [(b"cf-ipcountry", b"KZ")], "query_string": b"", "client": ("203.0.113.9", 1)})
    plans = {p["id"]: p for p in await shop.plans(db, cf)}
    assert plans[1]["price"] == 80.0 and plans[2]["price"] == 150.0
    base = {p["id"]: p for p in await shop.plans(db)}
    assert base[1]["price"] == 100.0


@pytest.mark.asyncio
async def test_resolving_an_incident_twice_preserves_chronology_and_audit(database, monkeypatch):
    from types import SimpleNamespace
    from app.enterprise_api import v41_incident_resolve
    from app.models import AuditLog

    db = database
    event = SecurityIncidentEvent(category="service", severity="high", title="Test incident")
    db.add(event)
    await db.commit()
    sent = []

    async def record(session, incident, opened):
        sent.append((incident.id, opened))

    monkeypatch.setattr(sp, "notify", record)
    admin = SimpleNamespace(email="ops@example.test")
    assert await v41_incident_resolve(event.id, db, admin) == {"ok": True}
    await db.refresh(event)
    first_resolved_at = event.resolved_at
    assert first_resolved_at is not None
    assert await v41_incident_resolve(event.id, db, admin) == {"ok": True}
    await db.refresh(event)
    assert event.resolved_at == first_resolved_at
    rows = (await db.scalars(select(AuditLog).where(AuditLog.action == "incident.resolved",
                                                   AuditLog.target == str(event.id)))).all()
    assert len(rows) == 1 and rows[0].actor == admin.email
    assert sent == [(event.id, False)]


@pytest.mark.asyncio
async def test_independent_postgres_sessions_resolve_once(database, monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.enterprise_api import v41_incident_resolve
    from app.models import AuditLog

    db = database
    if db.bind.dialect.name != "postgresql":
        pytest.skip("Concurrent independent sessions require PostgreSQL")
    event = SecurityIncidentEvent(category="service", severity="critical", title="Concurrent recovery")
    db.add(event)
    await db.commit()
    notified = []

    async def record(session, incident, opened):
        notified.append((incident.id, opened))

    monkeypatch.setattr(sp, "notify", record)
    async def resolve(actor):
        async with AsyncSession(db.bind, expire_on_commit=False) as other:
            return await v41_incident_resolve(event.id, other, SimpleNamespace(email=actor))

    assert await asyncio.gather(resolve("a@example.test"), resolve("b@example.test")) == [{"ok": True}] * 2
    rows = (await db.scalars(select(AuditLog).where(AuditLog.action == "incident.resolved",
                                                   AuditLog.target == str(event.id)))).all()
    assert len(rows) == 1
    assert notified == [(event.id, False)]


@pytest.mark.asyncio
async def test_service_monitor_preserves_manual_resolution_and_unknown_id_returns_404(database, monkeypatch):
    from types import SimpleNamespace
    from fastapi import HTTPException
    from app.enterprise_api import v41_incident_resolve

    db = database
    down = [{"name": "nl-1", "country": "NL", "status": "offline"}]
    up = [{"name": "nl-1", "country": "NL", "status": "online"}]
    start = datetime(2026, 10, 28, 9, 0)
    sent = []

    async def record(session, incident, opened, sender=None):
        sent.append((incident.id, opened))

    monkeypatch.setattr(sp, "notify", record)
    await sp.watch(db, down, start)
    opened = await sp.watch(db, down, start + timedelta(minutes=10))
    incident_id, = opened["opened"]
    admin = SimpleNamespace(email="ops@example.test")
    await v41_incident_resolve(incident_id, db, admin)
    event = await db.get(SecurityIncidentEvent, incident_id)
    manual_time = event.resolved_at
    assert (await sp.watch(db, up, start + timedelta(minutes=11)))["closed"] == []
    await db.refresh(event)
    assert event.resolved_at == manual_time
    assert sent == [(incident_id, True), (incident_id, False)]
    with pytest.raises(HTTPException) as missing:
        await v41_incident_resolve(incident_id + 100, db, admin)
    assert missing.value.status_code == 404
