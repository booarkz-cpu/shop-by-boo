import asyncio
import logging
import re
from datetime import datetime
from html import escape
from aiogram import Bot,Dispatcher,Router
from aiogram.filters import CommandStart, Command
from aiogram.types import CallbackQuery,Message,InlineKeyboardMarkup,InlineKeyboardButton,PreCheckoutQuery,WebAppInfo
from sqlalchemy import select, text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession
from .sub_proxy import client_url
from .config import settings
from .db import engine
from .bot_banners import send_section
from .models import AppSetting,BotMenuItem,CustomField,Promotion,Advertisement,Plan,Broadcast,User,Subscription,AbuseViolation,NodeAgent

logger = logging.getLogger("remnawave.broadcast")

router=Router()

from .bot_texts import t as _t

# v28.72.0: every text is in bot_texts (ru / en / uk, editable in «Telegram-бот → Тексты бота»).
_ALIASES = {"open": "open_shop", "scope": "promo_scope"}


def _lang(message: Message | None = None) -> str:
    code = ""
    author = getattr(message, "from_user", None) if message is not None else None
    if author is not None and getattr(author, "language_code", None):
        code = author.language_code
    code = (code or settings.default_language or "ru").lower()
    if code.startswith("uk") or code.startswith("ua"): return "uk"
    return "en" if code.startswith("en") else "ru"

def _tr(lang: str, key: str, **kwargs) -> str:
    return _t(lang, _ALIASES.get(key, key), **kwargs)


def _qlang(query) -> str:
    """The language of a callback's author (CallbackQuery has from_user like Message)."""
    return _lang(query)

async def get_bot_config():
    async with AsyncSession(engine,expire_on_commit=False) as db:
        public_keys = {"bot_name", "bot_start_image"}
        vals = {
            row.key: row.value
            for row in (
                await db.execute(select(AppSetting).where(AppSetting.key.in_(public_keys)))
            ).scalars().all()
        }
        menu=(await db.execute(select(BotMenuItem).where(BotMenuItem.enabled.is_(True)).order_by(BotMenuItem.sort_order,BotMenuItem.id))).scalars().all()
        fields=(await db.execute(select(CustomField).where(CustomField.enabled.is_(True)).order_by(CustomField.sort_order,CustomField.id))).scalars().all()
        now=datetime.utcnow()
        ads=(await db.execute(select(Advertisement).where(Advertisement.enabled.is_(True)).order_by(Advertisement.sort_order,Advertisement.id))).scalars().all()
        ads=[a for a in ads if (not a.starts_at or now>=a.starts_at) and (not a.ends_at or now<=a.ends_at)]
        promos=(await db.execute(select(Promotion).where(Promotion.enabled.is_(True)).order_by(Promotion.id.desc()))).scalars().all()
        promos=[p for p in promos if (not p.starts_at or now>=p.starts_at) and (not p.ends_at or now<=p.ends_at)]
        plans=(await db.execute(select(Plan).where(Plan.enabled.is_(True)).order_by(Plan.id))).scalars().all()
        return vals,menu,fields,ads,promos,plans

def promo_text(promos,plans,lang="ru"):
    chunks=[]
    discount_word = _tr(lang, "promo_off")
    for p in promos:
        scope="" if not p.plan_ids else _tr(lang, "scope")
        chunks.append(f"🎁 <b>{escape(p.name)}</b> — {discount_word} {p.value:g}{'%' if p.kind=='percent' else ' ₽'}{scope}.\n{escape(p.description)}".strip())
    return "\n\n".join(chunks)


def broadcast_recipient_query(target: str, now: datetime):
    """Users with a Telegram id. Active joins subscriptions, so the query is distinct."""
    stmt = select(User.id, User.telegram_id).where(User.telegram_id.is_not(None))
    if target == "active":
        stmt = stmt.join(Subscription, Subscription.user_id == User.id).where(Subscription.expires_at > now)
    elif target == "inactive":
        active_ids = select(Subscription.user_id).where(Subscription.expires_at > now)
        stmt = stmt.where(~User.id.in_(active_ids))
    return stmt.distinct().order_by(User.id)


def _private(message) -> bool:
    """Web App buttons are accepted by Telegram only in private chats (BUTTON_TYPE_INVALID otherwise)."""
    return getattr(getattr(message, "chat", None), "type", "private") == "private"


PROMO_RE = re.compile(r"[A-Z0-9_-]{2,64}")


async def _telegram_post(client, method: str, payload: dict):
    """Bot API call honoring flood control: on 429 wait ``retry_after`` and try again (3 attempts)."""
    url = f"https://api.telegram.org/bot{settings.bot_token}/{method}"
    response = None
    for attempt in range(3):
        response = await client.post(url, json=payload)
        if response.status_code != 429 or attempt == 2:
            return response
        wait = 1.0
        try:
            wait = float(response.json().get("parameters", {}).get("retry_after", 1))
        except Exception:
            wait = 1.0
        await asyncio.sleep(min(max(wait, 0.5), 30))
    return response


async def _mark_broadcast_failed(broadcast_id: int) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as db:
        row = await db.get(Broadcast, broadcast_id)
        if row and row.status == "sending":
            row.status = "failed"
            row.finished_at = datetime.utcnow()
            await db.commit()


