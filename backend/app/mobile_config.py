"""Everything the Android and iOS customer apps show, edited in «Бот и кабинет → Приложения»
(v28.31.0).

The apps build their screens from ``GET /api/mobile/config?lang=ru|en|uk``: look, bottom tabs,
home screen blocks and buttons, sign-in screen, plans comparison, support contacts, profile
items and promo cards. Shop data (plans, documents, Mini App promos and theme) is merged in,
so one request is enough and the app can keep the last answer for offline use.

Administrator settings live in ``app_settings.mobile_config`` and are validated by
:class:`MobileConfig`; every save is audited. Texts are given per language (ru required,
en/uk fall back to ru).
"""
from __future__ import annotations

import hashlib
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from .app_config import COLOR, Icon, PromoCard, _safe_url
from .db import get_db
from .models import AppSetting
from .security import require_permission

router = APIRouter()
SETTING_KEY = "mobile_config"
LANGS = ("ru", "en", "uk")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Text(_Strict):
    """One text in three languages; English and Ukrainian fall back to Russian."""
    ru: str = Field(default="", max_length=300)
    en: str = Field(default="", max_length=300)
    uk: str = Field(default="", max_length=300)

    def get(self, lang: str) -> str:
        return (getattr(self, lang, "") or self.ru).strip()


def T(ru: str, en: str = "", uk: str = "") -> Text:
    return Text(ru=ru, en=en, uk=uk)


class Look(_Strict):
    app_name: str = Field(default="", max_length=40, description="Пусто — название магазина")
    logo_url: str = Field(default="", max_length=1024)
    mode: Literal["dark", "light", "system"] = "dark"
    use_miniapp_colors: bool = False
    accent: str = Field(default="#8a79ff", pattern=COLOR)
    accent_2: str = Field(default="#5cc8ff", pattern=COLOR)
    background: str = Field(default="#0c1021", pattern=COLOR)
    surface: str = Field(default="#161b30", pattern=COLOR)
    text: str = Field(default="#eef1ff", pattern=COLOR)
    muted: str = Field(default="#a4afd0", pattern=COLOR)
    radius: int = Field(default=22, ge=0, le=40)

    @field_validator("logo_url")
    @classmethod
    def https(cls, value):
        value = (value or "").strip()
        if value and not (value.startswith("https://") or value.startswith("/media/")):
            raise ValueError("Логотип — ссылка https:// или файл /media/…")
        return value


TabId = Literal["home", "plans", "profile", "support", "servers", "info", "wallet", "family", "status", "devices", "referral"]
TAB_ICONS = {"home": "shield", "plans": "zap", "profile": "users", "support": "help", "servers": "globe", "info": "info",
             "wallet": "wallet", "family": "heart", "status": "server", "devices": "smartphone", "referral": "gift"}
TAB_TITLES = {
    "home": T("VPN", "VPN", "VPN"), "plans": T("Тарифы", "Plans", "Тарифи"), "profile": T("Профиль", "Profile", "Профіль"),
    "support": T("Поддержка", "Support", "Підтримка"), "servers": T("Локации", "Locations", "Локації"),
    "info": T("Информация", "Information", "Інформація"), "wallet": T("Кошелёк", "Wallet", "Гаманець"),
    "family": T("Семья", "Family", "Сім'я"), "status": T("Статус", "Status", "Статус"),
    "devices": T("Устройства", "Devices", "Пристрої"), "referral": T("Друзья", "Friends", "Друзі"),
}


class Tab(_Strict):
    id: TabId
    enabled: bool = True
    title: Text = Field(default_factory=Text)
    icon: Icon | Literal[""] = ""


def _default_tabs() -> list[Tab]:
    return [Tab(id="home"), Tab(id="plans"), Tab(id="profile"), Tab(id="support"),
            Tab(id="servers", enabled=False), Tab(id="info", enabled=False), Tab(id="wallet", enabled=False),
            Tab(id="family", enabled=False), Tab(id="status", enabled=False), Tab(id="devices", enabled=False),
            Tab(id="referral", enabled=False)]


ButtonAction = Literal["link", "section", "telegram_bot", "telegram_channel", "support", "connect", "plans"]


