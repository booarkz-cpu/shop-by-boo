"""Telegram account shortcuts; all mutations run through the common cabinet."""
from datetime import datetime
from html import escape
from urllib.parse import urlsplit, urlunsplit
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from aiogram import Router
router=Router()
from .config import settings
from .db import engine
from .models import Payment, Subscription, User

PAGES = {"surveys": "surveys", "account": "overview", "balance": "wallet", "payments": "payments", "gifts": "gifts", "referral": "referral", "support": "support", "devices": "devices"}
TITLES = {"surveys": "Опросы", "account": "Мой кабинет", "balance": "Кошелёк", "payments": "Платежи", "gifts": "Подарки", "referral": "Реферальная программа", "support": "Поддержка", "devices": "Устройства"}


def page_url(page: str) -> str:
    url = urlsplit(settings.mini_app_url or settings.cabinet_url)
    if url.scheme != "https" or not url.netloc:
        return ""
    return urlunsplit((url.scheme, url.netloc, url.path, url.query, page))


@router.message(Command(*PAGES))
async def workspace(message: Message):
    if not message.from_user or message.chat.type != "private":
        await message.answer("Откройте личный чат с ботом для управления аккаунтом.")
        return
    command = (message.text or "").split()[0].split("@")[0].lstrip("/")
    async with AsyncSession(engine, expire_on_commit=False) as db:
        from .account_merge import identity_user
        user = await identity_user(db, "telegram", int(message.from_user.id))
        if not user or user.restricted_at:
            await message.answer("Начните с /start. Если доступ ограничен, обратитесь в поддержку.")
            return
        lines = [f"<b>{TITLES.get(command,'Мой кабинет')}</b>"]
        if command in {"balance", "account"}:
            lines.append(f"Кошелёк: {user.wallet_balance or 0} {escape(settings.default_currency)}")
        if command in {"referral", "account"}:
            lines.append(f"Реферальный баланс: {user.referral_balance or 0} {escape(settings.default_currency)}")
            lines.append(f"Код приглашения: <code>{escape(user.referral_code)}</code>")
        if command == "account":
            sub = await db.scalar(select(Subscription).where(Subscription.user_id==user.id,Subscription.is_primary.is_(True)))
            lines.append(f"Подписка до {sub.expires_at:%d.%m.%Y}" if sub and sub.expires_at and sub.expires_at>datetime.utcnow() else "Активной подписки нет")
        if command == "payments":
            rows = (await db.execute(select(Payment).where(Payment.user_id==user.id).order_by(Payment.id.desc()).limit(5))).scalars().all()
            for p in rows:
                lines.append(f"#{p.id} · {p.amount} {escape(p.currency)} · {escape(p.status)}")
            if not rows: lines.append("Платежей пока нет.")
    keys = list(PAGES) if command == "account" else [command]
    buttons = [[InlineKeyboardButton(text=TITLES[key], web_app=WebAppInfo(url=page_url(PAGES[key])))] for key in keys if page_url(PAGES[key])]
    from .bot_banners import send_section
    await send_section(message, command if command in PAGES else "account", "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None)
