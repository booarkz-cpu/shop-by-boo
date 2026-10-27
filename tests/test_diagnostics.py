"""«Не работает VPN»: the app's checks plus the shop's facts give a cause, hints and a support ticket."""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select
from starlette.requests import Request

from app import diagnostics, node_health
from app import main as shop
from app.models import Subscription, SupportTicket, User
from test_subscription_commerce import database  # noqa: F401


def req():
    return Request({"type": "http", "method": "POST", "path": "/api/me/diagnostics", "client": ("10.0.0.1", 1), "query_string": b"", "headers": []})


@pytest.fixture
def env(database, monkeypatch):
    async def first(request, session):
        return await session.get(User, 1)

    async def snapshot():
        return {"nodes": [{"name": "DE", "status": "online"}, {"name": "NL", "status": "online"}]}
    monkeypatch.setattr(shop, "user_from_token", first)
    monkeypatch.setattr(node_health, "node_snapshot", snapshot)
    return database


def checks(api=True, servers=(True, True)):
    out = [diagnostics.CheckIn(name="dns", target="api.corgi.test", ok=True, ms=12),
           diagnostics.CheckIn(name="api", target="https://api.corgi.test/health/live", ok=api, ms=80),
           diagnostics.CheckIn(name="subscription", ok=True, detail="2 сервера")]
    out += [diagnostics.CheckIn(name="server", target=f"de{i}.corgi.test:443", ok=ok, ms=40 if ok else None) for i, ok in enumerate(servers)]
    return out


@pytest.mark.asyncio
async def test_blocked_servers_are_told_apart_and_a_ticket_carries_the_report(env):
    sub = await env.get(Subscription, 1)
    sub.expires_at = datetime.utcnow() + timedelta(days=10)
    await env.commit()
    out = await diagnostics.my_diagnostics(diagnostics.DiagnosticsIn(message="Не подключается дома", platform="android", app_version="3.2.0",
                                                                    vpn_state="ON", checks=checks(servers=(False, False))), req(), env)
    assert out["cause"] == "servers_blocked" and "Авто" in out["hints"][0]
    ticket = await env.scalar(select(SupportTicket).where(SupportTicket.id == out["ticket_id"]))
    assert "Не подключается дома" in ticket.message and "✗ server de0.corgi.test:443" in ticket.message and "ноды в сети: 2/2" in ticket.message


@pytest.mark.asyncio
async def test_the_most_likely_cause_comes_first(env):
    sub = await env.get(Subscription, 1)
    sub.expires_at = datetime.utcnow() - timedelta(days=1)
    await env.commit()
    out = await diagnostics.my_diagnostics(diagnostics.DiagnosticsIn(checks=checks(api=False, servers=(False,))), req(), env)
    assert out["cause"] == "expired", "an expired subscription explains everything else"
    sub.expires_at = datetime.utcnow() + timedelta(days=1)
    await env.commit()
    assert (await diagnostics.my_diagnostics(diagnostics.DiagnosticsIn(checks=checks(api=False)), req(), env))["cause"] == "shop_unreachable"
    assert (await diagnostics.my_diagnostics(diagnostics.DiagnosticsIn(checks=checks(servers=(True, False))), req(), env))["cause"] == "some_servers"
    assert (await diagnostics.my_diagnostics(diagnostics.DiagnosticsIn(checks=checks()), req(), env))["cause"] == "unknown"