async def broadcast_worker(bot: Bot):
    import httpx
    while True:
        claimed = None
        try:
            async with AsyncSession(engine, expire_on_commit=False) as db:
                row = (await db.execute(sql_text("UPDATE broadcasts SET status='sending' WHERE id=(SELECT id FROM broadcasts WHERE status='queued' ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING id"))).first()
                await db.commit()
                if not row:
                    await asyncio.sleep(2)
                    continue
                claimed = int(row[0])
                item = await db.get(Broadcast, claimed)
                if not item:
                    claimed = None
                    continue
                now = datetime.utcnow()
                recipients = (await db.execute(broadcast_recipient_query(item.target, now))).all()
                sent = int(item.sent_count or 0)
                failed = int(item.failed_count or 0)
                start = sent + failed
                async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
                    for index, recipient in enumerate(recipients):
                        if index < start:
                            continue
                        try:
                            markup = {"inline_keyboard": [[{"text": item.button_text, "url": item.button_url}]]} if item.button_text and item.button_url else None
                            if item.image_url:
                                payload = {"chat_id": recipient.telegram_id, "photo": item.image_url, "caption": item.text, "parse_mode": "HTML"}
                                if markup:
                                    payload["reply_markup"] = markup
                                response = await _telegram_post(client, "sendPhoto", payload)
                            else:
                                payload = {"chat_id": recipient.telegram_id, "text": item.text, "parse_mode": "HTML"}
                                if markup:
                                    payload["reply_markup"] = markup
                                response = await _telegram_post(client, "sendMessage", payload)
                            if response is not None and response.is_success:
                                sent += 1
                            else:
                                failed += 1
                        except Exception:
                            logger.exception("broadcast delivery failed for id %s", claimed)
                            failed += 1
                        item.sent_count = sent
                        item.failed_count = failed
                        await db.commit()
                        await asyncio.sleep(0.04)
                item.status = "completed"
                item.finished_at = datetime.utcnow()
                await db.commit()
                claimed = None
        except Exception:
            logger.exception("broadcast worker failed")
            if claimed is not None:
                try:
                    await _mark_broadcast_failed(claimed)
                except Exception:
                    logger.exception("broadcast failure status was not saved")
            await asyncio.sleep(5)

async def menu_answer(send,*args,**kwargs):
    from aiogram.exceptions import TelegramBadRequest
    from .menu_tree import without_custom_icons
    try:return await send(*args,**kwargs)
    except TelegramBadRequest as exc:
        markup=kwargs.get('reply_markup')
        if not markup or 'emoji' not in str(exc).lower():raise
        kwargs['reply_markup']=without_custom_icons(markup)
        return await send(*args,**kwargs)


@router.callback_query(lambda query:bool(query.data and (query.data.startswith('menu:') or query.data.startswith('menu-field:'))))
async def menu_callback(query:CallbackQuery):
    if not query.message or query.message.chat.type!='private' or query.message.chat.id!=query.from_user.id:
        await query.answer();return
    from .menu_tree import telegram_keyboard,visible_children
    vals,menu,fields,*_=await get_bot_config()
    try:item_id=int(query.data.split(':',1)[1])
    except (ValueError,IndexError):await query.answer();return
    row=next((r for r in menu if r.id==item_id),None)
    if query.data.startswith('menu-field:'):
        if not row or row.item_type!='field' or row not in visible_children(menu,row.parent_id):await query.answer(_tr(_qlang(query),'menu_button_gone'));return
        field=next((f for f in fields if f.key==row.action and f.enabled),None)
        if not field:await query.answer(_tr(_qlang(query),'menu_field_gone'));return
        await query.answer();await send_section(query.message,f'menu-{row.id}',f'<b>{escape(field.label)}</b>\n{escape(field.value)}');return
    if item_id and (not row or row.item_type!='folder' or not visible_children(menu,item_id)):
        await query.answer(_tr(_qlang(query),'menu_empty'));return
    markup=telegram_keyboard(menu,fields,item_id or None)
    # Navigation edits the same message (banner + text + buttons) instead of posting new ones.
    await query.answer();await send_section(query.message,f'menu-{row.id}' if row else 'menu',escape(row.title) if row else _tr(_qlang(query),'menu_title'),markup,fallback='menu',edit=True)


async def send_app_login(message:Message):
    """One-use button that opens the Android/iOS app already signed in."""
    if not message.from_user:
        return
    from .account_merge import identity_user
    from .app_login import APP_CODE_MINUTES, issue_app_code, open_url
    async with AsyncSession(engine, expire_on_commit=False) as db:
        user=await identity_user(db,"telegram",int(message.from_user.id))
        if not user:
            await message.answer(_tr(_lang(message), "start_first"))
            return
        code=await issue_app_code(db,user.id)
        await db.commit()
    lang=_lang(message)
    text=_tr(lang,"app_login",minutes=APP_CODE_MINUTES)
    markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=_tr(lang,"app_open"),url=open_url(code))]])
    await message.answer(text,reply_markup=markup,parse_mode="HTML")


@router.message(Command("app"))
async def app_command(message:Message):
    if not _private(message):
        await message.answer(_tr(_lang(message), "private_only"))
        return
    await send_app_login(message)


