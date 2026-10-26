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
from .config import settings
from .db import engine
from .bot_banners import send_section
from .models import AppSetting,BotMenuItem,CustomField,Promotion,Advertisement,Plan,Broadcast,User,Subscription,AbuseViolation,NodeAgent

logger = logging.getLogger("remnawave.broadcast")

router=Router()

_BOT_TEXT = {
    "ru": {
        "welcome": "Добро пожаловать в {name}!",
        "prices": "Актуальные цены",
        "scope": " для выбранных тарифов",
        "open": "🛒 Открыть магазин",
        "promo_usage": "Использование: /promo КОД",
        "promo_ready": "Промокод <b>{code}</b>. Откройте магазин и примените его к тарифу.",
        "gift_ready": "Подарок <b>{code}</b>. Откройте магазин, чтобы активировать его.",
        "ops_denied": "Команда только для владельца магазина.",
        "ops_status": "Открытых нарушений: {violations}. Агентов за 5 минут: {agents}. Панель: {url}",
    },
    "uk": {
        "welcome": "Ласкаво просимо до {name}!", "prices": "Актуальні ціни", "scope": " для вибраних тарифів", "open": "🛒 Відкрити магазин", "promo_usage": "Використання: /promo КОД", "promo_ready": "Промокод <b>{code}</b>. Відкрийте магазин і застосуйте його до тарифу.", "gift_ready": "Подарунок <b>{code}</b>. Відкрийте магазин, щоб активувати його.", "ops_denied": "Команда доступна лише власнику магазину.", "ops_status": "Відкритих порушень: {violations}. Агентів за 5 хвилин: {agents}. Панель: {url}",
    },
    "en": {
        "welcome": "Welcome to {name}!",
        "prices": "Current prices",
        "scope": " for selected plans",
        "open": "🛒 Open shop",
        "promo_usage": "Usage: /promo CODE",
        "promo_ready": "Promo code <b>{code}</b>. Open the shop and apply it to a plan.",
        "gift_ready": "Gift <b>{code}</b>. Open the shop to activate it.",
        "ops_denied": "This command is only for the shop owner.",
        "ops_status": "Open violations: {violations}. Agents seen in 5 minutes: {agents}. Panel: {url}",
    },
}

def _lang(message: Message | None = None) -> str:
    code = ""
    if message is not None and message.from_user and message.from_user.language_code:
        code = message.from_user.language_code
    code = (code or settings.default_language or "ru").lower()
    if code.startswith("uk") or code.startswith("ua"): return "uk"
    return "en" if code.startswith("en") else "ru"

def _tr(lang: str, key: str, **kwargs) -> str:
    table = _BOT_TEXT.get(lang) or _BOT_TEXT["ru"]
    text = table[key]
    for name, value in kwargs.items():
        text = text.replace("{" + name + "}", str(value))
    return text

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
    discount_word = "скидка" if lang != "en" else "off"
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
        if not row or row.item_type!='field' or row not in visible_children(menu,row.parent_id):await query.answer('Кнопка больше не доступна');return
        field=next((f for f in fields if f.key==row.action and f.enabled),None)
        if not field:await query.answer('Поле больше не доступно');return
        await query.answer();await send_section(query.message,f'menu-{row.id}',f'<b>{escape(field.label)}</b>\n{escape(field.value)}');return
    if item_id and (not row or row.item_type!='folder' or not visible_children(menu,item_id)):
        await query.answer('Меню пусто или больше не доступно');return
    markup=telegram_keyboard(menu,fields,item_id or None)
    # Navigation edits the same message (banner + text + buttons) instead of posting new ones.
    await query.answer();await send_section(query.message,f'menu-{row.id}' if row else 'menu',escape(row.title) if row else 'Меню',markup,fallback='menu',edit=True)


