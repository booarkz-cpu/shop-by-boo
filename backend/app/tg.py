"""Small Telegram Bot API helper for the backend (the bot process has aiogram; the API and workers use this)."""
from __future__ import annotations

import httpx

from .config import settings


class TelegramError(Exception):
    def __init__(self, code: int, description: str):
        super().__init__(f"{code}: {description}")
        self.code = code
        self.description = description

    @property
    def blocked(self) -> bool:
        """The user blocked the bot, deleted the account or never started it."""
        text = self.description.lower()
        return self.code == 403 or "chat not found" in text or "user is deactivated" in text


async def call(method: str, payload: dict, client: httpx.AsyncClient | None = None) -> dict:
    """POST one Bot API method; returns ``result`` or raises TelegramError (429 carries retry_after in the text)."""
    if not settings.bot_token:
        raise TelegramError(0, "BOT_TOKEN is not set")
    own = client is None
    client = client or httpx.AsyncClient(timeout=15)
    try:
        response = await client.post(f"https://api.telegram.org/bot{settings.bot_token}/{method}", json=payload)
        body = response.json() if response.content else {}
    finally:
        if own:
            await client.aclose()
    if not body.get("ok"):
        raise TelegramError(int(body.get("error_code") or response.status_code), str(body.get("description") or ""))
    return body.get("result")