@router.message(CommandStart())
async def start(message:Message):
    if getattr(getattr(message,"chat",None),"type","private")!="private":
        await message.answer(_tr(_lang(message), "private_only"))
        return
    parts=(message.text or "").split(maxsplit=1)
    incoming=parts[1].strip().split()[0] if len(parts)>1 else ""
    # A payload may combine parts with «__»: ref_<code>__src_<source> (referral and ad source in one link).
    ref_part=next((p for p in incoming.split("__") if p.lower().startswith("ref_")),"")

    # /start is also the canonical Telegram-to-shop binding point. Without this,
    # a user can interact with the bot but remain invisible to broadcasts and
    # Telegram-based account lookups until the Mini App is opened.
    if message.from_user:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            tg_id = int(message.from_user.id)
            from .account_merge import identity_user
            user = await identity_user(db, "telegram", tg_id)
            created_now = not user
            if user:
                changed = False
                username = message.from_user.username or user.username
                if user.telegram_id == tg_id and username and username != user.username:
                    user.username = username
                    changed = True
                if changed:
                    await db.commit()
            else:
                from fastapi import HTTPException as _Refused
                from .moderation import invite_from_start, registration_check
                try:
                    await registration_check(db, telegram_id=tg_id, invite=invite_from_start(incoming))
                except _Refused as refused:
                    await message.answer(str(refused.detail))
                    return
                user=User(
                    telegram_id=tg_id,
                    username=message.from_user.username,
                    referral_code=__import__("secrets").token_urlsafe(8).upper(),
                )
                db.add(user)
                await db.commit()
            from .channel_gate import missing as missing_channels
            lacking = await missing_channels(tg_id, "all")
            if lacking:
                rows = [[InlineKeyboardButton(text=c["title"], url=c["url"])] for c in lacking if c.get("url")]
                await send_section(message, "channels", _tr(_lang(message), "channels_required", channels=", ".join(escape(c["title"]) for c in lacking)),
                                   InlineKeyboardMarkup(inline_keyboard=rows) if rows else None, fallback="start")
                return
            from .economics import remember_source, source_from_start
            from .ad_postbacks import click_from_start, remember_click
            from .activity_log import record as record_activity
            record_activity(db, user.id, "bot", "start", {"payload": incoming[:60]} if incoming else None)
            await remember_click(db, user.id, click_from_start(incoming))
            await remember_source(db, user, source_from_start(incoming))
            await db.commit()
            if created_now:
                from .ad_postbacks import fire as fire_conversion
                fire_conversion(user.id, "registration")
                from .pinned_message import on_start as pinned_on_start
                await pinned_on_start(db, user.id, tg_id)
            if ref_part and not user.referred_by_id:
                from .referrals import bind_referrer
                from fastapi import HTTPException
                user=(await db.execute(select(User).where(User.id==user.id).with_for_update())).scalar_one()
                try:
                    await bind_referrer(db,user,ref_part[4:])
                    await db.commit()
                except HTTPException:
                    await db.rollback()


    if incoming.lower()=="app_login":
        await send_app_login(message)
        return

    vals,menu,fields,ads,promos,plans=await get_bot_config()
    lang=_lang(message)
    start_arg=""
    parts=(message.text or "").split(maxsplit=1)
    if len(parts)>1:
        start_arg=parts[1].strip().split()[0]
    gift_code=start_arg.upper() if start_arg.upper().startswith("GIFT_") else ""
    family_code=start_arg[7:] if start_arg.startswith("family_") and re.fullmatch(r"[A-Za-z0-9]{6,32}",start_arg[7:]) else ""
    from .menu_tree import telegram_keyboard,visible_children
    buttons=telegram_keyboard(menu,fields).inline_keyboard;field_text=[]
    for m in visible_children(menu):
        if m.item_type=='field':
            f=next((x for x in fields if x.key==m.action),None)
            if f:field_text.append(f"<b>{escape(f.label)}</b>\n{escape(f.value)}")
    shop_url=settings.mini_app_url
    if gift_code:
        join="&" if "?" in shop_url else "?"
        shop_url=f"{shop_url}{join}gift={gift_code}"
    if family_code:
        join="&" if "?" in shop_url else "?"
        shop_url=f"{shop_url}{join}family={family_code}"
    if not buttons: buttons=[[InlineKeyboardButton(text=_tr(lang,"open"),web_app=WebAppInfo(url=shop_url))]]
    elif gift_code or family_code:
        buttons.append([InlineKeyboardButton(text=_tr(lang,"open"),web_app=WebAppInfo(url=shop_url))])
    name=escape(vals.get("bot_name") or _tr(lang,"shop_name")); text=_tr(lang,"welcome",name=name)
    pt=promo_text(promos,plans,lang)
    if gift_code: text += "\n\n"+_tr(lang,"gift_ready",code=escape(gift_code))
    if family_code: text += "\n\n"+_tr(lang,"family_invite")
    if pt: text += "\n\n"+pt
    price_lines=[]
    for plan in plans:
        promo_obj=next((x for x in promos if not x.plan_ids or plan.id in x.plan_ids),None)
        price=float(plan.price)
        if promo_obj:
            discount=price*float(promo_obj.value)/100 if promo_obj.kind=="percent" else min(price,float(promo_obj.value))
            price_lines.append(f"• {escape(plan.name)}: <s>{price:.2f} ₽</s> <b>{price-discount:.2f} ₽</b>")
        else: price_lines.append(f"• {escape(plan.name)}: <b>{price:.2f} ₽</b>")
    if price_lines: text += "\n\n💳 <b>"+_tr(lang,"prices")+"</b>\n"+"\n".join(price_lines)
    for a in ads:
        text += f"\n\n📣 <b>{escape(a.title)}</b>\n{escape(a.text)}"
        if a.button_text and a.button_url: buttons.append([InlineKeyboardButton(text=a.button_text,url=a.button_url)])
    if field_text: text += "\n\n"+"\n\n".join(field_text)
    markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    # Banner: own image from the admin panel, the legacy /start image or the default corgi Lusi.
    await send_section(message,"start",text,markup)

# ---------------------------------------------------------------- documents (v28.29.0)

class _Texts(dict):
    """INFO_EMPTY / INFO_TITLE by language, from the texts registry."""
    def __init__(self, key):
        super().__init__()
        self.key = key

    def __getitem__(self, lang):
        return _tr(lang, self.key)

    def get(self, lang, default=None):
        return _tr(lang, self.key)


INFO_EMPTY = _Texts("info_empty")
INFO_TITLE = _Texts("info_title")


