"""The admin apps open the full web panel with a one-time ticket: 60 s, once, bound to the administrator."""
import json

import pytest
from fastapi import HTTPException
from fastapi.responses import Response
from sqlalchemy import select

from app import admin_web_ticket
from app import main as shop
from app.models import AdminSession, AdminUser
from app.security import hash_password, issue_token
from test_behaviour_auth import db, request  # noqa: F401


class Redis:
    def __init__(self):
        self.data, self.ttl = {}, {}

    async def set(self, key, value, ex=None, nx=False):
        self.data[key], self.ttl[key] = value, ex
        return True

    async def getdel(self, key):
        return self.data.pop(key, None)


@pytest.mark.asyncio
async def test_a_ticket_opens_one_browser_session_and_only_once(db, monkeypatch):  # noqa: F811
    redis = Redis()
    monkeypatch.setattr(shop, "redis_client", redis)
    monkeypatch.setattr(shop.settings, "admin_domain", "admin.corgi.test")
    admin = AdminUser(email="ops@corgi.test", password_hash=hash_password("x"), role="operator")
    db.add(admin)
    await db.commit()
    token = issue_token(admin, True, 30, jti="app-jti")
    req = request("/api/admin/auth/web-ticket", token=token)
    out = await admin_web_ticket.issue_web_ticket(req, admin)
    assert out["url"].startswith("https://admin.corgi.test/?ticket=") and out["expires_in"] == 60
    ticket = out["url"].split("ticket=", 1)[1]
    stored = next(iter(redis.data))
    assert ticket not in stored and json.loads(redis.data[stored]) == {"admin_id": admin.id, "mfa": True}, "only a hash is stored"
    response = Response()
    body = await admin_web_ticket.redeem_web_ticket(admin_web_ticket.TicketIn(ticket=ticket), request("/api/admin/auth/ticket"), response, db)
    assert body["email"] == "ops@corgi.test" and "rw_admin=" in response.headers.get("set-cookie", "")
    assert (await db.execute(select(AdminSession))).scalars().first() is not None
    with pytest.raises(HTTPException) as reused:
        await admin_web_ticket.redeem_web_ticket(admin_web_ticket.TicketIn(ticket=ticket), request("/api/admin/auth/ticket"), Response(), db)
    assert reused.value.status_code == 401


@pytest.mark.asyncio
async def test_a_disabled_admin_cannot_use_an_old_ticket(db, monkeypatch):  # noqa: F811
    redis = Redis()
    monkeypatch.setattr(shop, "redis_client", redis)
    admin = AdminUser(email="old@corgi.test", password_hash=hash_password("x"), role="operator")
    db.add(admin)
    await db.commit()
    out = await admin_web_ticket.issue_web_ticket(request("/x", token=issue_token(admin, False, 30, jti="j")), admin)
    admin.disabled = True
    await db.commit()
    with pytest.raises(HTTPException):
        await admin_web_ticket.redeem_web_ticket(admin_web_ticket.TicketIn(ticket=out["url"].split("ticket=")[1]), request("/x"), Response(), db)