class Button(_Strict):
    id: str = Field(pattern=r"^[a-z0-9_-]{1,32}$")
    enabled: bool = True
    title: Text
    subtitle: Text = Field(default_factory=Text)
    icon: Icon = "send"
    action: ButtonAction = "link"
    target: str = Field(default="", max_length=1024, description="Ссылка, раздел (home, plans…) или канал @name")
    style: Literal["primary", "secondary", "accent"] = "secondary"
    placement: Literal["home", "profile", "support"] = "home"

    @model_validator(mode="after")
    def target_fits(self):
        if self.action == "link":
            if not self.target.startswith(("https://", "tg://")):
                raise ValueError(f"Кнопка «{self.title.ru}»: ссылка должна начинаться с https:// или tg://")
            _safe_url(self.target)
        elif self.action == "section" and self.target not in TAB_TITLES:
            raise ValueError(f"Кнопка «{self.title.ru}»: раздел — один из {', '.join(TAB_TITLES)}")
        elif self.action == "telegram_channel" and not (self.target.startswith("@") or self.target.startswith("https://t.me/")):
            raise ValueError(f"Кнопка «{self.title.ru}»: канал — @имя или https://t.me/…")
        return self


BlockKind = Literal["notice", "connect", "usage", "server", "promo", "buttons", "trial"]


class Block(_Strict):
    kind: BlockKind
    enabled: bool = True


class Home(_Strict):
    blocks: list[Block] = Field(default_factory=lambda: [Block(kind=k) for k in ("notice", "connect", "usage", "server", "promo", "buttons", "trial")],
                                max_length=12)
    notice: Text = Field(default_factory=Text, description="Строка-объявление сверху; пусто — не показывать")
    notice_link: str = Field(default="", max_length=1024)
    connect_title: Text = Field(default_factory=lambda: T("Подключить", "Connect", "Підключити"))
    connected_title: Text = Field(default_factory=lambda: T("Подписка активна", "Subscription active", "Підписка активна"))
    disconnected_title: Text = Field(default_factory=lambda: T("Подписка не активна", "No active subscription", "Підписка не активна"))
    connect_hint: Text = Field(default_factory=lambda: T("Нажмите, чтобы добавить подписку в приложение VPN",
                                                          "Tap to add the subscription to your VPN app", "Натисніть, щоб додати підписку в застосунок VPN"))
    preferred_client: Literal["auto", "happ", "v2rayng", "hiddify", "streisand", "v2raytun"] = "auto"

    _link = field_validator("notice_link")(classmethod(lambda cls, v: _safe_url(v)))


LoginMethod = Literal["telegram", "yandex", "vk", "google", "email", "passkey"]


class Login(_Strict):
    title: Text = Field(default_factory=lambda: T("Войдите или зарегистрируйтесь", "Sign in or create an account", "Увійдіть або зареєструйтеся"))
    subtitle: Text = Field(default_factory=lambda: T("Один аккаунт для приложения, бота и личного кабинета",
                                                      "One account for the app, the bot and the web cabinet", "Один акаунт для застосунку, бота й кабінету"))
    methods: list[LoginMethod] = Field(default_factory=lambda: ["telegram", "yandex", "google", "vk", "email", "passkey"], min_length=1, max_length=6)
    show_legal: bool = True
    legal_text: Text = Field(default_factory=lambda: T("Создавая аккаунт, вы соглашаетесь с политикой конфиденциальности и офертой",
                                                        "By creating an account you accept the privacy policy and the offer",
                                                        "Створюючи акаунт, ви погоджуєтеся з політикою конфіденційності та офертою"))

    @field_validator("methods")
    @classmethod
    def unique(cls, value):
        return list(dict.fromkeys(value))


class CompareRow(_Strict):
    label: Text
    trial: str = Field(default="", max_length=40)
    paid: str = Field(default="", max_length=40)


class Plans(_Strict):
    title: Text = Field(default_factory=lambda: T("Получите все преимущества", "Get every benefit", "Отримайте всі переваги"))
    subtitle: Text = Field(default_factory=Text)
    trial_label: Text = Field(default_factory=lambda: T("Пробный", "Trial", "Пробний"))
    paid_label: Text = Field(default_factory=lambda: T("Премиум", "Premium", "Преміум"))
    compare: list[CompareRow] = Field(default_factory=list, max_length=10)
    footnote: Text = Field(default_factory=lambda: T("Оплачивая, вы соглашаетесь с офертой и политикой конфиденциальности",
                                                      "By paying you accept the offer and the privacy policy",
                                                      "Оплачуючи, ви погоджуєтеся з офертою та політикою конфіденційності"))
    highlight_plan_id: int | None = Field(default=None, ge=1)


class Support(_Strict):
    title: Text = Field(default_factory=lambda: T("Поддержка", "Support", "Підтримка"))
    show_faq: bool = True
    ticket_form: bool = True
    chat_title: Text = Field(default_factory=lambda: T("Чат поддержки", "Support chat", "Чат підтримки"))
    chat_text: Text = Field(default_factory=lambda: T("Ответим в приложении", "We reply in the app", "Відповімо в застосунку"))


