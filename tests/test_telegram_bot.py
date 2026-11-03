"""v28.71.0 (stage 13): the Telegram bot management — token without restart, the connection state, the admin section.

Telegram itself is replaced by a fake: the live check against the real Bot API runs in CI with the test bot's token
(tests/live/test_telegram_live.py, BLOCKED_SECRETS without it)."""
import asyncio
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from app import bot, error_log, runtime_settings, system_status, telegram_bot
from app.config import settings
from app.models import AuditLog, SystemErrorLog, TelegramBotState, User
from test_subscription_commerce import database  # noqa: F401

ADMIN = SimpleNamespace(email="owner@corgi.test", role="admin")
TOKEN_A = "123456789:" + "A" * 35
TOKEN_B = "987654321:" + "B" * 35


@pytest.fixture
def telegram(monkeypatch):
    calls = []

    async def call(method, payload=None, token=None, timeout=15):
        calls.append((method, payload or {}))
        if (token or settings.bot_token) == "123:BAD":
            raise telegram_bot.TelegramError("Unauthorized")
        if method == "getMe":
            return {"id": 123456789, "username": "corgi_lucy_bot", "first_name": "Корги Люси", "can_join_groups": True}
        if method == "getWebhookInfo":
            return {"url": "https://old.example.com/hook", "pending_update_count": 3, "last_error_message": None}
        if method == "sendMessage":
            return {"message_id": 42}
        return True
    monkeypatch.setattr(telegram_bot, "call", call)
    monkeypatch.setattr(settings, "bot_token", TOKEN_A)
    monkeypatch.setattr(settings, "bot_username", "corgi_lucy_bot")
    return calls


def test_token_is_a_runtime_secret_with_a_shape():
    definition = next(d for d in runtime_settings.DEFINITIONS if d.key == "bot_token")
    assert definition.secret and definition.group == "telegram"
    assert runtime_settings._parse_value(definition, " " + TOKEN_A + "\n") == TOKEN_A
    with pytest.raises(HTTPException):
        runtime_settings._parse_value(definition, "not-a-token")
    assert runtime_settings._parse_value(definition, "") == ""
    assert telegram_bot.fingerprint(TOKEN_A) != telegram_bot.fingerprint(TOKEN_B) and len(telegram_bot.fingerprint(TOKEN_A)) == 12


@pytest.mark.asyncio
async def test_status_check_and_commands(database, telegram):
    db = database
    db.add(User(id=50, telegram_id=777, referral_code="TG50"))
    await db.commit()
    out = await telegram_bot.status(db, ADMIN)
    assert out["token_set"] and out["state"] == "unknown" and out["check"]["status"] == "warn"
    assert TOKEN_A not in json.dumps(out) and out["token_fingerprint_settings"] == telegram_bot.fingerprint(TOKEN_A)
    assert out["stats"]["telegram_users"] == 1

    await telegram_bot.report(db, state="running", username="corgi_lucy_bot", last_ok_at=datetime.utcnow(), updates=5)
    out = await telegram_bot.status(db, ADMIN)
    assert out["connected"] and out["check"]["status"] == "ok" and out["updates_total"] == 5

    live = await telegram_bot.check(db, ADMIN)
    assert live["mode"] == "webhook" and live["pending_updates"] == 3 and not live["username_mismatch"]
    await telegram_bot.delete_webhook(db, ADMIN)
    assert ("deleteWebhook", {"drop_pending_updates": False}) in telegram

    got = await telegram_bot.get_commands(db, ADMIN)
    assert not got["custom"] and [c["command"] for c in got["commands"]["ru"]][:3] == ["start", "buy", "subscription"]
    payload = telegram_bot.CommandsIn(ru=[{"command": "/Start", "description": "Меню"}, {"command": "buy", "description": "Тарифы"}],
                                      en=[{"command": "start", "description": "Menu"}], uk=[])
    saved = await telegram_bot.put_commands(payload, db, ADMIN)
    assert saved["commands"]["ru"][0]["command"] == "start"
    sent = [(m, p) for m, p in telegram if m in ("setMyCommands", "deleteMyCommands")]
    assert sent == [("setMyCommands", {"commands": saved["commands"]["ru"]}),
                    ("setMyCommands", {"commands": saved["commands"]["en"], "language_code": "en"}),
                    ("deleteMyCommands", {"language_code": "uk"})]
    assert (await telegram_bot.get_commands(db, ADMIN))["custom"]
    with pytest.raises(ValidationError):
        telegram_bot.CommandsIn(ru=[{"command": "старт", "description": "x"}])
    with pytest.raises(HTTPException):
        await telegram_bot.put_commands(telegram_bot.CommandsIn(ru=[{"command": "a", "description": "x"}, {"command": "a", "description": "y"}]), db, ADMIN)

    with pytest.raises(HTTPException) as err:  # nobody to write to
        await telegram_bot.test_message(telegram_bot.TestMessageIn(), db, ADMIN)
    assert err.value.status_code == 422
    out = await telegram_bot.test_message(telegram_bot.TestMessageIn(chat_id=777, text="Гав"), db, ADMIN)
    assert out["message_id"] == 42 and ("sendMessage", {"chat_id": 777, "text": "Гав"}) in telegram
    actions = (await db.execute(select(AuditLog.action))).scalars().all()
    assert {"telegram.commands.updated", "telegram.test_message", "telegram.webhook.deleted"} <= set(actions)

    db.add_all([SystemErrorLog(fingerprint="a" * 64, level="ERROR", logger="remnawave.broadcast", message="bot session failed", process="bot"),
                SystemErrorLog(fingerprint="b" * 64, level="ERROR", logger="api", message="api failure", process="api")])
    await db.commit()
    assert [e["message"] for e in (await telegram_bot.errors(db, ADMIN))["errors"]] == ["bot session failed"]

    settings.bot_token = "123:BAD"
    with pytest.raises(HTTPException) as err:
        await telegram_bot.check(db, ADMIN)
    assert err.value.status_code == 502 and "Unauthorized" in err.value.detail