async def show_info(message, kind: str, lang: str, *, edit: bool = False):
    """A document from «Контент → Документы»: its banner, then the text (split to fit Telegram)."""
    from .info_pages import load, localized, split_message, telegram_html
    async with AsyncSession(engine, expire_on_commit=False) as db:
        page = localized(kind, await load(db, kind), lang)
    if not page:
        await message.answer(INFO_EMPTY.get(lang, INFO_EMPTY["ru"]))
        return
    parts = split_message(telegram_html(page))
    back = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="←", callback_data="info:menu")]])
    await send_section(message, kind, parts[0], back if len(parts) == 1 else None, fallback="info", edit=edit)
    for i, part in enumerate(parts[1:], start=2):
        await message.answer(part, parse_mode="HTML", reply_markup=back if i == len(parts) else None)


async def info_menu(message, lang: str, *, edit: bool = False):
    from .info_pages import published
    async with AsyncSession(engine, expire_on_commit=False) as db:
        pages = await published(db, lang)
    if not pages:
        await message.answer(INFO_EMPTY.get(lang, INFO_EMPTY["ru"]))
        return
    icons = {"faq": "❓", "rules": "📋", "privacy": "🔒", "offer": "📄"}
    markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"{icons[p['kind']]} {p['title']}", callback_data=f"info:{p['kind']}")] for p in pages])
    await send_section(message, "info", INFO_TITLE.get(lang, INFO_TITLE["ru"]), markup, edit=edit)


@router.message(Command("info"))
async def info_command(message: Message):
    await info_menu(message, _lang(message))


@router.message(Command("faq", "rules", "privacy", "offer"))
async def info_page_command(message: Message):
    kind = (message.text or "/").split()[0].lstrip("/").split("@")[0].lower()
    await show_info(message, kind, _lang(message))


@router.callback_query(lambda query: bool(query.data and query.data.startswith("info:")))
async def info_callback(query: CallbackQuery):
    from .info_pages import KINDS
    kind = query.data.split(":", 1)[1]
    await query.answer()
    if not query.message:
        return
    lang = _lang(None)
    code = (query.from_user.language_code or "").lower() if query.from_user else ""
    if code:
        lang = "uk" if code.startswith(("uk", "ua")) else "en" if code.startswith("en") else "ru"
    if kind == "menu":
        await info_menu(query.message, lang, edit=True)
    elif kind in KINDS:
        await show_info(query.message, kind, lang, edit=True)


@router.message(Command("buy"))
async def buy(message: Message):
    if not _private(message):
        await message.answer(_tr(_lang(message), "private_only"))
        return
    lang = _lang(message)
    _, _, _, _, _, plans = await get_bot_config()
    if not plans:
        await message.answer(_tr(lang, "plans_empty"))
        return
    currency = escape(settings.default_currency or "RUB")
    lines = [_tr(lang, "plan_line", plan=escape(p.name), price=f"{p.price:.2f}", currency=currency, days=p.duration_days) for p in plans]
    url = settings.mini_app_url
    await send_section(message, "buy", _tr(lang, "plans_title") + "\n" + "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=_tr(lang, "open"), web_app=WebAppInfo(url=url))]]))

@router.message(Command("subscription"))
async def subscription(message: Message):
    if getattr(getattr(message,"chat",None),"type","private")!="private":
        await message.answer(_tr(_lang(message), "private_only"))
        return
    lang = _lang(message)
    if not message.from_user:
        return
    async with AsyncSession(engine, expire_on_commit=False) as db:
        from .account_merge import identity_user
        user = await identity_user(db, "telegram", int(message.from_user.id))
        sub = (await db.execute(select(Subscription).where(Subscription.user_id == user.id,Subscription.is_primary.is_(True)))).scalar_one_or_none() if user else None
        from .sub_proxy import config as proxy_config
        await proxy_config(db)  # the bot runs in its own process: read the proxy settings for client_url
    if not sub or not sub.subscription_url:
        await send_section(message, "subscription", _tr(lang, "no_subscription"), InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=_tr(lang,"open"), web_app=WebAppInfo(url=settings.mini_app_url))]]))
        return
    await send_section(message, "subscription", _tr(lang, "your_subscription") + "\n" + escape(client_url(sub.subscription_url) or ""))

@router.message(Command("contest"))
async def contest_command(message: Message):
    """Referral contest: the leaderboard and the customer's own place (referral_contests.py)."""
    if not message.from_user or getattr(getattr(message, "chat", None), "type", "private") != "private":
        return
    async with AsyncSession(engine, expire_on_commit=False) as db:
        from .account_merge import identity_user
        from .referral_contests import current, leaderboard, public
        user = await identity_user(db, "telegram", int(message.from_user.id))
        contest = await current(db)
        view = public(contest, await leaderboard(db, contest, 100), user.id if user else None) if contest else None
    lang = _lang(message)
    if not view:
        await send_section(message, "contest", _tr(lang, "contest_none"), fallback="referral")
        return
    lines = [_tr(lang, "contest_title", title=escape(view["title"]), date=view["ends_at"][:10]), ""]
    lines += [f"{r['place']}. {escape(r['name'])} — {r['score']}" for r in view["top"]]
    lines += ["", _tr(lang, "contest_place", place=view["me"]["place"], score=view["me"]["score"]) if view["me"] else _tr(lang, "contest_join")]
    await send_section(message, "contest", "\n".join(lines), fallback="referral")