ProfileItem = Literal["email", "telegram", "id", "subscription", "devices", "family", "referral", "wallet", "language", "documents", "logout"]


class Profile(_Strict):
    items: list[ProfileItem] = Field(default_factory=lambda: ["email", "telegram", "id", "subscription", "devices", "family", "referral", "language", "documents", "logout"],
                                     max_length=11)
    referral_title: Text = Field(default_factory=lambda: T("Приглашайте друзей", "Invite friends", "Запрошуйте друзів"))
    referral_text: Text = Field(default_factory=lambda: T("Получайте бонус за каждого друга, который оплатит подписку",
                                                           "Get a bonus for every friend who pays for a subscription",
                                                           "Отримуйте бонус за кожного друга, який оплатить підписку"))


class Promos(_Strict):
    source: Literal["miniapp", "own", "off"] = "miniapp"
    cards: list[PromoCard] = Field(default_factory=list, max_length=6)


class MobileConfig(_Strict):
    look: Look = Field(default_factory=Look)
    tabs: list[Tab] = Field(default_factory=_default_tabs, min_length=1, max_length=11)
    home: Home = Field(default_factory=Home)
    buttons: list[Button] = Field(default_factory=list, max_length=12)
    login: Login = Field(default_factory=Login)
    plans: Plans = Field(default_factory=Plans)
    support: Support = Field(default_factory=Support)
    profile: Profile = Field(default_factory=Profile)
    promos: Promos = Field(default_factory=Promos)

    @field_validator("tabs")
    @classmethod
    def tabs_ok(cls, value):
        ids = [t.id for t in value]
        if len(ids) != len(set(ids)):
            raise ValueError("Вкладки не должны повторяться")
        on = [t for t in value if t.enabled]
        if not 2 <= len(on) <= 5:
            raise ValueError("Включите от двух до пяти вкладок нижней панели")
        if "home" not in [t.id for t in on]:
            raise ValueError("Вкладка «VPN» (home) должна быть включена")
        return value

    @field_validator("buttons")
    @classmethod
    def unique_buttons(cls, value):
        ids = [b.id for b in value]
        if len(ids) != len(set(ids)):
            raise ValueError("ID кнопок не должны повторяться")
        return value


async def load(db: AsyncSession) -> MobileConfig:
    row = await db.get(AppSetting, SETTING_KEY)
    if not row or not row.value:
        return MobileConfig()
    try:
        return MobileConfig.model_validate_json(row.value)
    except Exception:
        return MobileConfig()


def _lang(request: Request | None, lang: str | None) -> str:
    if lang in LANGS:
        return lang
    header = ((request.headers.get("accept-language") if request is not None else "") or "ru")[:2].lower()
    return header if header in LANGS else "ru"


def _button(b: Button, lang: str, bot: str) -> dict:
    target = b.target
    if b.action == "telegram_bot":
        target = f"https://t.me/{bot}" if bot else ""
    elif b.action == "telegram_channel" and target.startswith("@"):
        target = "https://t.me/" + target[1:]
    elif b.action == "support":
        target = f"https://t.me/{bot}?start=support" if bot else ""
    return {"id": b.id, "title": b.title.get(lang), "subtitle": b.subtitle.get(lang), "icon": b.icon, "action": b.action,
            "target": target, "style": b.style, "placement": b.placement}


