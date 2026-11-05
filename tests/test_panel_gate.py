"""v28.78.0 (stage 18): «Доступ к панели → Вход через магазин» — the shop's own login in front of a Remnawave panel
(backend/app/panel_gate.py) instead of the TinyAuth container. The real Caddy runs it in tests/live/test_panel_gate_live.py."""
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from starlette.requests import Request

from app import main as shop
from app import panel_gate, rw_plan, rw_steps
from app.models import AdminSession, AdminUser, AuditLog, RemnawaveInstallation
from test_subscription_commerce import database  # noqa: F401

PANEL = "panel.example.com"
CHROME = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/140.0"


class FakeRedis:
    def __init__(self):
        self.data = {}

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.data:
            return False
        self.data[key] = value
        return True

    async def getdel(self, key):
        return self.data.pop(key, None)


def request(path="/", host=PANEL, cookie="", agent=CHROME):
    headers = [(b"x-corgi-gate-host", host.encode()), (b"user-agent", agent.encode())]
    if cookie:
        headers.append((b"cookie", f"{panel_gate.COOKIE}={cookie}".encode()))
    return Request({"type": "http", "method": "GET", "path": path, "headers": headers, "query_string": b"", "client": ("203.0.113.9", 1)})


@pytest.fixture
def gate(database, monkeypatch):
    monkeypatch.setattr(shop, "redis_client", FakeRedis())
    monkeypatch.setattr(panel_gate.settings, "admin_domain", "admin.shop.example")
    panel_gate._cache.clear()
    return database


async def setup(db, role="admin"):
    admin = AdminUser(email="ops@corgi.test", password_hash="x", role=role)
    row = RemnawaveInstallation(created_by="ci", action="install", mode="panel", server_ids=[1], status="succeeded", plan={}, plan_sha256="0" * 64,
                                params={"panel_server_id": 1, "panel_domain": PANEL, "panel_access": "gate"})
    db.add_all([admin, row])
    await db.commit()
    return admin, row


async def login(db, admin, row):
    out = await panel_gate.open_panel(row.id, db, admin)
    assert out["url"].startswith(f"https://{PANEL}/__corgi_gate?t=")
    ticket = out["url"].split("t=", 1)[1]
    answer = await panel_gate.redeem(ticket, request(), db)
    cookie = answer.headers["set-cookie"]
    return ticket, cookie.split(";")[0].split("=", 1)[1], cookie


@pytest.mark.asyncio
async def test_open_login_verify(gate):
    db = gate
    admin, row = await setup(db)
    without = await panel_gate.verify(request(), db)
    assert without.status_code == 302 and without.headers["location"] == "https://admin.shop.example/#rwInstaller"
    assert (await panel_gate.verify(request(agent="curl/8"), db)).status_code == 401
    ticket, token, raw = await login(db, admin, row)
    assert "HttpOnly" in raw and "Secure" in raw and "SameSite=lax" in raw and "Domain" not in raw, "a cookie of the panel's own domain"
    assert (await panel_gate.verify(request(cookie=token), db)).status_code == 200
    with pytest.raises(HTTPException) as err:  # one-time
        await panel_gate.redeem(ticket, request(), db)
    assert err.value.status_code == 401
    panel_gate._cache.clear()
    assert (await panel_gate.verify(request(cookie=token, host="other.example.com"), db)).status_code == 302, "bound to the domain"
    assert (await panel_gate.verify(request(cookie=token + "x"), db)).status_code == 302
    actions = set((await db.execute(select(AuditLog.action).where(AuditLog.action.like("rw.panel_gate.%")))).scalars())
    assert actions == {"rw.panel_gate.ticket", "rw.panel_gate.login"}


@pytest.mark.asyncio
async def test_revocation_closes_the_panel(gate):
    db = gate
    admin, row = await setup(db)
    _, token, _ = await login(db, admin, row)
    from app.security import revoke_all_admin_sessions
    await revoke_all_admin_sessions(db, admin.id)
    await db.commit()
    panel_gate._cache.clear()
    assert (await panel_gate.verify(request(cookie=token), db)).status_code == 302
    _, token, _ = await login(db, admin, row)
    admin.role = "viewer"  # no provision_nodes
    await db.commit()
    panel_gate._cache.clear()
    assert (await panel_gate.verify(request(cookie=token), db)).status_code == 302
    admin.role, admin.disabled = "admin", True
    await db.commit()
    panel_gate._cache.clear()
    assert (await panel_gate.verify(request(cookie=token), db)).status_code == 302
    session = (await db.execute(select(AdminSession).order_by(AdminSession.id.desc()))).scalars().first()
    assert session.expires_at > datetime.utcnow() + timedelta(hours=11)


