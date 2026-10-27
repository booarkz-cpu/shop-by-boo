from pathlib import Path

import pytest

from test_subscription_commerce import database  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = (ROOT / "release-manifest.template.json").read_text()


def test_release_is_v1_0_2_realise():
    assert '"version": "2.0.0-realise"' in MANIFEST


# Renewed locks are released by their owner through the helper: test_v1_release_deep_audit.py.
@pytest.mark.asyncio
async def test_an_expiry_reminder_is_sent_once_and_retried_after_a_failure(database, monkeypatch):
    from datetime import datetime, timedelta

    from app import main as shop
    from app.models import Subscription, User

    class Redis:
        def __init__(self):
            self.keys = {}

        async def get(self, key):
            return self.keys.get(key)

        async def set(self, key, value, nx=False, ex=None):
            if nx and key in self.keys:
                return False
            self.keys[key] = value
            return True

        async def delete(self, key):
            self.keys.pop(key, None)

    class Telegram:
        status = 500
        sent = []

        async def post(self, url, json):
            Telegram.sent.append(json["chat_id"])
            return type("R", (), {"status_code": Telegram.status})()
    monkeypatch.setattr(shop, "redis_client", Redis())
    monkeypatch.setattr(shop.settings, "bot_token", "1:x")
    (await database.get(User, 1)).telegram_id = 101
    (await database.get(Subscription, 1)).expires_at = datetime.utcnow() + timedelta(days=1)
    await database.commit()
    assert await shop.send_expiry_reminders(database, Telegram()) == 0, "Telegram refused: nothing is marked sent"
    Telegram.status = 200
    assert await shop.send_expiry_reminders(database, Telegram()) == 1, "the next hour tries again"
    assert await shop.send_expiry_reminders(database, Telegram()) == 0, "and never twice for the same end date"
    assert Telegram.sent == [101, 101]
