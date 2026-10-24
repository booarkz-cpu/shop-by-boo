"""Bot handlers follow Bot API rules: Web App buttons only in private chats, flood control retries."""
from types import SimpleNamespace

import httpx
import pytest

from app import bot


class Msg:
    def __init__(self, chat_type, text="/buy"):
        self.chat = SimpleNamespace(type=chat_type, id=-100)
        self.from_user = SimpleNamespace(id=5, language_code="ru", username="u")
        self.text = text
        self.sent = []

    async def answer(self, text, **kwargs):
        self.sent.append((text, kwargs))


@pytest.mark.asyncio
async def test_buy_and_promo_in_groups_send_no_web_app_button():
    for handler, text in ((bot.buy, "/buy"), (bot.promo, "/promo AUTUMN")):
        msg = Msg("supergroup", text)
        await handler(msg)
        assert msg.sent and "reply_markup" not in msg.sent[0][1]


@pytest.mark.asyncio
async def test_promo_rejects_malformed_codes():
    msg = Msg("private", "/promo " + "x" * 200)
    await bot.promo(msg)
    assert "reply_markup" not in msg.sent[0][1]
    msg = Msg("private", "/promo autumn-20")
    await bot.promo(msg)
    markup = msg.sent[0][1]["reply_markup"]
    assert markup.inline_keyboard[0][0].web_app.url.endswith("?promo=AUTUMN-20")


@pytest.mark.asyncio
async def test_flood_control_waits_retry_after_and_retries(monkeypatch):
    replies = [httpx.Response(429, json={"ok": False, "parameters": {"retry_after": 1}}),
               httpx.Response(429, json={"ok": False, "parameters": {"retry_after": 2}}),
               httpx.Response(200, json={"ok": True})]
    waits = []

    async def sleep(seconds):
        waits.append(seconds)
    monkeypatch.setattr(bot.asyncio, "sleep", sleep)
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: replies.pop(0)))
    response = await bot._telegram_post(client, "sendMessage", {"chat_id": 1, "text": "x"})
    assert response.status_code == 200 and waits == [1.0, 2.0]