class FakeBot:
    """aiogram's Bot as far as the supervisor uses it."""
    made = []

    def __init__(self, token):
        self.token = token
        FakeBot.made.append(token)
        self.session = SimpleNamespace(close=self._close)
        self.closed = False

    async def _close(self):
        self.closed = True

    async def get_me(self):
        if self.token.startswith("111"):
            raise RuntimeError(f"Unauthorized for token {self.token}")
        return SimpleNamespace(id=int(self.token.split(":")[0]), username=f"bot{self.token[:3]}", first_name="Люси")

    async def delete_webhook(self, drop_pending_updates=False):
        return True


@pytest.mark.asyncio
async def test_supervisor_reconnects_on_a_new_token(database, monkeypatch):
    db = database
    monkeypatch.setattr(bot, "engine", db.bind)
    monkeypatch.setattr(bot, "TOKEN_CHECK", 0.01)
    monkeypatch.setattr(bot, "POLL_CHECK", 0.02)

    async def no_broadcasts(_bot):
        await asyncio.sleep(3600)
    monkeypatch.setattr(bot, "broadcast_worker", no_broadcasts)
    FakeBot.made = []
    monkeypatch.setattr(settings, "bot_token", TOKEN_A)

    async def rotate():
        await asyncio.sleep(0.1)
        settings.bot_token = TOKEN_B  # the owner saves a new token in the runtime settings
    rotation = asyncio.create_task(rotate())
    task = asyncio.create_task(bot.supervise(bot_factory=FakeBot, poll=False, sessions=3))
    await asyncio.sleep(0.3)
    await rotation
    for _ in range(100):
        if FakeBot.made == [TOKEN_A, TOKEN_B]:
            break
        await asyncio.sleep(0.02)
    assert FakeBot.made == [TOKEN_A, TOKEN_B], "the bot reconnected with the new token without a restart"
    db.expire_all()
    row = await db.get(TelegramBotState, 1)
    assert row.state == "running" and row.username == "bot987" and row.token_fingerprint == telegram_bot.fingerprint(TOKEN_B)
    assert row.last_ok_at and TOKEN_B not in json.dumps(telegram_bot.state_view(row))
    settings.bot_token = ""  # ends the second session; with no token the supervisor waits
    await asyncio.sleep(0.1)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    db.expire_all()
    assert (await db.get(TelegramBotState, 1)).state == "idle"

    # A refused token: the error is recorded with the token masked, and the bot retries.
    bad = "111111111:" + "C" * 35
    settings.bot_token = bad
    task = asyncio.create_task(bot.supervise(bot_factory=FakeBot, poll=False, sessions=1))
    for _ in range(100):
        db.expire_all()
        row = await db.get(TelegramBotState, 1)
        if row.state == "error":
            break
        await asyncio.sleep(0.02)
    settings.bot_token = ""
    await asyncio.sleep(0.05)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert row.state == "error" and "Unauthorized" in row.last_error and bad not in row.last_error and "***" in row.last_error


def test_system_status_reads_the_bot_state(monkeypatch):
    monkeypatch.setattr(settings, "bot_token", TOKEN_A)
    stale = SimpleNamespace(state="running", last_ok_at=datetime.utcnow() - timedelta(minutes=10), bot_id=1, username="b", first_name="",
                            token_fingerprint="", started_at=None, last_update_at=None, updates_total=0, last_error=None,
                            last_error_at=None, commands_applied_at=None)
    assert system_status.telegram_check(telegram_bot.state_view(stale))["status"] == "error"
    stale.last_ok_at = datetime.utcnow()
    assert system_status.telegram_check(telegram_bot.state_view(stale))["status"] == "ok"
    assert error_log.install  # the bot process installs the error log handler (bot.main)
