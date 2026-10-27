"""2.12.0 Telegram broadcast from the admin panel and the admin apps."""
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import main as shop
from app.models import Broadcast, Subscription, User
from app_contract import permissions
from test_subscription_commerce import database  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]


def test_broadcast_admin_apps_expose_it():
    admin = (ROOT / "admin/src/main.tsx").read_text()
    android = (ROOT / "mobile/android-admin/app/src/main/java/shop/remnawave/admin/MainActivity.kt").read_text()
    ios = (ROOT / "mobile/ios-admin/VpnShopAdmin/ContentView.swift").read_text()
    assert 'target:btarget' in admin or "target:btarget" in admin
    assert "/api/admin/broadcasts/" in admin
    assert "Все с Telegram" in admin and "Активная подписка" in admin
    assert "/api/admin/broadcasts" in android and "/api/admin/marketing" in android
    assert "broadcastTarget" in android
    assert "/api/admin/broadcasts" in ios and "broadcastTarget" in ios
    notes = (ROOT / "docs/archive/root/RELEASE_NOTES_V2_12_0.md").read_text()
    assert "2.12.0" in notes and "Русский" in notes and "English" in notes
    assert "manage_broadcasts" in notes


def test_broadcast_routes_need_the_broadcast_permission():
    assert permissions("POST", "/api/admin/broadcasts") == {"manage_broadcasts"}
    assert permissions("POST", "/api/admin/broadcasts/{broadcast_id}/retry") == {"manage_broadcasts"}


@pytest.mark.asyncio
async def test_recipients_are_counted_once_per_telegram_customer(database):
    from app.bot import broadcast_recipient_query
    now = datetime.utcnow()
    (await database.get(User, 1)).telegram_id = 1001
    database.add_all([User(id=3, telegram_id=1003, referral_code="U3"), User(id=4, referral_code="U4"),
                      Subscription(id=2, user_id=1, plan_id=1, expires_at=now + timedelta(days=3), is_primary=False),
                      Subscription(id=3, user_id=3, plan_id=1, expires_at=now - timedelta(days=3))])
    await database.commit()
    rows = {t: [r.id for r in (await database.execute(broadcast_recipient_query(t, now))).all()] for t in ("all", "active", "inactive")}
    assert rows["all"] == [1, 3], "only customers with Telegram"
    assert rows["active"] == [1], "two live subscriptions, one message"
    assert rows["inactive"] == [3]


@pytest.mark.asyncio
async def test_a_broadcast_is_validated_before_it_is_queued(database, monkeypatch):
    monkeypatch.setattr(shop.settings, "bot_token", "123:abc")
    monkeypatch.setattr(shop, "validate_public_url", lambda value, **kw: value)
    admin = SimpleNamespace(email="a@b.c")
    bad = [({"text": "x", "button_text": "Открыть"}, "Button text and URL are set together"),
           ({"text": "x" * 1025, "image_url": "https://cdn.example/a.png"}, "Caption is longer than 1024 characters"),
           ({"text": "x", "target": "everyone"}, "Unsupported target")]
    for data, detail in bad:
        with pytest.raises(HTTPException) as refused:
            await shop.create_broadcast(shop.BroadcastIn(**data), database, admin)
        assert refused.value.detail == detail
    out = await shop.create_broadcast(shop.BroadcastIn(text="Новый сервер", button_text="Открыть", button_url="https://t.me/x"), database, admin)
    assert out["status"] == "queued"
    row = await database.get(Broadcast, out["id"])
    with pytest.raises(HTTPException) as queued:
        await shop.retry_broadcast(row.id, database, admin)
    assert queued.value.status_code == 409, "only a stopped or failed broadcast is retried"
    row.status, row.sent_count = "failed", 5
    await database.commit()
    again = await shop.retry_broadcast(row.id, database, admin)
    assert again == {"id": row.id, "status": "queued", "sent_count": 5, "failed_count": row.failed_count}, "a retry continues, it does not resend"
