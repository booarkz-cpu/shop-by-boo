"""v43.1 re-audit, checked by running the code (was: code lines searched in main.py).
The emergency payment switch runs in test_v40_security_gate.py."""
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from starlette.requests import Request

from app import main as shop
from app.models import BotMenuItem, CustomField, Subscription
from test_subscription_commerce import database  # noqa: F401

ADMIN = SimpleNamespace(email="a@b.c")


@pytest.mark.asyncio
async def test_menu_field_buttons_need_an_existing_enabled_field(database):
    database.add(CustomField(key="support_chat", label="Чат", value="https://t.me/x", enabled=False))
    await database.commit()
    with pytest.raises(HTTPException) as unknown:
        await shop.admin_menu(shop.MenuIn(title="Чат", action="support_chat", item_type="field"), database, ADMIN)
    assert unknown.value.detail == "Кнопка field ссылается на неизвестное или отключённое поле"
    field = (await database.execute(select(CustomField))).scalar_one()
    field.enabled = True
    await database.commit()
    assert (await shop.admin_menu(shop.MenuIn(title="Чат", action="support_chat", item_type="field"), database, ADMIN))["id"]


@pytest.mark.asyncio
async def test_the_bot_menu_has_at_most_30_buttons(database, monkeypatch):
    monkeypatch.setattr(shop, "validate_public_url", lambda value, **kw: value)
    database.add_all([BotMenuItem(title=f"b{i}", action="https://shop.example", item_type="url", sort_order=i) for i in range(30)])
    await database.commit()
    with pytest.raises(HTTPException) as full:
        await shop.admin_menu(shop.MenuIn(title="31", action="https://shop.example", item_type="url"), database, ADMIN)
    assert full.value.status_code == 400 and "30 кнопок" in full.value.detail


@pytest.mark.asyncio
async def test_connection_info_answers_once_without_caching(database):
    sub = await database.get(Subscription, 1)
    sub.subscription_url = "https://sub.corgi.test/abc"
    await database.commit()
    request = Request({"type": "http", "method": "GET", "path": "/api/me/connection-info", "client": ("10.0.0.1", 1), "query_string": b"",
                       "headers": [(b"accept-language", b"en-US")]})
    response = await shop.connection_info(request, database)
    body = json.loads(response.body)
    assert response.headers["Cache-Control"] == "private, no-store"
    assert body["subscription_url"] == "https://sub.corgi.test/abc" and body["platforms"]["ios"].startswith("iOS: install")
    sub.subscription_url = "https://x\r\nSet-Cookie: a=b"
    await database.commit()
    assert json.loads((await shop.connection_info(request, database)).body)["subscription_url"] is None, "a broken link is never handed out"
