"""Telegram bot management (v28.71, stage 13; docs/ru/new/TELEGRAM_GUIDE.md).

* **State.** The bot process (``bot.py``) writes one row, ``telegram_bot_state``: who it is (``getMe``), when Telegram
  last answered, the last update it received and the last error. «Состояние системы» and the «Telegram-бот» section
  read it — so the owner sees whether the bot actually talks to Telegram, not only that a token is set.
* **Token without restart.** ``BOT_TOKEN`` is a runtime setting (encrypted). The bot process re-reads it and reconnects
  with the new token (``bot.supervise``); the token never reaches the browser, only its fingerprint.
* **Admin.** Live check (``getMe``, ``getWebhookInfo``), the command menu on ru / en / uk (``setMyCommands``), a test
  message, removing a stale webhook, statistics and the bot's errors from the error log.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import get_db
from .security import require_permission

router = APIRouter(prefix="/api/admin/telegram", tags=["telegram-bot"])
TOKEN = re.compile(r"^\d{5,16}:[A-Za-z0-9_-]{30,64}$")
COMMAND = re.compile(r"^[a-z0-9_]{1,32}$")
LANGS = ("ru", "en", "uk")
FRESH = timedelta(minutes=3)
# The menu the bot's handlers answer (bot.py, bot_workspace.py); the owner edits descriptions and order.
DEFAULT_COMMANDS = {
    "ru": [("start", "Главное меню"), ("buy", "Тарифы и покупка"), ("subscription", "Моя подписка"), ("keys", "Ключи и устройства"),
           ("promo", "Промокод"), ("status", "Уведомления"), ("info", "Помощь и документы"), ("app", "Вход в приложение")],
    "en": [("start", "Main menu"), ("buy", "Plans and purchase"), ("subscription", "My subscription"), ("keys", "Keys and devices"),
           ("promo", "Promo code"), ("status", "Notifications"), ("info", "Help and documents"), ("app", "Sign in to the app")],
    "uk": [("start", "Головне меню"), ("buy", "Тарифи та покупка"), ("subscription", "Моя підписка"), ("keys", "Ключі та пристрої"),
           ("promo", "Промокод"), ("status", "Сповіщення"), ("info", "Допомога та документи"), ("app", "Вхід у застосунок")],
}


def fingerprint(token: str) -> str:
    """What the admin panel and the logs may show instead of the token."""
    return hashlib.sha256(token.encode()).hexdigest()[:12] if token else ""


class TelegramError(RuntimeError):
    """Telegram's own description (never the URL: it carries the token)."""


async def call(method: str, payload: dict | None = None, token: str | None = None, timeout: float = 15) -> Any:
    token = settings.bot_token if token is None else token
    if not token:
        raise TelegramError("BOT_TOKEN не задан")
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            answer = await client.post(f"https://api.telegram.org/bot{token}/{method}", json=payload or {})
    except httpx.HTTPError as exc:
        raise TelegramError(f"Telegram недоступен: {type(exc).__name__}") from None
    try:
        data = answer.json()
    except ValueError:
        raise TelegramError(f"Telegram ответил {answer.status_code}") from None
    if not data.get("ok"):
        raise TelegramError(str(data.get("description") or f"Telegram ответил {answer.status_code}")[:300])
    return data.get("result")


# ---------------------------------------------------------------- state (written by the bot process)

async def _row(db: AsyncSession):
    from .models import TelegramBotState
    row = await db.get(TelegramBotState, 1)
    if row is None:
        row = TelegramBotState(id=1, state="idle", updates_total=0, updated_at=datetime.utcnow())
        db.add(row)
    return row


async def report(db: AsyncSession, *, updates: int = 0, **fields) -> None:
    row = await _row(db)
    for key, value in fields.items():
        setattr(row, key, value)
    if updates:
        row.updates_total = (row.updates_total or 0) + updates
    row.updated_at = datetime.utcnow()
    await db.commit()