@router.message(Command("status"))
async def status_command(message: Message):
    """v28.47 «Состояние сервиса»: regions and payments now, and a button to get outage news."""
    if not message.from_user or getattr(getattr(message, "chat", None), "type", "private") != "private":
        return
    from .models import StatusSubscriber
    from .status_page import build
    async with AsyncSession(engine, expire_on_commit=False) as db:
        from .account_merge import identity_user
        user = await identity_user(db, "telegram", int(message.from_user.id))
        page = await build(db)
        on = bool(user and await db.scalar(select(StatusSubscriber.id).where(StatusSubscriber.user_id == user.id)))
    lang = _lang(message)
    head = _tr(lang, {"operational": "status_operational", "degraded": "status_degraded", "outage": "status_outage"}.get(page["overall"], "status_unknown"))
    lines = [f"<b>{head}</b>"]
    lines += [f"{r['country']}: {r['label']} ({r['online']}/{r['total']})" for r in page["regions"][:12]]
    lines += [f"{c['name']}: {c['label']}" for c in page["components"][:6]]
    opened = [i for i in page["incidents"] if i["status"] == "open"][:3]
    if opened:
        lines.append("\n" + _tr(lang, "status_now", incidents="; ".join(escape(i["title"]) for i in opened)))
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=_tr(lang, "status_notify_off") if on else _tr(lang, "status_notify_on"),
                                                                           callback_data="status:off" if on else "status:on")]]) if user else None
    await message.answer("\n".join(lines), parse_mode="HTML", reply_markup=keyboard)


@router.callback_query(lambda query: bool(query.data and query.data in ("status:on", "status:off")))
async def status_toggle(query: CallbackQuery):
    from sqlalchemy import delete
    from .models import StatusSubscriber
    async with AsyncSession(engine, expire_on_commit=False) as db:
        from .account_merge import identity_user
        user = await identity_user(db, "telegram", int(query.from_user.id))
        if not user:
            await query.answer(_tr(_qlang(query), "start_first"))
            return
        if query.data == "status:on":
            if not await db.scalar(select(StatusSubscriber.id).where(StatusSubscriber.user_id == user.id)):
                db.add(StatusSubscriber(user_id=user.id))
        else:
            await db.execute(delete(StatusSubscriber).where(StatusSubscriber.user_id == user.id))
        await db.commit()
    await query.answer(_tr(_qlang(query), "status_subscribed" if query.data == "status:on" else "status_unsubscribed"))


@router.callback_query(lambda query: bool(query.data and (query.data.startswith("csat:") or query.data.startswith("nps:"))))
async def feedback_answer(query: CallbackQuery):
    """v28.52: a support rating (csat:<ticket>:<1-5>) or an NPS answer (nps:<wave>:<0-10>) from the inline buttons."""
    from fastapi import HTTPException
    from .feedback import record
    kind, ref, score = (query.data.split(":") + ["", ""])[:3]
    async with AsyncSession(engine, expire_on_commit=False) as db:
        from .account_merge import identity_user
        user = await identity_user(db, "telegram", int(query.from_user.id))
        if not user:
            await query.answer(_tr(_qlang(query), "start_first"))
            return
        try:
            if kind == "csat":
                await record(db, user.id, "csat", int(score), ticket_id=int(ref))
            else:
                await record(db, user.id, "nps", int(score), wave=ref)
        except (HTTPException, ValueError):
            await query.answer(_tr(_qlang(query), "feedback_failed"))
            return
    await query.answer(_tr(_qlang(query), "feedback_thanks"))
    if query.message:
        low = (kind == "csat" and int(score) <= 3) or (kind == "nps" and int(score) <= 6)
        await query.message.answer(_tr(_qlang(query), "feedback_low" if low else "feedback_high"))


@router.message(Command("filter"))
async def filter_command(message: Message):
    """v28.54 «Фильтр»: ad blocking or the children's mode on the subscription."""
    if not message.from_user or getattr(getattr(message, "chat", None), "type", "private") != "private":
        return
    from .dns_filter import view
    from .subscriptions import owned
    async with AsyncSession(engine, expire_on_commit=False) as db:
        from .account_merge import identity_user
        user = await identity_user(db, "telegram", int(message.from_user.id))
        v = await view(db, await owned(db, user.id)) if user else None
    lang = _lang(message)
    if not v or not v["enabled"]:
        await message.answer(_tr(lang, "filter_unavailable"))
        return
    current = next((m["title"] for m in v["modes"] if m["key"] == v["mode"]), _tr(lang, "filter_none"))
    rows = [[InlineKeyboardButton(text=("✅ " if not v["mode"] else "") + _tr(lang, "filter_none"), callback_data="filter:off")]]
    rows += [[InlineKeyboardButton(text=("✅ " if v["mode"] == m["key"] else "") + m["title"], callback_data=f"filter:{m['key']}")] for m in v["modes"]]
    await message.answer(_tr(lang, "filter_current", mode=current), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(lambda query: bool(query.data and query.data.startswith("filter:")))
async def filter_choose(query: CallbackQuery):
    from fastapi import HTTPException
    from .dns_filter import set_filter
    from .subscriptions import is_family_subscription, owned
    mode = query.data.split(":", 1)[1]
    mode = "" if mode == "off" else mode
    async with AsyncSession(engine, expire_on_commit=False) as db:
        from .account_merge import identity_user
        user = await identity_user(db, "telegram", int(query.from_user.id))
        sub = await owned(db, user.id, lock=True) if user else None
        if not sub or await is_family_subscription(db, sub.id):
            await query.answer(_tr(_qlang(query), "filter_family" if sub else "subscription_not_found"), show_alert=True)
            return
        try:
            await set_filter(db, sub, mode, "bot")
        except HTTPException as exc:
            await query.answer(str(exc.detail)[:190], show_alert=True)
            return
    await query.answer(_tr(_qlang(query), "filter_on" if mode else "filter_off"))


@router.message(Command("level"))
async def level_command(message: Message):
    """v28.51 «Уровни лояльности»: the customer's level, its perks and what is left to the next one."""
    if not message.from_user or getattr(getattr(message, "chat", None), "type", "private") != "private":
        return
    from .loyalty import current
    async with AsyncSession(engine, expire_on_commit=False) as db:
        from .account_merge import identity_user
        user = await identity_user(db, "telegram", int(message.from_user.id))
        lv = await current(db, user.id) if user else None
    lang = _lang(message)
    if not lv:
        await message.answer(_tr(lang, "level_off"))
        return

    def perks(x):
        items = [_tr(lang, "level_cashback", percent=x["cashback_percent"]) if x.get("cashback_percent") else "",
                 _tr(lang, "level_discount", percent=x["discount_percent"]) if x.get("discount_percent") else ""]
        return ", ".join(i for i in items if i) or "—"
    lines = [_tr(lang, "level_current", level=escape(lv["title"])), perks(lv)]
    if lv["next"]:
        lines.append("\n" + _tr(lang, "level_next", level=escape(lv["next"]["title"]), need=escape(lv["next"]["need"] or _tr(lang, "level_need_little")),
                                 perks=perks(lv["next"]))
                     + (_tr(lang, "level_bonus_days", days=lv["next"]["bonus_days"]) if lv["next"].get("bonus_days") else "") + ".")
    else:
        lines.append("\n" + _tr(lang, "level_top"))
    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("freeze"))
