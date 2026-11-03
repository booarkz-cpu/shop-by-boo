"""v28.71.0 (stage 13): the shop's bot against the real Telegram Bot API with the owner's test bot.

The token comes from the Actions secret TELEGRAM_TEST_BOT_TOKEN (never from the repository). Checked:

* the supervisor connects with the token: getMe, the state row «running» with the bot's username, long polling starts
  and stops cleanly when the token setting changes (reconnecting to a new token is covered by tests/test_telegram_bot.py);
* the admin section's live check (getMe, getWebhookInfo) and the command menu applied on three languages and read back
  from Telegram (getMyCommands), then the shop's default menu restored.

Skipped without the secret — the status is BLOCKED_SECRETS."""
import asyncio
import os
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app import bot, telegram_bot
from app.config import settings
from app.models import Base, TelegramBotState

TOKEN = os.environ.get("TELEGRAM_TEST_BOT_TOKEN", "")
pytestmark = pytest.mark.skipif(not TOKEN, reason="no TELEGRAM_TEST_BOT_TOKEN secret (BLOCKED_SECRETS)")
ADMIN = SimpleNamespace(email="ci@corgi.test", role="admin")


@pytest_asyncio.fixture
async def db(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/tg.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(bot, "engine", engine)
    monkeypatch.setattr(settings, "bot_token", TOKEN)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_bot_connects_polls_and_takes_commands(db, monkeypatch):
    monkeypatch.setattr(bot, "TOKEN_CHECK", 1)
    monkeypatch.setattr(bot, "POLL_CHECK", 2)
    live = await telegram_bot.check(db, ADMIN)
    print("bot:", live["username"], "mode:", live["mode"])
    assert live["bot_id"] and live["username"]

    task = asyncio.create_task(bot.supervise(sessions=1))
    row = None
    for _ in range(30):
        await asyncio.sleep(1)
        db.expire_all()
        row = await db.get(TelegramBotState, 1)
        if row and row.state == "running" and row.last_ok_at and row.username:
            break
    assert row and row.state == "running" and row.username == live["username"], row and row.last_error
    assert row.token_fingerprint == telegram_bot.fingerprint(TOKEN)
    await asyncio.sleep(4)  # long polling runs, the periodic check («getMe») passes
    settings.bot_token = ""  # the token removed in the settings: the session ends cleanly
    await asyncio.wait_for(task, timeout=30)
    settings.bot_token = TOKEN
    assert (await telegram_bot.check(db, ADMIN))["mode"] == "polling", "the bot removed any webhook and polls"

    menu = telegram_bot.CommandsIn(ru=[{"command": "start", "description": "Главное меню (CI)"}],
                                   en=[{"command": "start", "description": "Main menu (CI)"}],
                                   uk=[{"command": "start", "description": "Головне меню (CI)"}])
    await telegram_bot.put_commands(menu, db, ADMIN)
    for lang, text in (("en", "Main menu (CI)"), ("uk", "Головне меню (CI)")):
        got = await telegram_bot.call("getMyCommands", {"language_code": lang})
        assert got == [{"command": "start", "description": text}]
    assert await telegram_bot.call("getMyCommands", {}) == [{"command": "start", "description": "Главное меню (CI)"}]
    await telegram_bot.put_commands(telegram_bot.CommandsIn(**telegram_bot.default_commands()), db, ADMIN)
    assert len(await telegram_bot.call("getMyCommands", {})) == len(telegram_bot.DEFAULT_COMMANDS["ru"])