@pytest.mark.asyncio
async def test_tickets_only_for_gate_installations_and_on_the_panel_domain(gate):
    db = gate
    admin, row = await setup(db)
    other = RemnawaveInstallation(created_by="ci", action="install", mode="panel", server_ids=[1], status="succeeded", plan={}, plan_sha256="1" * 64,
                                  params={"panel_server_id": 1, "panel_domain": "p2.example.com", "panel_access": "cookie"})
    db.add(other)
    await db.commit()
    with pytest.raises(HTTPException) as err:
        await panel_gate.open_panel(other.id, db, admin)
    assert err.value.status_code == 409
    out = await panel_gate.open_panel(row.id, db, admin)
    with pytest.raises(HTTPException) as err:  # redeemed on another host (a link carried elsewhere)
        await panel_gate.redeem(out["url"].split("t=", 1)[1], request(host="evil.example.com"), db)
    assert err.value.status_code == 400
    with pytest.raises(HTTPException):
        await panel_gate.redeem("short", request(), db)


def test_caddyfile_and_plan():
    caddy = rw_plan.caddyfile({PANEL: 3000}, "acme", "a@example.com", gate={PANEL: "https://api.shop.example"})
    assert "handle /__corgi_gate {" in caddy and "rewrite * /api/panel-gate/redeem?{query}" in caddy
    assert "forward_auth @guarded https://api.shop.example {" in caddy and "uri /api/panel-gate/verify" in caddy
    assert caddy.count("header_up X-Corgi-Gate-Host {host}") == 2 and "not path /api/sub/*" in caddy
    assert caddy.index("forward_auth") < caddy.index("reverse_proxy 127.0.0.1:3000")
    for bad in ("http://api.shop.example", "https://api.shop.example/x", "https://api.shop.example\n}"):
        with pytest.raises(ValueError):
            rw_plan.caddyfile({PANEL: 3000}, "acme", None, gate={PANEL: bad})
    with pytest.raises(ValidationError):
        rw_plan.PlanIn(mode="node", node_server_ids=[2], panel_access="gate")
    built = rw_plan.build_plan(rw_plan.PlanIn(mode="panel", panel_server_id=1, panel_domain=PANEL, tls="internal", panel_access="gate"),
                               {1: {"name": "s1", "host": "93.184.216.34"}}, None)
    assert any("администраторам магазина" in c for c in built["servers"]["1"]["changes"])


@pytest.mark.asyncio
async def test_wizard_files_point_at_the_shop(monkeypatch):
    monkeypatch.setattr(panel_gate.settings, "api_domain", "api.shop.example")
    plan = rw_plan.PlanIn(mode="panel", panel_server_id=1, panel_domain=PANEL, tls="internal", panel_access="gate")
    ctx = rw_steps.Context(plan=plan, servers={1: {"name": "s1", "host": "93.184.216.34"}}, secrets=rw_steps.new_secrets(), state={})
    files = await rw_steps.files_for(ctx, "proxy", 1)
    assert set(files) == {"Caddyfile", "docker-compose.yml"} and "forward_auth @guarded https://api.shop.example" in files["Caddyfile"]
    assert "tinyauth" not in files["docker-compose.yml"]


@pytest.mark.asyncio
async def test_plan_needs_a_public_shop_address(monkeypatch):
    from app import rw_api
    monkeypatch.setattr(panel_gate.settings, "api_domain", "localhost")
    monkeypatch.setattr(panel_gate.settings, "public_base_url", "http://localhost:8000")
    with pytest.raises(HTTPException) as err:
        rw_api._gate_ready("gate")
    assert err.value.status_code == 422
    monkeypatch.setattr(panel_gate.settings, "api_domain", "api.shop.example")
    rw_api._gate_ready("gate")
    rw_api._gate_ready("cookie")


def test_admin_dependency_is_used():
    from app import admin_center
    routes = {p: r for r, p in admin_center._walk(shop.app.routes)}
    assert "POST" in routes["/api/admin/rw/installations/{installation_id}/panel-gate"].methods
    assert {"/api/panel-gate/verify", "/api/panel-gate/redeem"} <= set(routes)