async def build(db: AsyncSession, request: Request | None = None, lang: str | None = None) -> dict:
    """The document the apps render, in one language, with shop data merged in."""
    from .app_config import build_config
    from .config import settings
    from .info_pages import load as load_doc, localized, published
    from .mobile_oauth import available_providers
    cfg = await load(db)
    lang = _lang(request, lang)
    shop = await build_config(db, None)
    bot = settings.bot_username or ""
    look = cfg.look
    colors = {"accent": look.accent, "accent_2": look.accent_2, "background": look.background, "surface": look.surface,
              "text": look.text, "muted": look.muted}
    if look.use_miniapp_colors:
        v = shop["theme"]["vars"]
        colors = {"accent": v["--cfg-accent"], "accent_2": v["--cfg-accent-2"], "background": v["--cfg-bg"], "surface": v["--cfg-surface"],
                  "text": v["--cfg-text"], "muted": v["--cfg-muted"]}
    ready = set(available_providers()) | {"email", "passkey"}
    docs = await published(db, lang)
    faq = localized("faq", await load_doc(db, "faq"), lang) if cfg.support.show_faq else None
    promos = shop["promos"] if cfg.promos.source == "miniapp" else [] if cfg.promos.source == "off" else [p.model_dump(mode="json") for p in cfg.promos.cards]
    out = {
        "schema": 1,
        "lang": lang,
        "look": {"app_name": look.app_name or shop["brand"]["name"], "logo_url": look.logo_url, "mode": look.mode, "radius": look.radius, "colors": colors},
        "tabs": [{"id": t.id, "title": t.title.get(lang) or TAB_TITLES[t.id].get(lang), "icon": t.icon or TAB_ICONS[t.id]} for t in cfg.tabs if t.enabled],
        "home": {"blocks": [b.kind for b in cfg.home.blocks if b.enabled], "notice": cfg.home.notice.get(lang), "notice_link": cfg.home.notice_link,
                 "connect_title": cfg.home.connect_title.get(lang), "connected_title": cfg.home.connected_title.get(lang),
                 "disconnected_title": cfg.home.disconnected_title.get(lang), "connect_hint": cfg.home.connect_hint.get(lang),
                 "preferred_client": cfg.home.preferred_client},
        "buttons": [_button(b, lang, bot) for b in cfg.buttons if b.enabled],
        "login": {"title": cfg.login.title.get(lang), "subtitle": cfg.login.subtitle.get(lang),
                  "methods": [m for m in cfg.login.methods if m in ready],
                  "legal": cfg.login.legal_text.get(lang) if cfg.login.show_legal else "",
                  "legal_links": [{"kind": d["kind"], "title": d["title"]} for d in docs if d["kind"] in ("privacy", "offer")]},
        "plans": {"title": cfg.plans.title.get(lang), "subtitle": cfg.plans.subtitle.get(lang), "trial_label": cfg.plans.trial_label.get(lang),
                  "paid_label": cfg.plans.paid_label.get(lang), "compare": [{"label": r.label.get(lang), "trial": r.trial, "paid": r.paid} for r in cfg.plans.compare],
                  "footnote": cfg.plans.footnote.get(lang), "highlight_plan_id": cfg.plans.highlight_plan_id, "items": shop["plans"],
                  "currency": shop["brand"]["currency"], "trial_days": shop.get("trial_days")},
        "support": {"title": cfg.support.title.get(lang), "ticket_form": cfg.support.ticket_form, "chat_title": cfg.support.chat_title.get(lang),
                    "chat_text": cfg.support.chat_text.get(lang), "faq": (faq or {}).get("items", []) if faq else [],
                    "faq_text": (faq or {}).get("body", "") if faq else ""},
        "profile": {"items": cfg.profile.items, "referral_title": cfg.profile.referral_title.get(lang), "referral_text": cfg.profile.referral_text.get(lang)},
        "documents": [{"kind": d["kind"], "title": d["title"]} for d in docs],
        "promos": promos,
        "bot_username": bot,
        "auth_scheme": settings.mobile_auth_scheme,
    }
    out["version"] = hashlib.sha256(json.dumps(out, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()[:16]
    return out


@router.get("/api/mobile/config")
async def mobile_config(request: Request, response: Response, lang: str | None = None, db: AsyncSession = Depends(get_db)):
    out = await build(db, request, lang)
    etag = f'"{out["version"]}"'
    response.headers["Cache-Control"] = "no-cache"
    response.headers["ETag"] = etag
    if request.headers.get("If-None-Match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    return out


@router.get("/api/admin/mobile-config")
async def admin_get(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("read"))):
    from .mobile_oauth import available_providers
    cfg = await load(db)
    return {"config": cfg.model_dump(mode="json"), "defaults": MobileConfig().model_dump(mode="json"),
            "providers": available_providers(), "preview": {lang: await build(db, None, lang) for lang in LANGS}}


@router.put("/api/admin/mobile-config")
async def admin_save(payload: MobileConfig, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("manage_content"))):
    from .main import audit
    row = await db.get(AppSetting, SETTING_KEY)
    value = payload.model_dump_json()
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=SETTING_KEY, value=value))
    await audit(db, "mobile_config.saved", admin.email, None, {"tabs": [t.id for t in payload.tabs if t.enabled], "buttons": len(payload.buttons)})
    await db.commit()
    return {"ok": True, "preview": await build(db, None, "ru")}


@router.delete("/api/admin/mobile-config")
async def admin_reset(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("manage_content"))):
    from .main import audit
    row = await db.get(AppSetting, SETTING_KEY)
    if row:
        await db.delete(row)
    await audit(db, "mobile_config.reset", admin.email)
    await db.commit()
    return {"ok": True}
