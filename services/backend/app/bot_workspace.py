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
from .bot_texts import t


def title(lang: str, key: str) -> str:
    """Section titles from the texts registry (v28.72.0; «Telegram-бот → Тексты бота»)."""
    return t(lang, f"ws_{key}")


def page_url(page: str) -> str:
    url = urlsplit(settings.mini_app_url or settings.cabinet_url)
    if url.scheme != "https" or not url.netloc:
        return ""
    return urlunsplit((url.scheme, url.netloc, url.path, url.query, page))


@router.message(Command(*PAGES))
async def workspace(message: Message):
    from .bot import _lang
    lang = _lang(message)
    if not message.from_user or message.chat.type != "private":
        await message.answer(t(lang, "private_only"))
        return
    command = (message.text or "").split()[0].split("@")[0].lstrip("/")
    async with AsyncSession(engine, expire_on_commit=False) as db:
        from .account_merge import identity_user
        user = await identity_user(db, "telegram", int(message.from_user.id))
        if not user or user.restricted_at:
            await message.answer(t(lang, "restricted"))
            return
        lines = [f"<b>{title(lang, command if command in PAGES else 'account')}</b>"]
        if command in {"balance", "account"}:
            lines.append(t(lang, "ws_wallet", amount=user.wallet_balance or 0, currency=escape(settings.default_currency)))
        if command in {"referral", "account"}:
            lines.append(t(lang, "ws_referral_balance", amount=user.referral_balance or 0, currency=escape(settings.default_currency)))
            lines.append(t(lang, "ws_referral_code", code=escape(user.referral_code)))
        if command == "account":
            sub = await db.scalar(select(Subscription).where(Subscription.user_id==user.id,Subscription.is_primary.is_(True)))
            lines.append(t(lang, "ws_subscription_until", date=f"{sub.expires_at:%d.%m.%Y}") if sub and sub.expires_at and sub.expires_at>datetime.utcnow() else t(lang, "ws_no_subscription"))
        if command == "payments":
            rows = (await db.execute(select(Payment).where(Payment.user_id==user.id).order_by(Payment.id.desc()).limit(5))).scalars().all()
            for p in rows:
                lines.append(f"#{p.id} · {p.amount} {escape(p.currency)} · {escape(p.status)}")
            if not rows: lines.append(t(lang, "ws_no_payments"))
    keys = list(PAGES) if command == "account" else [command]
    buttons = [[InlineKeyboardButton(text=title(lang, key), web_app=WebAppInfo(url=page_url(PAGES[key])))] for key in keys if page_url(PAGES[key])]
    from .tribute import configured as tribute_ready
    if command == "balance" and tribute_ready() and settings.tribute_donate_link.startswith("https://"):
        # v28.44: a donation through Tribute tops up this wallet (the payer is matched by this Telegram account).
        buttons.append([InlineKeyboardButton(text=t(lang, "ws_tribute"), url=settings.tribute_donate_link)])
    from .bot_banners import send_section
    await send_section(message, command if command in PAGES else "account", "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None)