async def freeze_command(message: Message):
    """v28.50 «Заморозка подписки»: pause the paid subscription (VPN off, paid days kept) or thaw it."""
    if not message.from_user or getattr(getattr(message, "chat", None), "type", "private") != "private":
        return
    from .subscription_freeze import status_for
    from .subscriptions import owned
    async with AsyncSession(engine, expire_on_commit=False) as db:
        from .account_merge import identity_user
        user = await identity_user(db, "telegram", int(message.from_user.id))
        sub = await owned(db, user.id) if user else None
        s = await status_for(db, user, sub) if user else None
    lang = _lang(message)
    if not s or not s["enabled"] or not sub:
        await message.answer(_tr(lang, "freeze_unavailable"))
        return
    if s["frozen"]:
        await message.answer(_tr(lang, "freeze_frozen", date=s["frozen"]["until"][:10]),
                             reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=_tr(lang, "freeze_thaw_button"), callback_data="freeze:thaw")]]))
        return
    if s["reason"]:
        await message.answer(s["reason"])
        return
    options = sorted({d for d in (s["min_days"], 7, 14, 30, s["max_days"]) if s["min_days"] <= d <= min(s["max_days"], s["days_left"])})
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=_tr(lang, "freeze_days_button", days=d), callback_data=f"freeze:{d}") for d in options[:5]]])
    await message.answer(_tr(lang, "freeze_offer", days=s["days_left"]), reply_markup=keyboard)


@router.callback_query(lambda query: bool(query.data and query.data.startswith("freeze:")))
async def freeze_action(query: CallbackQuery):
    from fastapi import HTTPException
    from .subscription_freeze import freeze, thaw
    from .subscriptions import owned
    async with AsyncSession(engine, expire_on_commit=False) as db:
        from .account_merge import identity_user
        user = await identity_user(db, "telegram", int(query.from_user.id))
        sub = await owned(db, user.id, lock=True) if user else None
        lang = _qlang(query)
        if not sub:
            await query.answer(_tr(lang, "subscription_not_found"))
            return
        value = query.data.split(":", 1)[1]
        try:
            if value == "thaw":
                if not await thaw(db, sub, commit=True):
                    await query.answer(_tr(lang, "freeze_not_frozen"))
                    return
                text = _tr(lang, "freeze_thawed", date=f"{sub.expires_at:%d.%m.%Y}")
            else:
                result = await freeze(db, user, sub, int(value))
                text = _tr(lang, "freeze_done", date=result["until"][:10])
        except HTTPException as exc:
            await query.answer(str(exc.detail)[:190], show_alert=True)
            return
    await query.answer()
    if query.message:
        await query.message.answer(text)


@router.message(Command("keys"))
async def keys_command(message: Message):
    """«Ключи подключения» (wg_pool.py): every server of the subscription as its own link."""
    if not message.from_user or getattr(getattr(message, "chat", None), "type", "private") != "private":
        return
    from urllib.parse import unquote
    async with AsyncSession(engine, expire_on_commit=False) as db:
        from .account_merge import identity_user
        from .sub_proxy import short_uuid_of
        user = await identity_user(db, "telegram", int(message.from_user.id))
        sub = (await db.execute(select(Subscription).where(Subscription.user_id == user.id, Subscription.is_primary.is_(True)))).scalar_one_or_none() if user else None
    short = short_uuid_of(sub.subscription_url) if sub and sub.expires_at and sub.expires_at > datetime.utcnow() else ""
    lang = _lang(message)
    if not short:
        await message.answer(_tr(lang, "no_subscription"))
        return
    try:
        from .remnawave import RemnawaveClient
        info = await RemnawaveClient()._request("GET", f"/api/subscriptions/by-short-uuid/{short}")
    except Exception:  # noqa: BLE001 — the panel is unavailable
        await message.answer(_tr(lang, "keys_unavailable"))
        return
    links = [x for x in (info or {}).get("links") or [] if isinstance(x, str) and "://" in x and "@0.0.0.0:1" not in x][:8]
    if not links:
        await message.answer(_tr(lang, "keys_empty"))
        return
    lines = [_tr(lang, "keys_title")]
    lines += [f"{escape(unquote(x.split('#', 1)[1]) if '#' in x else x.split('://')[0])}\n<code>{escape(x)}</code>" for x in links]
    from .masque_panel import customer_items          # MASQUE has its own subscription (the panel does not know it)
    async with AsyncSession(engine, expire_on_commit=False) as db:
        lines += [_tr(lang, "keys_masque", name=escape(i["name"]), url=escape(i["url"])) for i in (await customer_items(db, user.id))[0]
                  if not i["over_limit"]]
    text = "\n\n".join(lines)
    # A photo caption holds 1024 characters: long key lists go as a plain message.
    if len(text) > 1000:
        await message.answer(text[:4000], parse_mode="HTML")
    else:
        await send_section(message, "connection", text, fallback="subscription")