async def send_app_login(message:Message):
    """One-use button that opens the Android/iOS app already signed in."""
    if not message.from_user:
        return
    from .account_merge import identity_user
    from .app_login import APP_CODE_MINUTES, issue_app_code, open_url
    async with AsyncSession(engine, expire_on_commit=False) as db:
        user=await identity_user(db,"telegram",int(message.from_user.id))
        if not user:
            await message.answer("Сначала отправьте /start, чтобы создать аккаунт.")
            return
        code=await issue_app_code(db,user.id)
        await db.commit()
    lang=_lang(message)
    text=("📱 <b>Вход в приложение</b>\nНажмите кнопку на телефоне, где установлено приложение. "
          f"Ссылка работает один раз и действует {APP_CODE_MINUTES} минут. Никому её не пересылайте.") if lang!="en" else \
         ("📱 <b>Sign in to the app</b>\nTap the button on the phone with the app installed. "
          f"The link works once and expires in {APP_CODE_MINUTES} minutes. Do not forward it.")
    markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Открыть приложение" if lang!="en" else "Open the app",url=open_url(code))]])
    await message.answer(text,reply_markup=markup,parse_mode="HTML")


@router.message(Command("app"))
async def app_command(message:Message):
    if not _private(message):
        await message.answer("Откройте личный чат с ботом, чтобы войти в приложение.")
        return
    await send_app_login(message)


@router.message(CommandStart())
async def start(message:Message):
    if getattr(getattr(message,"chat",None),"type","private")!="private":
        await message.answer("Откройте личный чат с ботом для управления аккаунтом.")
        return
    parts=(message.text or "").split(maxsplit=1)
    incoming=parts[1].strip().split()[0] if len(parts)>1 else ""

    # /start is also the canonical Telegram-to-shop binding point. Without this,
    # a user can interact with the bot but remain invisible to broadcasts and
    # Telegram-based account lookups until the Mini App is opened.
    if message.from_user:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            tg_id = int(message.from_user.id)
            from .account_merge import identity_user
            user = await identity_user(db, "telegram", tg_id)
            if user:
                changed = False
                username = message.from_user.username or user.username
                if user.telegram_id == tg_id and username and username != user.username:
                    user.username = username
                    changed = True
                if changed:
                    await db.commit()
            else:
                user=User(
                    telegram_id=tg_id,
                    username=message.from_user.username,
                    referral_code=__import__("secrets").token_urlsafe(8).upper(),
                )
                db.add(user)
                await db.commit()
            if incoming.lower().startswith("ref_") and not user.referred_by_id:
                from .referrals import bind_referrer
                from fastapi import HTTPException
                user=(await db.execute(select(User).where(User.id==user.id).with_for_update())).scalar_one()
                try:
                    await bind_referrer(db,user,incoming[4:])
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
    name=escape(vals.get("bot_name") or "Корги Люси"); text=_tr(lang,"welcome",name=name)
    pt=promo_text(promos,plans,lang)
    if gift_code: text += "\n\n"+_tr(lang,"gift_ready",code=escape(gift_code))
    if family_code: text += "\n\n"+("👨‍👩‍👧 Вас пригласили в семейную подписку. Откройте магазин, чтобы присоединиться." if lang!="en" else "👨‍👩‍👧 You are invited to a family subscription. Open the shop to join.")
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

