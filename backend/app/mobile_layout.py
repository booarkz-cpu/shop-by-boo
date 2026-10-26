"""Layout of the Android and iOS customer apps, edited in the admin panel.

The apps draw every screen from one document: the tab bar, the order and titles of the
sections, every button of every section (label in three languages, action, style, icon,
visibility), the section banners, the interface texts and the colours of the brand.
Administrator changes are stored as a full :class:`MobileLayout` in
``app_settings.mobile_layout``; an empty value means the defaults below.

* ``GET /api/mobile/layout?lang=ru|en|uk`` — public, resolved for one language, with an ETag.
  Banner URLs come from the banner registry (``bot_banners``): the default Lusi banner of the
  section, an uploaded one or nothing when the banner is hidden.
* ``GET/PUT/DELETE /api/admin/mobile-layout`` — the editable document, the defaults and the
  catalogues the editor needs (actions, icons, banner keys, texts).

The apps never execute anything the layout names that they do not know: an unknown action is
not representable here, URLs are limited to https:// and tg://, and section targets must exist.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .models import AppSetting
from .security import require_permission

logger = logging.getLogger(__name__)
router = APIRouter()
SETTING_KEY = "mobile_layout"
LANGS = ("ru", "en", "uk")
COLOR = r"^#[0-9a-fA-F]{6}$"
SLUG = r"^[a-z][a-z0-9_-]{0,31}$"

ICONS = ("power", "shield", "globe", "star", "crown", "user", "settings", "headset", "message", "send", "bell",
         "bug", "rocket", "gift", "wallet", "card", "users", "heart", "smartphone", "plus", "copy", "share", "link",
         "key", "lock", "info", "file", "help", "server", "activity", "zap", "clock", "refresh", "logout", "language",
         "sliders", "qr", "download", "trophy", "home")
Icon = Literal[ICONS]  # type: ignore[valid-type]

# Everything a button can do. The apps implement each action; "open" and "url" take a target.
ACTIONS: dict[str, str] = {
    "connect": "Подключить / отключить VPN (импорт подписки во VPN-клиент)",
    "open": "Открыть раздел приложения (цель — id раздела)",
    "url": "Открыть ссылку (цель — https:// или tg://)",
    "document": "Открыть документ (цель — faq, rules, privacy, offer из «Документов»)",
    "cabinet": "Открыть личный кабинет (ссылка из настроек макета)",
    "telegram_channel": "Открыть Telegram-канал (ссылка из настроек макета)",
    "import_app": "Добавить подписку в приложение (цель — happ, v2rayng, streisand, hiddify)",
    "copy_subscription": "Скопировать ссылку подписки",
    "show_qr": "Показать QR-код подписки",
    "copy_id": "Скопировать ID клиента",
    "buy": "Оплатить выбранный тариф",
    "pay_wallet": "Оплатить выбранный тариф с баланса",
    "trial": "Включить пробный период",
    "topup": "Пополнить баланс",
    "redeem": "Активировать промокод или подарочную карту",
    "auto_location": "Автовыбор самого быстрого сервера",
    "share_referral": "Поделиться реферальной ссылкой",
    "copy_referral": "Скопировать реферальную ссылку",
    "family_invite": "Пригласить в семейную подписку",
    "support_ticket": "Написать в чат поддержки (обращение)",
    "report_problem": "Сообщить о проблеме (обращение с диагностикой)",
    "language": "Сменить язык",
    "push_toggle": "Включить / выключить push-уведомления",
    "widget_toggle": "Включить / выключить виджет",
    "passkey_add": "Добавить ключ входа (passkey)",
    "refresh": "Обновить данные",
    "sign_out": "Выйти из аккаунта",
}
Action = Literal[tuple(ACTIONS)]  # type: ignore[valid-type]
IMPORT_APPS = ("happ", "v2rayng", "streisand", "hiddify")
DOCUMENTS = ("faq", "rules", "privacy", "offer")
Style = Literal["primary", "accent", "secondary", "ghost", "danger"]

# Section kinds the apps can draw. "custom" is an administrator page: a banner, a text and buttons.
KINDS = ("vpn", "locations", "premium", "subscription", "support", "settings", "devices", "family", "referral",
         "wallet", "gifts", "notifications", "status", "security", "info", "custom")
Kind = Literal[KINDS]  # type: ignore[valid-type]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Label(_Strict):
    ru: str = Field(min_length=1, max_length=60)
    en: str = Field(default="", max_length=60)
    uk: str = Field(default="", max_length=60)

    def pick(self, lang: str) -> str:
        return (getattr(self, lang, "") or "").strip() or self.ru


class LongText(_Strict):
    ru: str = Field(default="", max_length=2000)
    en: str = Field(default="", max_length=2000)
    uk: str = Field(default="", max_length=2000)

    def pick(self, lang: str) -> str:
        return (getattr(self, lang, "") or "").strip() or self.ru


def _safe_url(value: str) -> str:
    value = (value or "").strip()
    if value and (not re.match(r"^(https://|tg://)[^\s<>\"']+$", value) or len(value) > 1024):
        raise ValueError("Ссылка должна начинаться с https:// или tg:// и не содержать пробелов")
    return value


class Button(_Strict):
    id: str = Field(pattern=SLUG)
    label: Label
    action: Action
    target: str = Field(default="", max_length=1024)
    style: Style = "secondary"
    icon: Icon | Literal[""] = ""
    visible: bool = True
    # Shown only to customers with (or without) an active subscription; "any" — always.
    audience: Literal["any", "subscribed", "unsubscribed"] = "any"

    @model_validator(mode="after")
    def target_fits_action(self):
        if self.action == "url":
            if not self.target:
                raise ValueError(f"Кнопка {self.id}: укажите ссылку")
            _safe_url(self.target)
        elif self.action == "open":
            if not re.fullmatch(SLUG, self.target or ""):
                raise ValueError(f"Кнопка {self.id}: укажите раздел, который она открывает")
        elif self.action == "import_app":
            if self.target not in IMPORT_APPS:
                raise ValueError(f"Кнопка {self.id}: приложение — одно из {', '.join(IMPORT_APPS)}")
        elif self.action == "document":
            if self.target not in DOCUMENTS:
                raise ValueError(f"Кнопка {self.id}: документ — один из {', '.join(DOCUMENTS)}")
        elif self.target:
            raise ValueError(f"Кнопка {self.id}: действие «{self.action}» не принимает цель")
        return self


class Banner(_Strict):
    enabled: bool = True
    # Key in the banner registry: a default Lusi banner that can be replaced by an upload
    # in «Контент → Баннеры». Empty — the section has no banner.
    key: str = Field(default="", pattern=r"^$|^[a-z][a-z0-9-]{0,40}$")
    link: str = Field(default="", max_length=1024)
    _link = field_validator("link")(classmethod(lambda cls, v: _safe_url(v)))


class Section(_Strict):
    id: str = Field(pattern=SLUG)
    kind: Kind
    enabled: bool = True
    tab: bool = False
    title: Label
    subtitle: LongText = Field(default_factory=LongText)
    body: LongText = Field(default_factory=LongText)
    icon: Icon = "info"
    banner: Banner = Field(default_factory=Banner)
    buttons: list[Button] = Field(default_factory=list, max_length=24)

    @field_validator("buttons")
    @classmethod
    def unique_buttons(cls, value):
        ids = [b.id for b in value]
        if len(ids) != len(set(ids)):
            raise ValueError("Повторяется id кнопки в разделе")
        return value


class MobileTheme(_Strict):
    accent: str = Field(default="#FF8A1F", pattern=COLOR)
    accent_2: str = Field(default="#FFC069", pattern=COLOR)
    background: str = Field(default="#0E0F14", pattern=COLOR)
    surface: str = Field(default="#1A1C24", pattern=COLOR)
    surface_2: str = Field(default="#252833", pattern=COLOR)
    text: str = Field(default="#F5F2EE", pattern=COLOR)
    muted: str = Field(default="#9A97A3", pattern=COLOR)
    success: str = Field(default="#3DDC84", pattern=COLOR)
    danger: str = Field(default="#FF5A6E", pattern=COLOR)
    radius: int = Field(default=22, ge=0, le=40)


DEFAULT_TEXTS: dict[str, dict[str, str]] = {
    "brand": {"ru": "Корги VPN", "en": "Corgi VPN", "uk": "Коргі VPN"},
    "status_off": {"ru": "VPN отключён", "en": "VPN is off", "uk": "VPN вимкнено"},
    "status_connecting": {"ru": "Подключаем…", "en": "Connecting…", "uk": "Підключаємо…"},
    "status_on": {"ru": "VPN подключён", "en": "VPN is on", "uk": "VPN підключено"},
    "status_no_client": {"ru": "Установите VPN-клиент, чтобы подключиться", "en": "Install a VPN client to connect",
                         "uk": "Встановіть VPN-клієнт, щоб підключитися"},
    "traffic_left": {"ru": "Осталось трафика", "en": "Traffic left", "uk": "Залишилось трафіку"},
    "unlimited": {"ru": "Безлимит", "en": "Unlimited", "uk": "Безліміт"},
    "until": {"ru": "до", "en": "until", "uk": "до"},
    "days_left": {"ru": "осталось {n} дн.", "en": "{n} days left", "uk": "залишилось {n} дн."},
    "no_subscription": {"ru": "Нет активной подписки", "en": "No active subscription", "uk": "Немає активної підписки"},
    "auto_location": {"ru": "Автовыбор — самый быстрый", "en": "Auto — the fastest", "uk": "Автовибір — найшвидший"},
    "devices": {"ru": "Устройств", "en": "Devices", "uk": "Пристроїв"},
    "servers": {"ru": "Серверы", "en": "Servers", "uk": "Сервери"},
    "your_id": {"ru": "Ваш ID", "en": "Your ID", "uk": "Ваш ID"},
    "per_month": {"ru": "₽/мес", "en": "₽/mo", "uk": "₽/міс"},
    "offline": {"ru": "Нет связи — показаны сохранённые данные", "en": "Offline — showing saved data",
                "uk": "Немає зв'язку — показано збережені дані"},
    "consent": {"ru": "Нажимая «Оплатить», вы принимаете оферту и условия автопродления",
                "en": "By paying you accept the offer and the auto-renewal terms",
                "uk": "Натискаючи «Оплатити», ви приймаєте оферту та умови автопродовження"},
}


def _b(id_, ru, en, uk, action, target="", style="secondary", icon="", audience="any") -> dict:
    return {"id": id_, "label": {"ru": ru, "en": en, "uk": uk}, "action": action, "target": target, "style": style,
            "icon": icon, "visible": True, "audience": audience}


def _s(id_, kind, ru, en, uk, icon, banner, buttons, tab=False, subtitle=None) -> dict:
    return {"id": id_, "kind": kind, "enabled": True, "tab": tab, "title": {"ru": ru, "en": en, "uk": uk},
            "subtitle": subtitle or {"ru": "", "en": "", "uk": ""}, "body": {"ru": "", "en": "", "uk": ""},
            "icon": icon, "banner": {"enabled": bool(banner), "key": banner, "link": ""}, "buttons": buttons}


DEFAULT_SECTIONS = [
    _s("subscription", "subscription", "Подписка", "Subscription", "Підписка", "user", "app-subscription", [
        _b("copy_id", "Копировать ID", "Copy ID", "Копіювати ID", "copy_id", style="ghost", icon="copy"),
        _b("happ", "Добавить в Happ", "Add to Happ", "Додати в Happ", "import_app", "happ", "primary", "download", "subscribed"),
        _b("v2rayng", "Добавить в v2rayNG", "Add to v2rayNG", "Додати в v2rayNG", "import_app", "v2rayng", "secondary", "download", "subscribed"),
        _b("copy_link", "Скопировать ссылку подписки", "Copy subscription link", "Скопіювати посилання", "copy_subscription", icon="link", audience="subscribed"),
        _b("qr", "QR-код для другого устройства", "QR code for another device", "QR-код для іншого пристрою", "show_qr", icon="qr", audience="subscribed"),
        _b("devices", "Добавить устройства", "Add devices", "Додати пристрої", "open", "devices", icon="smartphone"),
        _b("premium", "Перейти на Премиум", "Go Premium", "Перейти на Преміум", "open", "premium", "accent", "crown"),
        _b("wallet", "Баланс и пополнение", "Balance and top-up", "Баланс і поповнення", "open", "wallet", icon="wallet"),
        _b("family", "Семейная подписка", "Family plan", "Сімейна підписка", "open", "family", icon="heart"),
        _b("referral", "Пригласить друга", "Invite a friend", "Запросити друга", "open", "referral", icon="users"),
        _b("gifts", "Подарки и промокоды", "Gifts and promo codes", "Подарунки та промокоди", "open", "gifts", icon="gift"),
    ], tab=True),
    _s("premium", "premium", "Премиум", "Premium", "Преміум", "crown", "app-premium", [
        _b("buy", "Оплатить", "Pay", "Оплатити", "buy", style="primary", icon="card"),
        _b("pay_wallet", "Оплатить с баланса", "Pay from balance", "Оплатити з балансу", "pay_wallet", icon="wallet"),
        _b("redeem", "У меня есть промокод", "I have a promo code", "У мене є промокод", "redeem", style="ghost", icon="gift"),
        _b("offer", "Договор оферты", "Public offer", "Договір оферти", "document", "offer", "ghost", "file"),
    ], tab=True, subtitle={"ru": "Безлимитный трафик, все локации и приоритетная поддержка",
                           "en": "Unlimited traffic, every location and priority support",
                           "uk": "Безлімітний трафік, усі локації та пріоритетна підтримка"}),
    _s("vpn", "vpn", "VPN", "VPN", "VPN", "power", "app-vpn", [
        _b("connect", "Подключить", "Connect", "Підключити", "connect", style="primary", icon="power"),
        _b("location", "Выбрать локацию", "Choose location", "Обрати локацію", "open", "locations", icon="globe"),
        _b("upgrade", "Улучшить до Премиум", "Upgrade to Premium", "Покращити до Преміум", "open", "premium", "accent", "crown"),
        _b("trial", "Попробовать бесплатно", "Try for free", "Спробувати безкоштовно", "trial", style="secondary", icon="star", audience="unsubscribed"),
        _b("support", "Поддержка", "Support", "Підтримка", "open", "support", "ghost", "headset"),
        _b("report", "Сообщить о проблеме", "Report a problem", "Повідомити про проблему", "report_problem", style="ghost", icon="bug"),
    ], tab=True),
    _s("locations", "locations", "Локации", "Locations", "Локації", "globe", "app-locations", [
        _b("auto", "Автовыбор — самый быстрый", "Auto — the fastest", "Автовибір — найшвидший", "auto_location", style="primary", icon="rocket"),
    ], tab=True),
    _s("settings", "settings", "Настройки", "Settings", "Налаштування", "settings", "app-settings", [
        _b("cabinet", "Перейти в личный кабинет", "Open my account", "Перейти в особистий кабінет", "cabinet", style="primary", icon="user"),
        _b("channel", "Telegram-канал", "Telegram channel", "Telegram-канал", "telegram_channel", icon="send"),
        _b("language", "Язык", "Language", "Мова", "language", icon="language"),
        _b("push", "Push-уведомления", "Push notifications", "Push-сповіщення", "push_toggle", icon="bell"),
        _b("widget", "Виджет на главный экран", "Home screen widget", "Віджет на головний екран", "widget_toggle", icon="smartphone"),
        _b("notifications", "Уведомления", "Notifications", "Сповіщення", "open", "notifications", icon="bell"),
        _b("security", "Вход и безопасность", "Sign-in and security", "Вхід і безпека", "open", "security", icon="key"),
        _b("documents", "Документы", "Documents", "Документи", "open", "info", icon="file"),
        _b("privacy", "Политика конфиденциальности", "Privacy policy", "Політика конфіденційності", "document", "privacy", icon="lock"),
        _b("offer", "Договор оферты", "Public offer", "Договір оферти", "document", "offer", icon="file"),
        _b("report", "Сообщить о проблеме", "Report a problem", "Повідомити про проблему", "report_problem", icon="bug"),
        _b("sign_out", "Выйти", "Sign out", "Вийти", "sign_out", style="danger", icon="logout"),
    ], tab=True),
    _s("support", "support", "Поддержка", "Support", "Підтримка", "headset", "app-support", [
        _b("chat", "Написать в поддержку", "Message support", "Написати в підтримку", "support_ticket", style="primary", icon="message"),
        _b("faq", "Частые вопросы", "FAQ", "Часті питання", "document", "faq", icon="help"),
        _b("rules", "Правила сервиса", "Service rules", "Правила сервісу", "document", "rules", icon="file"),
        _b("status", "Состояние сервиса", "Service status", "Стан сервісу", "open", "status", icon="activity"),
        _b("channel", "Наш Telegram-канал", "Our Telegram channel", "Наш Telegram-канал", "telegram_channel", icon="send"),
    ]),
    _s("devices", "devices", "Устройства", "Devices", "Пристрої", "smartphone", "app-devices", [
        _b("qr", "Подключить по QR-коду", "Connect with a QR code", "Підключити за QR-кодом", "show_qr", style="primary", icon="qr", audience="subscribed"),
        _b("copy_link", "Скопировать ссылку подписки", "Copy subscription link", "Скопіювати посилання", "copy_subscription", icon="link", audience="subscribed"),
    ]),
    _s("family", "family", "Семья", "Family", "Родина", "heart", "app-family", [
        _b("invite", "Пригласить близких", "Invite your family", "Запросити близьких", "family_invite", style="primary", icon="share"),
    ]),
    _s("referral", "referral", "Пригласи друга", "Invite a friend", "Запроси друга", "users", "app-referral", [
        _b("share", "Поделиться", "Share", "Поділитися", "share_referral", style="primary", icon="share"),
        _b("copy", "Скопировать", "Copy", "Скопіювати", "copy_referral", icon="copy"),
    ], subtitle={"ru": "Дарим бонус за каждого друга, который оплатит подписку",
                 "en": "Get a bonus for every friend who buys a subscription",
                 "uk": "Даруємо бонус за кожного друга, який оплатить підписку"}),
    _s("wallet", "wallet", "Баланс", "Balance", "Баланс", "wallet", "app-wallet", [
        _b("topup", "Пополнить", "Top up", "Поповнити", "topup", style="primary", icon="card"),
    ]),
    _s("gifts", "gifts", "Подарки", "Gifts", "Подарунки", "gift", "app-gifts", [
        _b("redeem", "Активировать код", "Redeem a code", "Активувати код", "redeem", style="primary", icon="gift"),
    ]),
    _s("notifications", "notifications", "Уведомления", "Notifications", "Сповіщення", "bell", "app-notifications", [
        _b("push", "Push-уведомления", "Push notifications", "Push-сповіщення", "push_toggle", style="primary", icon="bell"),
    ]),
    _s("status", "status", "Состояние сервиса", "Service status", "Стан сервісу", "activity", "app-status", [
        _b("refresh", "Обновить", "Refresh", "Оновити", "refresh", icon="refresh"),
    ]),
    _s("security", "security", "Вход и безопасность", "Sign-in and security", "Вхід і безпека", "key", "app-security", [
        _b("passkey", "Добавить ключ входа", "Add a passkey", "Додати ключ входу", "passkey_add", style="primary", icon="key"),
    ]),
    _s("info", "info", "Информация", "Information", "Інформація", "info", "app-info", [
        _b("support", "Написать в поддержку", "Message support", "Написати в підтримку", "support_ticket", style="secondary", icon="message"),
    ], subtitle={"ru": "Частые вопросы, правила, политика конфиденциальности и оферта",
                 "en": "FAQ, rules, privacy policy and public offer",
                 "uk": "Часті питання, правила, політика конфіденційності та оферта"}),
]


# Strings of the apps (mobile/l10n/user.json, copied to assets/mobile_strings.json): every one can be
# replaced from the admin panel, per language. The apps use the replacement instead of their own text.
STRINGS_FILE = __import__("pathlib").Path(__file__).resolve().parent / "assets" / "mobile_strings.json"


def app_strings() -> dict[str, dict[str, str]]:
    """key → {"ru": …, "en": …, "uk": …} of the strings bundled with the apps."""
    raw = json.loads(STRINGS_FILE.read_text(encoding="utf-8"))
    return {k: {lang: raw.get(lang, {}).get(k, "") for lang in LANGS} for k in raw["ru"]}


# Blocks of the screens the administrator switches on and off.
FEATURES: dict[str, str] = {
    "header_support": "Главный экран: кнопка поддержки в шапке",
    "header_notifications": "Главный экран: кнопка уведомлений в шапке",
    "vpn_status": "Главный экран: статус VPN",
    "vpn_plan_card": "Главный экран: карточка тарифа и трафика",
    "vpn_location_card": "Главный экран: карточка локации",
    "login_banner": "Экран входа: баннер",
    "login_sign_up": "Экран входа: кнопка регистрации",
    "login_passkey": "Экран входа: вход по ключу (passkey)",
    "language_switch": "Экран входа: переключатель языка",
    "settings_version": "Настройки: версия приложения",
}


class MobileLayout(_Strict):
    schema_version: int = Field(default=1, ge=1, le=1)
    theme: MobileTheme = Field(default_factory=MobileTheme)
    banners_enabled: bool = True
    sections: list[Section] = Field(default_factory=lambda: [Section.model_validate(s) for s in DEFAULT_SECTIONS],
                                    min_length=1, max_length=40)
    texts: dict[str, Label] = Field(default_factory=dict)
    # Replacements of the app strings (keys of mobile/l10n/user.json); an empty language keeps the app text.
    strings: dict[str, LongText] = Field(default_factory=dict)
    features: dict[str, bool] = Field(default_factory=lambda: {k: True for k in FEATURES})
    # Fixed links the actions use; empty values hide the buttons that need them.
    cabinet_url: str = Field(default="", max_length=1024)
    telegram_channel: str = Field(default="", max_length=1024)
    _urls = field_validator("cabinet_url", "telegram_channel")(classmethod(lambda cls, v: _safe_url(v)))

    @field_validator("texts")
    @classmethod
    def known_texts(cls, value):
        unknown = sorted(set(value) - set(DEFAULT_TEXTS))
        if unknown:
            raise ValueError("Неизвестные тексты: " + ", ".join(unknown[:5]))
        return value

    @field_validator("strings")
    @classmethod
    def known_strings(cls, value):
        unknown = sorted(set(value) - set(app_strings()))
        if unknown:
            raise ValueError("Неизвестные строки приложения: " + ", ".join(unknown[:5]))
        if any(len(getattr(v, lang)) > 300 for v in value.values() for lang in LANGS):
            raise ValueError("Строка приложения длиннее 300 символов")
        return {k: v for k, v in value.items() if v.ru.strip() or v.en.strip() or v.uk.strip()}

    @field_validator("features")
    @classmethod
    def known_features(cls, value):
        unknown = sorted(set(value) - set(FEATURES))
        if unknown:
            raise ValueError("Неизвестные функции: " + ", ".join(unknown[:5]))
        return {**{k: True for k in FEATURES}, **value}

    @model_validator(mode="after")
    def consistent(self):
        ids = [s.id for s in self.sections]
        if len(ids) != len(set(ids)):
            raise ValueError("Повторяется id раздела")
        tabs = [s for s in self.sections if s.tab and s.enabled]
        if not 2 <= len(tabs) <= 5:
            raise ValueError("В нижней панели должно быть от 2 до 5 включённых разделов")
        if not any(s.kind == "vpn" and s.enabled for s in self.sections):
            raise ValueError("Раздел VPN нельзя выключить: без него приложение не подключит клиента")
        known = set(ids)
        for section in self.sections:
            for button in section.buttons:
                if button.action == "open" and button.target not in known:
                    raise ValueError(f"Кнопка {section.id}/{button.id} открывает несуществующий раздел «{button.target}»")
        return self


def defaults() -> MobileLayout:
    return MobileLayout()


async def load(db: AsyncSession) -> MobileLayout:
    row = await db.get(AppSetting, SETTING_KEY)
    if not row or not row.value:
        return defaults()
    try:
        return MobileLayout.model_validate(json.loads(row.value))
    except (ValueError, ValidationError) as exc:
        # A broken stored value must not take the apps down: fall back to the defaults.
        logger.warning("stored mobile_layout is invalid, defaults are used: %s", exc)
        return defaults()


def pick_lang(raw: str | None) -> str:
    raw = (raw or "ru").lower()
    if raw.startswith(("uk", "ua")):
        return "uk"
    return "en" if raw.startswith("en") else "ru"


async def _banner_urls(db: AsyncSession, keys: set[str], enabled: bool) -> dict[str, str]:
    from .bot_banners import ENABLED_KEY, _public_url, load_state, resolve
    if not enabled or not keys:
        return {}
    # The bot-wide switch «Показывать баннеры в боте» does not hide the app banners: the layout has its own.
    state = {k: v for k, v in (await load_state(db)).items() if k != ENABLED_KEY}
    out = {}
    for key in keys:
        source, _, url = resolve(key, state)
        if source in {"custom", "default"}:
            out[key] = _public_url(key, source, url)
    return out


def resolve_static(layout: MobileLayout, lang: str, urls: dict[str, str]) -> dict:
    """The layout for one language, exactly as the apps draw it (``urls``: banner key → URL)."""
    texts = {k: (layout.texts[k].pick(lang) if k in layout.texts else (v.get(lang) or v["ru"])) for k, v in DEFAULT_TEXTS.items()}
    links = {"cabinet": layout.cabinet_url, "telegram_channel": layout.telegram_channel}
    sections = []
    for s in layout.sections:
        if not s.enabled:
            continue
        banner = None
        if layout.banners_enabled and s.banner.enabled and urls.get(s.banner.key):
            banner = {"url": urls[s.banner.key], "link": s.banner.link}
        buttons = []
        for b in s.buttons:
            if not b.visible:
                continue
            if b.action in ("cabinet", "telegram_channel") and not links[b.action]:
                continue  # the administrator has not set the link yet
            buttons.append({"id": b.id, "label": b.label.pick(lang), "action": b.action, "target": b.target,
                            "style": b.style, "icon": b.icon, "audience": b.audience})
        sections.append({"id": s.id, "kind": s.kind, "tab": s.tab, "title": s.title.pick(lang),
                         "subtitle": s.subtitle.pick(lang), "body": s.body.pick(lang), "icon": s.icon,
                         "banner": banner, "buttons": buttons})
    # Only the language the administrator filled: an English app never shows a Russian replacement.
    strings = {k: getattr(v, lang).strip() for k, v in layout.strings.items() if getattr(v, lang).strip()}
    doc = {"schema": 1, "lang": lang, "theme": layout.theme.model_dump(), "texts": texts, "strings": strings,
           "features": {**{k: True for k in FEATURES}, **layout.features},
           "tabs": [s["id"] for s in sections if s["tab"]], "sections": sections, "links": links}
    doc["version"] = hashlib.sha256(json.dumps(doc, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
    return doc


def bundled_defaults() -> dict:
    """The default layout in every language with the default Lusi banners.

    The apps ship this document (``assets/default_layout.json``, ``VpnShopUser/default_layout.json``)
    and draw it before the first answer of the shop and when the shop is unreachable.
    """
    layout = defaults()
    urls = {s.banner.key: f"/api/bot/banners/default/{s.banner.key}.jpg" for s in layout.sections if s.banner.key}
    return {lang: resolve_static(layout, lang, urls) for lang in LANGS}


async def resolve_layout(db: AsyncSession, lang: str) -> dict:
    layout = await load(db)
    keys = {s.banner.key for s in layout.sections if s.enabled and s.banner.enabled and s.banner.key}
    return resolve_static(layout, lang, await _banner_urls(db, keys, layout.banners_enabled))


@router.get("/api/mobile/layout")
async def mobile_layout(request: Request, response: Response, lang: str = "ru", db: AsyncSession = Depends(get_db)):
    doc = await resolve_layout(db, pick_lang(lang))
    etag = f'"{doc["version"]}"'
    # Clients revalidate on every start; an unchanged layout costs a 304 without a body.
    headers = {"Cache-Control": "no-cache", "ETag": etag}
    if request.headers.get("If-None-Match") == etag:
        return Response(status_code=304, headers=headers)
    response.headers.update(headers)
    return doc


@router.get("/api/admin/mobile-layout")
async def admin_mobile_layout(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("read"))):
    from .bot_banners import SECTIONS as BANNER_SECTIONS
    layout = await load(db)
    return {"layout": layout.model_dump(mode="json"), "defaults": defaults().model_dump(mode="json"),
            "actions": ACTIONS, "import_apps": list(IMPORT_APPS), "documents": {k: v for k, v in zip(DOCUMENTS, ("Частые вопросы", "Правила", "Политика конфиденциальности", "Публичная оферта"))}, "icons": list(ICONS), "kinds": list(KINDS),
            "texts": DEFAULT_TEXTS, "strings": app_strings(), "features": FEATURES, "banner_keys": {k: v[0] for k, v in BANNER_SECTIONS.items()},
            "preview": {lang: await resolve_layout(db, lang) for lang in LANGS}}


@router.put("/api/admin/mobile-layout")
async def admin_mobile_layout_save(payload: MobileLayout, db: AsyncSession = Depends(get_db),
                                   admin=Depends(require_permission("manage_content"))):
    from .bot_banners import valid_key
    from .main import audit
    bad = sorted({s.banner.key for s in payload.sections if s.banner.key and not valid_key(s.banner.key)})
    if bad:
        raise HTTPException(422, "Неизвестные баннеры: " + ", ".join(bad))
    row = await db.get(AppSetting, SETTING_KEY)
    value = payload.model_dump_json()
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=SETTING_KEY, value=value))
    await audit(db, "content.mobile_layout.updated", admin.email, None,
                {"sections": len(payload.sections), "buttons": sum(len(s.buttons) for s in payload.sections)})
    await db.commit()
    return {"ok": True, "preview": await resolve_layout(db, "ru")}


@router.delete("/api/admin/mobile-layout")
async def admin_mobile_layout_reset(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("manage_content"))):
    from .main import audit
    row = await db.get(AppSetting, SETTING_KEY)
    if row:
        row.value = ""
    await audit(db, "content.mobile_layout.reset", admin.email)
    await db.commit()
    return {"ok": True}