@router.message(Command("stats"))
async def stats_command(message: Message):
    """«Моя статистика» (customer_insights.py)."""
    if not message.from_user or getattr(getattr(message, "chat", None), "type", "private") != "private":
        return
    async with AsyncSession(engine, expire_on_commit=False) as db:
        from .account_merge import identity_user
        from .customer_insights import stats
        user = await identity_user(db, "telegram", int(message.from_user.id))
        data = await stats(db, user) if user else None
    lang = _lang(message)
    if not data:
        await message.answer(_tr(lang, "start_first"))
        return
    of, gb = _tr(lang, "of"), _tr(lang, "gb")
    traffic = f"{data['traffic_used_gb']} {gb}" + (f" {of} {data['traffic_limit_gb']}" if data["traffic_limit_gb"] else "") if data["traffic_used_gb"] is not None else "—"
    devices = f"{data['devices']}" + (f" {of} {data['device_limit']}" if data["device_limit"] else "")
    await send_section(message, "stats", _tr(lang, "stats", days_with_us=data["days_with_us"], days_paid=data["days_paid"], traffic=traffic, devices=devices),
                       fallback="account")


@router.message(Command("promo"))
async def promo(message:Message):
    if not _private(message):
        await message.answer(_tr(_lang(message), "private_only"))
        return
    lang=_lang(message)
    code=(message.text or "").split(maxsplit=1)
    if len(code)<2 or not PROMO_RE.fullmatch(code[1].strip().upper()):
        await message.answer(_tr(lang,"promo_usage"))
        return
    # Deep-link into Mini App with the code; server validates it again before payment.
    from urllib.parse import quote
    promo_code=code[1].strip().upper()
    await send_section(message,"promo",_tr(lang,"promo_ready",code=escape(promo_code)),InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=_tr(lang,"open"),web_app=WebAppInfo(url=settings.mini_app_url+"?promo="+quote(promo_code)))] ]))

@router.pre_checkout_query()
async def stars_pre_checkout(query: PreCheckoutQuery):
    """Telegram Stars: accept only a pending order with the same amount (10 s deadline)."""
    from .telegram_stars import check_pre_checkout
    try:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            error = await check_pre_checkout(db, order_id=query.invoice_payload, currency=query.currency, total=query.total_amount, telegram_id=query.from_user.id)
    except Exception:
        logger.exception("Stars pre-checkout check failed")
        error = _tr(_lang(query), "stars_check_failed")
    await query.answer(ok=error is None, error_message=error)


@router.message(lambda message: bool(getattr(message, "successful_payment", None)))
async def stars_paid(message: Message):
    from .telegram_stars import record_successful_payment
    paid = message.successful_payment
    try:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            expires = getattr(paid, "subscription_expiration_date", None)
            await record_successful_payment(db, order_id=paid.invoice_payload, currency=paid.currency, total=paid.total_amount,
                                            telegram_id=message.from_user.id, charge_id=paid.telegram_payment_charge_id,
                                            is_recurring=bool(getattr(paid, "is_recurring", False)),
                                            is_first_recurring=bool(getattr(paid, "is_first_recurring", False)),
                                            period_end=datetime.utcfromtimestamp(expires) if isinstance(expires, int) else None)
        await message.answer(_tr(_lang(message), "stars_paid_subscription" if paid.invoice_payload.startswith("starsub-") else "stars_paid_balance"))
    except Exception:
        # The charge id is in the update log; reconciliation by an operator uses it.
        logger.exception("Stars payment %s was not recorded", paid.telegram_payment_charge_id)
        await message.answer(_tr(_lang(message), "stars_delayed"))