def state_view(row, now: datetime | None = None) -> dict:
    now = now or datetime.utcnow()
    if row is None:
        return {"state": "unknown", "connected": False}
    connected = bool(row.last_ok_at and now - row.last_ok_at <= FRESH and row.state == "running")
    iso = lambda v: v.isoformat() + "Z" if v else None  # noqa: E731
    return {"state": row.state, "connected": connected, "bot_id": row.bot_id, "username": row.username, "first_name": row.first_name,
            "token_fingerprint": row.token_fingerprint, "started_at": iso(row.started_at), "last_ok_at": iso(row.last_ok_at),
            "last_update_at": iso(row.last_update_at), "updates_total": row.updates_total, "last_error": row.last_error,
            "last_error_at": iso(row.last_error_at), "commands_applied_at": iso(row.commands_applied_at)}


async def current_state(db: AsyncSession) -> dict:
    from .models import TelegramBotState
    return state_view(await db.get(TelegramBotState, 1))


def status_check(state: dict, token_set: bool, username: str) -> tuple[str, str]:
    """«Состояние системы»: ok only when the bot process talked to Telegram within the last minutes."""
    if not token_set:
        return "off", "Бот не настроен: укажите BOT_TOKEN в «Настройки без перезапуска → Telegram»."
    if state.get("connected"):
        return "ok", f"@{state.get('username') or username.lstrip('@')} на связи с Telegram (ответ {state.get('last_ok_at')})."
    if state.get("state") == "error":
        return "error", f"Бот не может работать с Telegram: {state.get('last_error') or 'ошибка'}."
    if state.get("last_ok_at"):
        return "error", f"Бот не связывался с Telegram с {state['last_ok_at']}: процесс бота остановлен или нет сети."
    return "warn", "Токен задан, но процесс бота ещё не сообщил о связи с Telegram (запущен ли контейнер bot?)."


# ---------------------------------------------------------------- admin

@router.get("/status")
async def status(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("settings.runtime.read"))):
    from .models import User
    state = await current_state(db)
    since = datetime.utcnow() - timedelta(days=1)
    telegram_users = int(await db.scalar(select(func.count()).select_from(User).where(User.telegram_id.is_not(None))) or 0)
    new_day = int(await db.scalar(select(func.count()).select_from(User).where(User.telegram_id.is_not(None), User.created_at >= since)) or 0)
    level, detail = status_check(state, bool(settings.bot_token), settings.bot_username or "")
    return {**state, "token_set": bool(settings.bot_token), "token_fingerprint_settings": fingerprint(settings.bot_token),
            "bot_username_setting": settings.bot_username or None, "check": {"status": level, "detail": detail},
            "stats": {"telegram_users": telegram_users, "new_last_day": new_day}}


@router.post("/check")
async def check(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("settings.runtime.read"))):
    """Asks Telegram right now with the current token: who the bot is and where its updates go."""
    try:
        me = await call("getMe")
        hook = await call("getWebhookInfo")
    except TelegramError as exc:
        raise HTTPException(502, f"Telegram: {exc}") from exc
    mismatch = bool(settings.bot_username and me.get("username") and settings.bot_username.lstrip("@").lower() != me["username"].lower())
    return {"bot_id": me.get("id"), "username": me.get("username"), "first_name": me.get("first_name"),
            "can_join_groups": me.get("can_join_groups"), "webhook_url": hook.get("url") or None,
            "pending_updates": hook.get("pending_update_count", 0), "webhook_error": hook.get("last_error_message"),
            "mode": "webhook" if hook.get("url") else "polling", "username_mismatch": mismatch}


@router.post("/webhook/delete")
async def delete_webhook(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("manage_content"))):
    """The bot works with long polling: a webhook left by another deployment takes its updates away."""
    from .main import audit
    try:
        await call("deleteWebhook", {"drop_pending_updates": False})
    except TelegramError as exc:
        raise HTTPException(502, f"Telegram: {exc}") from exc
    await audit(db, "telegram.webhook.deleted", admin.email, "bot", {})
    await db.commit()
    return {"deleted": True}


class CommandIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command: str = Field(min_length=1, max_length=32)
    description: str = Field(min_length=1, max_length=256)

    @field_validator("command")
    @classmethod
    def command_ok(cls, value: str) -> str:
        value = value.strip().lstrip("/").lower()
        if not COMMAND.match(value):
            raise ValueError("Команда: латиница в нижнем регистре, цифры и _, до 32 символов")
        return value


class CommandsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ru: list[CommandIn] = Field(default_factory=list, max_length=100)
    en: list[CommandIn] = Field(default_factory=list, max_length=100)
    uk: list[CommandIn] = Field(default_factory=list, max_length=100)


def default_commands() -> dict:
    return {lang: [{"command": c, "description": d} for c, d in items] for lang, items in DEFAULT_COMMANDS.items()}


@router.get("/commands")
async def get_commands(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("settings.runtime.read"))):
    from .models import TelegramBotState
    row = await db.get(TelegramBotState, 1)
    return {"commands": (row.commands if row and row.commands else default_commands()), "custom": bool(row and row.commands),
            "applied_at": row.commands_applied_at.isoformat() + "Z" if row and row.commands_applied_at else None}


@router.put("/commands")
async def put_commands(payload: CommandsIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("manage_content"))):
    """Saved and applied at once: the Russian list is also the default menu for other languages."""
    from .main import audit
    commands = {lang: [c.model_dump() for c in getattr(payload, lang)] for lang in LANGS}
    for lang, items in commands.items():
        if len({c["command"] for c in items}) != len(items):
            raise HTTPException(422, f"{lang}: команды повторяются")
    try:
        for lang in LANGS:
            body = {"commands": commands[lang]}
            if lang != "ru":
                body["language_code"] = lang
            if commands[lang]:
                await call("setMyCommands", body)
            else:
                await call("deleteMyCommands", {k: v for k, v in body.items() if k != "commands"})
    except TelegramError as exc:
        raise HTTPException(502, f"Telegram: {exc}") from exc
    await report(db, commands=commands, commands_applied_at=datetime.utcnow())
    await audit(db, "telegram.commands.updated", admin.email, "bot", {lang: len(items) for lang, items in commands.items()})
    await db.commit()
    return {"commands": commands, "applied": True}


class TestMessageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chat_id: int | None = None
    text: str = Field(default="Проверка связи: бот магазина работает.", min_length=1, max_length=1000)


@router.post("/test-message")
async def test_message(payload: TestMessageIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("manage_broadcasts"))):
    """A message from the bot to the owner (``ADMIN_TELEGRAM_ID``) or another chat: proves the token and the chat."""
    from .main import audit
    chat = payload.chat_id or settings.admin_telegram_id
    if not chat:
        raise HTTPException(422, "Укажите chat ID или «Telegram ID владельца» в «Настройки без перезапуска → Telegram»")
    try:
        sent = await call("sendMessage", {"chat_id": chat, "text": payload.text})
    except TelegramError as exc:
        raise HTTPException(502, f"Telegram: {exc}") from exc
    await audit(db, "telegram.test_message", admin.email, str(chat), {})
    await db.commit()
    return {"sent": True, "message_id": sent.get("message_id")}


@router.get("/errors")
async def errors(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("ops.diagnostics"))):
    """The bot process's errors from «Журнал ошибок» (APP_PROCESS=bot)."""
    from .models import SystemErrorLog
    rows = (await db.execute(select(SystemErrorLog).where(SystemErrorLog.process == "bot").order_by(SystemErrorLog.last_seen.desc())
                             .limit(50))).scalars().all()
    return {"errors": [{"id": r.id, "level": r.level, "logger": r.logger, "message": r.message[:500], "count": r.count,
                        "resolved": r.resolved, "last_seen": r.last_seen.isoformat() + "Z"} for r in rows]}