INFO_EMPTY = {"ru": "Документы пока не опубликованы.", "en": "No documents are published yet.", "uk": "Документи ще не опубліковані."}
INFO_TITLE = {"ru": "ℹ️ <b>Информация</b>", "en": "ℹ️ <b>Information</b>", "uk": "ℹ️ <b>Інформація</b>"}


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
        await message.answer("Откройте личный чат с ботом, чтобы выбрать тариф.")
        return
    lang = _lang(message)
    _, _, _, _, _, plans = await get_bot_config()
    if not plans:
        await message.answer("Магазин временно не содержит тарифов." if lang == "ru" else "The shop has no plans configured.")
        return
    currency = escape(settings.default_currency or "RUB")
    unit = "дн." if lang == "ru" else "days"
    lines = [f"• {escape(p.name)} — {p.price:.2f} {currency} / {p.duration_days} {unit}" for p in plans]
    url = settings.mini_app_url
    await send_section(message, "buy", ("🛒 <b>Тарифы</b>\n" if lang == "ru" else "🛒 <b>Plans</b>\n") + "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=_tr(lang, "open"), web_app=WebAppInfo(url=url))]]))

@router.message(Command("subscription"))
async def subscription(message: Message):
    if getattr(getattr(message,"chat",None),"type","private")!="private":
        await message.answer("Откройте личный чат с ботом для просмотра подписки.")
        return
    lang = _lang(message)
    if not message.from_user:
        return
    async with AsyncSession(engine, expire_on_commit=False) as db:
        from .account_merge import identity_user
        user = await identity_user(db, "telegram", int(message.from_user.id))
        sub = (await db.execute(select(Subscription).where(Subscription.user_id == user.id,Subscription.is_primary.is_(True)))).scalar_one_or_none() if user else None
    if not sub or not sub.subscription_url:
        await send_section(message, "subscription", "Активной подписки нет. Откройте магазин." if lang == "ru" else "No active subscription. Open the shop.", InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=_tr(lang,"open"), web_app=WebAppInfo(url=settings.mini_app_url))]]))
        return
    await send_section(message, "subscription", ("Ваша подписка:\n" if lang == "ru" else "Your subscription:\n") + escape(sub.subscription_url))

@router.message(Command("promo"))
async def promo(message:Message):
    if not _private(message):
        await message.answer("Откройте личный чат с ботом, чтобы применить промокод.")
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
        error = "Не удалось проверить счёт. Попробуйте ещё раз."
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
        await message.answer("⭐ Оплата получена: подписка продлена." if paid.invoice_payload.startswith("starsub-") else "⭐ Оплата получена, баланс пополнен.")
    except Exception:
        # The charge id is in the update log; reconciliation by an operator uses it.
        logger.exception("Stars payment %s was not recorded", paid.telegram_payment_charge_id)
        await message.answer("Оплата получена. Зачисление на баланс задерживается — поддержка уже видит платёж.")


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
    buttons = [[InlineKeyboardButton(text="Панель" if lang == "ru" else "Panel", url=url)]]
    await message.answer(_tr(lang, "ops_status", violations=violations, agents=agents, url=escape(url)), reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")

async def main():
    from .runtime_settings import refresh_runtime_settings, runtime_settings_scheduler
    async with AsyncSession(engine, expire_on_commit=False) as db:
        await refresh_runtime_settings(db, force=True)
    runtime_task = asyncio.create_task(runtime_settings_scheduler())
    if not settings.bot_token:
        if (settings.app_env or "").strip().lower() == "production":
            runtime_task.cancel()
            await asyncio.gather(runtime_task, return_exceptions=True)
            raise RuntimeError("BOT_TOKEN is empty")
        logger.warning("BOT_TOKEN is empty; Telegram polling stays idle outside production")
        try:
            while True:
                await asyncio.sleep(3600)
        finally:
            runtime_task.cancel()
            await asyncio.gather(runtime_task, return_exceptions=True)
    from . import bot_workspace  # Registers account commands on the shared router.
    bot = Bot(settings.bot_token)
    dp = Dispatcher()
    dp.include_router(router)
    dp.include_router(bot_workspace.router)

    # This service uses long polling. Remove a stale webhook left by a previous
    # deployment so Telegram does not route updates somewhere else.
    await bot.delete_webhook(drop_pending_updates=False)

    asyncio.create_task(broadcast_worker(bot))
    try:
        # Explicit update types: Telegram Stars needs pre_checkout_query and the payment messages.
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        runtime_task.cancel()
        await asyncio.gather(runtime_task, return_exceptions=True)
        await bot.session.close()
if __name__=="__main__": asyncio.run(main())