@router.message(Command("ops"))
async def ops(message: Message):
    lang = _lang(message)
    if not message.from_user or int(message.from_user.id) != int(settings.admin_telegram_id or 0):
        await message.answer(_tr(lang, "ops_denied"))
        return
    from datetime import timedelta
    from sqlalchemy import func
    async with AsyncSession(engine, expire_on_commit=False) as db:
        violations = int(await db.scalar(select(func.count()).select_from(AbuseViolation).where(AbuseViolation.status == "open")) or 0)
        cutoff = datetime.utcnow() - timedelta(minutes=5)
        agents = int(await db.scalar(select(func.count()).select_from(NodeAgent).where(NodeAgent.last_seen_at.is_not(None), NodeAgent.last_seen_at >= cutoff)) or 0)
    url = f"https://{settings.admin_domain}" if settings.admin_domain and settings.admin_domain != "localhost" else settings.public_base_url
    buttons = [[InlineKeyboardButton(text=_tr(lang, "ops_panel"), url=url)]]
    await message.answer(_tr(lang, "ops_status", violations=violations, agents=agents, url=escape(url)), reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")

POLL_CHECK = 60   # seconds between getMe calls (the connection check «Состояние системы» shows)
TOKEN_CHECK = 15  # seconds between looks at the runtime setting BOT_TOKEN


async def _report(**fields) -> None:
    from .telegram_bot import report
    try:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            await report(db, **fields)
    except Exception as exc:  # noqa: BLE001 — a database outage must not stop the bot
        logger.warning("bot state not saved: %s", exc)


async def _refresh_texts() -> None:
    """The owner's text overrides, at most once a minute (bot_texts.refresh)."""
    from .bot_texts import refresh
    try:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            await refresh(db)
    except Exception as exc:  # noqa: BLE001 — the defaults keep working without the database
        logger.warning("bot texts not refreshed: %s", exc)


class _Updates:
    """Counts updates between state writes (one write a minute, not one per message)."""
    def __init__(self):
        self.count, self.last = 0, None

    async def __call__(self, handler, event, data):
        self.count += 1
        self.last = datetime.utcnow()
        await _refresh_texts()
        return await handler(event, data)

    def take(self) -> tuple[int, datetime | None]:
        count, self.count = self.count, 0
        return count, self.last


async def run_with_token(token: str, *, bot_factory=None, poll=True) -> str:
    """One session with one token: until the token changes in the runtime settings (returns "changed") or Telegram
    refuses it (raises). The supervisor starts the next session."""
    from .telegram_bot import fingerprint
    from . import bot_workspace  # Registers account commands on the shared router.
    bot = (bot_factory or Bot)(token)
    counter = _Updates()
    dp = Dispatcher(storage=fsm_storage())
    dp.update.outer_middleware(counter)
    if router.parent_router is None:
        dp.include_router(router)
    if bot_workspace.router.parent_router is None:
        dp.include_router(bot_workspace.router)
    try:
        me = await bot.get_me()
        now = datetime.utcnow()
        await _report(state="running", bot_id=me.id, username=me.username, first_name=me.first_name, token_fingerprint=fingerprint(token),
                      started_at=now, last_ok_at=now, last_error=None)
        logger.info("bot @%s connected (token %s)", me.username, fingerprint(token))
        # This service uses long polling. Remove a stale webhook left by a previous deployment so Telegram does not
        # route updates somewhere else.
        await bot.delete_webhook(drop_pending_updates=False)
        broadcasts = asyncio.create_task(broadcast_worker(bot))
        polling = asyncio.create_task(dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types(), handle_signals=False)) if poll else None
        try:
            waited = 0
            while True:
                await asyncio.sleep(TOKEN_CHECK)
                waited += TOKEN_CHECK
                if polling is not None and polling.done():
                    polling.result()  # re-raises what stopped it
                    return "stopped"
                if settings.bot_token != token:
                    logger.info("BOT_TOKEN changed in the runtime settings: reconnecting")
                    return "changed"
                if waited >= POLL_CHECK:
                    waited = 0
                    await bot.get_me()
                    count, last = counter.take()
                    await _report(last_ok_at=datetime.utcnow(), updates=count, **({"last_update_at": last} if last else {}))
        finally:
            if polling is not None and not polling.done():
                try:
                    await dp.stop_polling()
                except RuntimeError:  # not started yet: cancel instead
                    polling.cancel()
                await asyncio.gather(polling, return_exceptions=True)
            broadcasts.cancel()
            await asyncio.gather(broadcasts, return_exceptions=True)
            count, last = counter.take()
            if count:
                await _report(updates=count, last_update_at=last)
    finally:
        await bot.session.close()
        for r in (router, bot_workspace.router):
            if r.parent_router is not None:
                r._parent_router = None


async def supervise(*, bot_factory=None, poll=True, sessions: int | None = None) -> None:
    """The bot process: runs a session with the current token, reconnects when it changes, waits while it is empty,
    retries after errors. The state goes to telegram_bot_state for the admin panel."""
    done = 0
    while sessions is None or done < sessions:
        token = settings.bot_token
        if not token:
            await _report(state="idle", last_error="BOT_TOKEN не задан")
            while not settings.bot_token:
                await asyncio.sleep(TOKEN_CHECK)
            continue
        done += 1
        try:
            await run_with_token(token, bot_factory=bot_factory, poll=poll)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — a refused token or a network outage: report, wait, try again
            text = str(exc).replace(token, "***")[:500]
            logger.error("bot session failed: %s: %s", type(exc).__name__, text)
            await _report(state="error", last_error=f"{type(exc).__name__}: {text}", last_error_at=datetime.utcnow())
            waited = 0
            while settings.bot_token == token and waited < 60:  # a new token is tried at once
                await asyncio.sleep(TOKEN_CHECK)
                waited += TOKEN_CHECK


async def main():
    import os
    os.environ.setdefault("APP_PROCESS", "bot")
    from .runtime_settings import refresh_runtime_settings, runtime_settings_scheduler
    from . import error_log
    error_log.install()  # the bot's errors reach «Журнал ошибок» (process «bot»)
    async with AsyncSession(engine, expire_on_commit=False) as db:
        await refresh_runtime_settings(db, force=True)
    runtime_task = asyncio.create_task(runtime_settings_scheduler())
    from .heartbeat import keep_beating
    beating = asyncio.create_task(keep_beating("bot"))  # container healthcheck: the event loop is alive (kept referenced)
    if not settings.bot_token:
        # v28.71.0: the token is a runtime setting now — the process waits for it instead of stopping.
        logger.warning("BOT_TOKEN is empty; the bot waits for it in the runtime settings")
    try:
        await supervise()
    finally:
        for task in (runtime_task, beating):
            task.cancel()
        await asyncio.gather(runtime_task, beating, return_exceptions=True)


def fsm_storage():
    """aiogram FSM state in Redis: survives a bot restart and is shared if the bot is moved to another host.
    Without Redis (local runs, tests) the in-memory storage is used."""
    from aiogram.fsm.storage.memory import MemoryStorage
    if not settings.redis_url:
        return MemoryStorage()
    try:
        from aiogram.fsm.storage.redis import DefaultKeyBuilder, RedisStorage
        return RedisStorage.from_url(settings.redis_url, connection_kwargs=settings.redis_connection_kwargs(),
                                     key_builder=DefaultKeyBuilder(prefix="corgi_fsm", with_bot_id=True),
                                     state_ttl=86400, data_ttl=86400)
    except Exception as exc:  # noqa: BLE001 — the bot must start even if Redis is misconfigured
        logger.warning("Redis FSM storage unavailable, using memory: %s", exc)
        return MemoryStorage()


if __name__=="__main__": asyncio.run(main())
