"""Every text the Telegram bot sends, on Russian, English and Ukrainian (v28.72, stage 13; docs/ru/new/TELEGRAM_GUIDE.md).

The defaults live here; the owner changes any of them in «Бот и кабинет → Telegram-бот → Тексты бота» (stored in
``app_settings.bot_texts`` as ``{lang: {key: text}}``). An override keeps the placeholders of its default
(``{name}``) and only the HTML tags Telegram understands. The language comes from the customer's Telegram
(``language_code``): Ukrainian, English, otherwise Russian (or the shop's default language).

Values put into placeholders are escaped by the bot; the texts themselves are the owner's and may use
``<b> <i> <u> <s> <code> <a href>``."""
from __future__ import annotations

import json
import re
import time

LANGS = ("ru", "en", "uk")
SETTING = "bot_texts"
PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")
TAG = re.compile(r"</?(b|i|u|s|code|pre|a)(\s+href=\"https?://[^\"<>]+\")?>")

# key: (group, ru, en, uk)
DEFAULTS: dict[str, tuple[str, str, str, str]] = {
    # ---- start and menu
    # Brand texts as defaults (owner's decision 4 of 2026-11-12; docs/BRAND_COPY.md).
    "welcome": ("Старт", "Добро пожаловать в {name} — свободный интернет без лишнего Гав!\nТвой интернет. Твои правила. Твоя Люси.",
                "Welcome to {name} — free internet without the extra woof!\nYour internet. Your rules. Your Lusi.",
                "Ласкаво просимо до {name} — вільний інтернет без зайвого Гав!\nТвій інтернет. Твої правила. Твоя Люсі."),
    "shop_name": ("Старт", "Корги Люси", "Corgi Lusi", "Коргі Люсі"),
    "open_shop": ("Старт", "🛒 Открыть магазин", "🛒 Open shop", "🛒 Відкрити магазин"),
    "prices": ("Старт", "Актуальные цены", "Current prices", "Актуальні ціни"),
    "promo_scope": ("Старт", " для выбранных тарифов", " for selected plans", " для вибраних тарифів"),
    "promo_off": ("Старт", "скидка", "off", "знижка"),
    "gift_ready": ("Старт", "Подарок <b>{code}</b>. Откройте магазин, чтобы активировать его.", "Gift <b>{code}</b>. Open the shop to activate it.",
                   "Подарунок <b>{code}</b>. Відкрийте магазин, щоб активувати його."),
    "family_invite": ("Старт", "👨‍👩‍👧 Вас пригласили в семейную подписку. Откройте магазин, чтобы присоединиться.",
                      "👨‍👩‍👧 You are invited to a family subscription. Open the shop to join.",
                      "👨‍👩‍👧 Вас запросили до сімейної підписки. Відкрийте магазин, щоб приєднатися."),
    "channels_required": ("Старт", "Чтобы пользоваться ботом, подпишитесь: {channels}. Затем снова нажмите /start.",
                          "To use the bot, subscribe to: {channels}. Then press /start again.",
                          "Щоб користуватися ботом, підпишіться: {channels}. Потім знову натисніть /start."),
    "private_only": ("Общее", "Откройте личный чат с ботом.", "Open a private chat with the bot.", "Відкрийте особистий чат із ботом."),
    "start_first": ("Общее", "Начните с /start.", "Start with /start.", "Почніть із /start."),
    "restricted": ("Общее", "Начните с /start. Если доступ ограничен, обратитесь в поддержку.",
                   "Start with /start. If access is restricted, contact support.",
                   "Почніть із /start. Якщо доступ обмежено, зверніться до підтримки."),
    "menu_title": ("Меню", "Меню", "Menu", "Меню"),
    "menu_button_gone": ("Меню", "Кнопка больше не доступна", "This button is no longer available", "Кнопка більше не доступна"),
    "menu_field_gone": ("Меню", "Поле больше не доступно", "This field is no longer available", "Поле більше не доступне"),
    "menu_empty": ("Меню", "Меню пусто или больше не доступно", "The menu is empty or no longer available", "Меню порожнє або більше не доступне"),
    # ---- app sign-in
    "app_login": ("Приложение", "📱 <b>Вход в приложение</b>\nНажмите кнопку на телефоне, где установлено приложение. Ссылка работает один раз и действует {minutes} минут. Никому её не пересылайте.",
                  "📱 <b>Sign in to the app</b>\nTap the button on the phone with the app installed. The link works once and expires in {minutes} minutes. Do not forward it.",
                  "📱 <b>Вхід у застосунок</b>\nНатисніть кнопку на телефоні, де встановлено застосунок. Посилання працює один раз і діє {minutes} хвилин. Нікому його не пересилайте."),
    "app_open": ("Приложение", "Открыть приложение", "Open the app", "Відкрити застосунок"),
    # ---- plans and subscription
    "plans_title": ("Тарифы", "🛒 <b>Тарифы</b>", "🛒 <b>Plans</b>", "🛒 <b>Тарифи</b>"),
    "plan_line": ("Тарифы", "• {plan} — {price} {currency} / {days} дн.", "• {plan} — {price} {currency} / {days} days", "• {plan} — {price} {currency} / {days} дн."),
    "plans_empty": ("Тарифы", "Магазин временно не содержит тарифов.", "The shop has no plans configured.", "У магазині тимчасово немає тарифів."),
    "no_subscription": ("Подписка", "Активной подписки нет. Откройте магазин.", "No active subscription. Open the shop.", "Активної підписки немає. Відкрийте магазин."),
    "your_subscription": ("Подписка", "Ваша подписка:", "Your subscription:", "Ваша підписка:"),
    "promo_usage": ("Промокоды", "Использование: /promo КОД", "Usage: /promo CODE", "Використання: /promo КОД"),
    "promo_ready": ("Промокоды", "Промокод <b>{code}</b>. Откройте магазин и примените его к тарифу.", "Promo code <b>{code}</b>. Open the shop and apply it to a plan.",
                    "Промокод <b>{code}</b>. Відкрийте магазин і застосуйте його до тарифу."),
    # ---- keys and statistics
    "keys_title": ("Ключи", "🔑 <b>Ключи подключения</b> — нажмите, чтобы скопировать:", "🔑 <b>Connection keys</b> — tap to copy:",
                   "🔑 <b>Ключі підключення</b> — натисніть, щоб скопіювати:"),
    "keys_unavailable": ("Ключи", "Сейчас не получилось получить ключи — попробуйте чуть позже или откройте кабинет.",
                         "Could not get the keys right now — try again a bit later or open the cabinet.",
                         "Зараз не вдалося отримати ключі — спробуйте трохи пізніше або відкрийте кабінет."),
    "keys_masque": ("Ключи", "🛰 <b>MASQUE · {name}</b> — отдельная подписка в формате JSON, добавьте ссылку в клиент как подписку:\n<code>{url}</code>",
                    "🛰 <b>MASQUE · {name}</b> — a separate JSON subscription, add the link to your client as a subscription:\n<code>{url}</code>",
                    "🛰 <b>MASQUE · {name}</b> — окрема підписка у форматі JSON, додайте посилання в клієнт як підписку:\n<code>{url}</code>"),
    "keys_empty": ("Ключи", "В подписке пока нет серверов.", "The subscription has no servers yet.", "У підписці поки немає серверів."),
    "stats": ("Статистика", "📊 <b>Моя статистика</b>\nС нами {days_with_us} дн., оплачено {days_paid} дн. VPN\nТрафик за период: {traffic}\nУстройства: {devices}",
              "📊 <b>My statistics</b>\nWith us {days_with_us} days, {days_paid} days of VPN paid\nTraffic this period: {traffic}\nDevices: {devices}",
              "📊 <b>Моя статистика</b>\nЗ нами {days_with_us} дн., оплачено {days_paid} дн. VPN\nТрафік за період: {traffic}\nПристрої: {devices}"),
    "of": ("Статистика", "из", "of", "з"),
    "gb": ("Статистика", "ГБ", "GB", "ГБ"),
    # ---- contest
    "contest_none": ("Конкурс", "Сейчас конкурса нет — следите за новостями.", "There is no contest right now — stay tuned.", "Зараз конкурсу немає — стежте за новинами."),
    "contest_title": ("Конкурс", "🏆 <b>{title}</b> — до {date}", "🏆 <b>{title}</b> — until {date}", "🏆 <b>{title}</b> — до {date}"),
    "contest_place": ("Конкурс", "Вы на {place} месте ({score})", "You are in place {place} ({score})", "Ви на {place} місці ({score})"),
    "contest_join": ("Конкурс", "Пригласите друга по своей ссылке, чтобы попасть в таблицу: /referral", "Invite a friend with your link to get on the board: /referral",
                     "Запросіть друга за своїм посиланням, щоб потрапити в таблицю: /referral"),
    # ---- service status
    "status_operational": ("Состояние сервиса", "🟢 Всё работает", "🟢 All systems operational", "🟢 Усе працює"),
    "status_degraded": ("Состояние сервиса", "🟡 Часть сервиса работает с перебоями", "🟡 Part of the service is degraded", "🟡 Частина сервісу працює з перебоями"),
    "status_outage": ("Состояние сервиса", "🔴 Серьёзный сбой", "🔴 Major outage", "🔴 Серйозний збій"),
    "status_unknown": ("Состояние сервиса", "⚪️ Нет данных", "⚪️ No data", "⚪️ Немає даних"),
    "status_now": ("Состояние сервиса", "<b>Сейчас:</b> {incidents}", "<b>Now:</b> {incidents}", "<b>Зараз:</b> {incidents}"),
    "status_notify_on": ("Состояние сервиса", "🔔 Сообщать о сбоях", "🔔 Notify me about outages", "🔔 Повідомляти про збої"),
    "status_notify_off": ("Состояние сервиса", "🔕 Не сообщать о сбоях", "🔕 Stop outage notifications", "🔕 Не повідомляти про збої"),
    "status_subscribed": ("Состояние сервиса", "Буду сообщать о сбоях и восстановлении", "I will tell you about outages and recovery", "Повідомлятиму про збої та відновлення"),
    "status_unsubscribed": ("Состояние сервиса", "Больше не сообщаю о сбоях", "Outage notifications are off", "Більше не повідомляю про збої"),
    # ---- feedback
    "feedback_failed": ("Оценки", "Не получилось сохранить оценку", "Could not save the rating", "Не вдалося зберегти оцінку"),
    "feedback_thanks": ("Оценки", "Спасибо за оценку!", "Thank you for the rating!", "Дякуємо за оцінку!"),
    "feedback_low": ("Оценки", "Спасибо! Расскажите, что можно сделать лучше, — просто напишите в поддержку.",
                     "Thank you! Tell us what we could do better — just write to support.",
                     "Дякуємо! Розкажіть, що можна зробити краще, — просто напишіть у підтримку."),
    "feedback_high": ("Оценки", "Спасибо, что помогаете нам стать лучше!", "Thank you for helping us get better!", "Дякуємо, що допомагаєте нам ставати кращими!"),
    # ---- filter
    "filter_unavailable": ("Фильтр", "Фильтр сейчас недоступен.", "The filter is not available right now.", "Фільтр зараз недоступний."),
    "filter_none": ("Фильтр", "Без фильтра", "No filter", "Без фільтра"),
    "filter_current": ("Фильтр", "Сейчас: {mode}. Фильтр работает на сервере — на всех ваших устройствах.",
                       "Now: {mode}. The filter works on the server — on all your devices.",
                       "Зараз: {mode}. Фільтр працює на сервері — на всіх ваших пристроях."),
    "filter_family": ("Фильтр", "Фильтр этой подписки включает владелец семьи", "The family owner sets the filter of this subscription", "Фільтр цієї підписки вмикає власник сім'ї"),
    "filter_on": ("Фильтр", "Готово — фильтр включится в течение минуты", "Done — the filter turns on within a minute", "Готово — фільтр увімкнеться протягом хвилини"),
    "filter_off": ("Фильтр", "Фильтр выключен", "The filter is off", "Фільтр вимкнено"),
    "subscription_not_found": ("Подписка", "Подписка не найдена", "Subscription not found", "Підписку не знайдено"),
    # ---- loyalty
    "level_off": ("Лояльность", "Уровни лояльности сейчас не действуют.", "Loyalty levels are not active right now.", "Рівні лояльності зараз не діють."),
    "level_current": ("Лояльность", "🏅 <b>Ваш уровень: {level}</b>", "🏅 <b>Your level: {level}</b>", "🏅 <b>Ваш рівень: {level}</b>"),
    "level_cashback": ("Лояльность", "кешбэк {percent}%", "cashback {percent}%", "кешбек {percent}%"),
    "level_discount": ("Лояльность", "скидка {percent}%", "discount {percent}%", "знижка {percent}%"),
    "level_next": ("Лояльность", "До уровня «{level}»: {need}. Там: {perks}", "To «{level}»: {need}. There: {perks}", "До рівня «{level}»: {need}. Там: {perks}"),
    "level_need_little": ("Лояльность", "совсем немного", "very little", "зовсім трохи"),
    "level_bonus_days": ("Лояльность", ", +{days} дн. в подарок", ", +{days} bonus days", ", +{days} дн. у подарунок"),
    "level_top": ("Лояльность", "У вас высший уровень — спасибо, что вы с нами!", "You have the top level — thank you for being with us!",
                  "У вас найвищий рівень — дякуємо, що ви з нами!"),
    # ---- freeze
    "freeze_unavailable": ("Заморозка", "Заморозка подписки сейчас недоступна.", "Pausing the subscription is not available right now.", "Заморожування підписки зараз недоступне."),
    "freeze_frozen": ("Заморозка", "Подписка заморожена до {date}. Разморозить сейчас? Неиспользованные дни заморозки вычтутся из срока.",
                      "The subscription is paused until {date}. Resume now? Unused pause days are taken from the term.",
                      "Підписку заморожено до {date}. Розморозити зараз? Невикористані дні заморожування віднімуться від терміну."),
    "freeze_thaw_button": ("Заморозка", "▶️ Разморозить", "▶️ Resume", "▶️ Розморозити"),
    "freeze_days_button": ("Заморозка", "{days} дн.", "{days} days", "{days} дн."),
    "freeze_offer": ("Заморозка", "Поставить подписку на паузу? VPN выключится, оплаченные дни сохранятся, срок сдвинется. В этом году доступно ещё {days} дн.",
                     "Pause the subscription? VPN turns off, paid days are kept and the term moves. {days} days are left this year.",
                     "Поставити підписку на паузу? VPN вимкнеться, оплачені дні збережуться, термін зсунеться. Цього року доступно ще {days} дн."),
    "freeze_not_frozen": ("Заморозка", "Подписка не заморожена", "The subscription is not paused", "Підписку не заморожено"),
    "freeze_thawed": ("Заморозка", "VPN снова работает. Подписка действует до {date}.", "VPN works again. The subscription is valid until {date}.",
                      "VPN знову працює. Підписка діє до {date}."),
    "freeze_done": ("Заморозка", "Подписка заморожена до {date}. Разморозить раньше: /freeze", "The subscription is paused until {date}. Resume earlier: /freeze",
                    "Підписку заморожено до {date}. Розморозити раніше: /freeze"),
    # ---- Telegram Stars
    "stars_check_failed": ("Оплата", "Не удалось проверить счёт. Попробуйте ещё раз.", "Could not check the invoice. Please try again.", "Не вдалося перевірити рахунок. Спробуйте ще раз."),
    "stars_paid_subscription": ("Оплата", "⭐ Оплата получена: подписка продлена.", "⭐ Payment received: the subscription is renewed.", "⭐ Оплату отримано: підписку продовжено."),
    "stars_paid_balance": ("Оплата", "⭐ Оплата получена, баланс пополнен.", "⭐ Payment received, the balance is topped up.", "⭐ Оплату отримано, баланс поповнено."),
    "stars_delayed": ("Оплата", "Оплата получена. Зачисление на баланс задерживается — поддержка уже видит платёж.",
                      "Payment received. Crediting the balance is delayed — support already sees the payment.",
                      "Оплату отримано. Зарахування на баланс затримується — підтримка вже бачить платіж."),
    # ---- account shortcuts (bot_workspace.py)
    "ws_surveys": ("Кабинет", "Опросы", "Surveys", "Опитування"),
    "ws_account": ("Кабинет", "Мой кабинет", "My account", "Мій кабінет"),
    "ws_balance": ("Кабинет", "Кошелёк", "Wallet", "Гаманець"),
    "ws_payments": ("Кабинет", "Платежи", "Payments", "Платежі"),
    "ws_gifts": ("Кабинет", "Подарки", "Gifts", "Подарунки"),
    "ws_referral": ("Кабинет", "Реферальная программа", "Referral program", "Реферальна програма"),
    "ws_support": ("Кабинет", "Поддержка", "Support", "Підтримка"),
    "ws_devices": ("Кабинет", "Устройства", "Devices", "Пристрої"),
    "ws_wallet": ("Кабинет", "Кошелёк: {amount} {currency}", "Wallet: {amount} {currency}", "Гаманець: {amount} {currency}"),
    "ws_referral_balance": ("Кабинет", "Реферальный баланс: {amount} {currency}", "Referral balance: {amount} {currency}", "Реферальний баланс: {amount} {currency}"),
    "ws_referral_code": ("Кабинет", "Код приглашения: <code>{code}</code>", "Invitation code: <code>{code}</code>", "Код запрошення: <code>{code}</code>"),
    "ws_subscription_until": ("Кабинет", "Подписка до {date}", "Subscription until {date}", "Підписка до {date}"),
    "ws_no_subscription": ("Кабинет", "Активной подписки нет", "No active subscription", "Активної підписки немає"),
    "ws_no_payments": ("Кабинет", "Платежей пока нет.", "No payments yet.", "Платежів поки немає."),
    "ws_tribute": ("Кабинет", "💝 Пополнить донатом (Tribute)", "💝 Top up with a donation (Tribute)", "💝 Поповнити донатом (Tribute)"),
    # ---- documents
    "info_title": ("Документы", "ℹ️ <b>Информация</b>", "ℹ️ <b>Information</b>", "ℹ️ <b>Інформація</b>"),
    "info_empty": ("Документы", "Документы пока не опубликованы.", "No documents are published yet.", "Документи ще не опубліковані."),
    # ---- owner
    "ops_denied": ("Владелец", "Команда только для владельца магазина.", "This command is only for the shop owner.", "Команда доступна лише власнику магазину."),
    "ops_status": ("Владелец", "Открытых нарушений: {violations}. Агентов за 5 минут: {agents}. Панель: {url}", "Open violations: {violations}. Agents seen in 5 minutes: {agents}. Panel: {url}",
                   "Відкритих порушень: {violations}. Агентів за 5 хвилин: {agents}. Панель: {url}"),
    "ops_panel": ("Владелец", "Панель", "Panel", "Панель"),
}

_cache: dict = {"at": 0.0, "overrides": {}}
TTL = 60


def default(lang: str, key: str) -> str:
    group, ru, en, uk = DEFAULTS[key]
    return {"ru": ru, "en": en, "uk": uk}.get(lang, ru)


def placeholders(key: str) -> set[str]:
    return set(PLACEHOLDER.findall(DEFAULTS[key][1]))


def t(lang: str, key: str, **values) -> str:
    """The text for the customer's language, with the owner's override if there is one. Values are inserted as
    given — the caller escapes them for HTML."""
    lang = lang if lang in LANGS else "ru"
    text = (_cache["overrides"].get(lang) or {}).get(key) or default(lang, key)
    for name, value in values.items():
        text = text.replace("{" + name + "}", str(value))
    return text


def check_override(key: str, text: str) -> str:
    """An override: only the placeholders of the default and only Telegram's HTML tags."""
    if key not in DEFAULTS:
        raise ValueError(f"Нет текста {key}")
    text = text.strip()
    if not text or len(text) > 3500:
        raise ValueError(f"{key}: от 1 до 3500 символов")
    extra = set(PLACEHOLDER.findall(text)) - placeholders(key)
    if extra:
        raise ValueError(f"{key}: неизвестные подстановки {', '.join('{' + e + '}' for e in sorted(extra))}")
    if "<" in TAG.sub("", text):
        raise ValueError(f"{key}: можно только теги <b> <i> <u> <s> <code> <pre> <a href>")
    return text


def load(value: str | None) -> dict:
    try:
        data = json.loads(value or "{}")
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {lang: {k: v for k, v in (data.get(lang) or {}).items() if k in DEFAULTS and isinstance(v, str)} for lang in LANGS}


async def refresh(db, force: bool = False) -> None:
    """Reads the overrides (at most once a minute; the bot calls it before answering)."""
    if not force and time.monotonic() - _cache["at"] < TTL:
        return
    from .models import AppSetting
    row = await db.get(AppSetting, SETTING)
    _cache["overrides"] = load(row.value if row else None)
    _cache["at"] = time.monotonic()
