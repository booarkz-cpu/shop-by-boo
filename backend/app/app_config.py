"""Data-driven Mini App configuration: GET /api/app-config.

The Mini App (and the web cabinet) render their theme, navigation, section banners, promo
cards, server categories, wallet amounts and payment methods, referral terms, support
buttons, info pages and the offer consent from one JSON document. It is assembled from
live shop data (plans, promotions, advertisements, cabinet menu, published pages, payment
agents) plus administrator overrides stored in ``app_settings.app_config``.

* ``GET /api/app-config`` — public; with a valid ``X-Telegram-Init-Data`` header the
  response also carries ``viewer`` (first name, username, language) for the greeting.
* ``GET/PUT/DELETE /api/admin/app-config`` — overrides, validated by :class:`Overrides`.
* ``GET/POST /api/me/consent`` — offer acceptance; :func:`require_consent` blocks
  checkout, top-ups and wallet purchases when the administrator requires it.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import get_db
from .models import AppSetting, UserConsent
from .security import require_permission

logger = logging.getLogger(__name__)
router = APIRouter()
SETTING_KEY = "app_config"

ICONS = ("home", "zap", "shield", "server", "wallet", "users", "gift", "help", "message", "send", "phone", "mail",
         "card", "sbp", "crypto", "star", "globe", "flag", "info", "file", "lock", "list", "trophy", "smartphone",
         "plug", "receipt", "bell", "key", "sparkles", "rocket", "heart", "clock")
Icon = Literal[ICONS]  # type: ignore[valid-type]
COLOR = r"^#[0-9a-fA-F]{6}$"

# Mini App section kind → banner key (app/assets/bot_banners/<key>.jpg or an admin upload).
SECTION_BANNERS = {
    "overview": "home", "plans": "buy", "trial": "trial", "connection": "connection", "servers": "servers",
    "wallet": "topup", "subscription": "subscription", "payments": "payments", "gifts": "gifts",
    "referral": "referral", "support": "support", "devices": "devices", "surveys": "surveys",
    "giveaways": "gifts", "security": "account", "notifications": "menu", "partner": "referral", "info": "info",
}
NAV_ICONS = {
    "overview": "home", "plans": "zap", "trial": "sparkles", "connection": "plug", "servers": "server",
    "wallet": "wallet", "subscription": "shield", "payments": "receipt", "gifts": "gift", "referral": "users",
    "support": "help", "devices": "smartphone", "surveys": "list", "giveaways": "trophy", "security": "key",
    "notifications": "bell", "partner": "users", "info": "info", "custom": "file",
}

DEFAULT_TEXTS = {
    "greeting": "Привет, {name}!",
    "greeting_anonymous": "Добро пожаловать!",
    "home_subtitle": "Ваш VPN под защитой корги Люси",
    "promo_title": "Акции",
    "promo_ends_in": "До конца акции",
    "subscription_title": "Подписка",
    "servers_title": "Серверы",
    "servers_empty": "Список серверов пока недоступен",
    "wallet_title": "Пополнение баланса",
    "wallet_balance": "Баланс",
    "wallet_amount": "Сумма пополнения",
    "wallet_method": "Способ оплаты",
    "wallet_pay": "Пополнить",
    "wallet_code": "Промокод или подарочная карта",
    "wallet_code_apply": "Активировать",
    "referral_title": "Пригласи друзей",
    "referral_link": "Ваша ссылка-приглашение",
    "referral_copy": "Скопировать ссылку",
    "support_title": "Поддержка",
    "support_subtitle": "Выберите удобный способ связи",
    "info_title": "Информация",
    "consent_title": "Условия использования",
    "consent_accept": "Принимаю",
    "offline": "Нет связи с сервером — показаны сохранённые данные",
    "retry": "Повторить",
    "error": "Не удалось загрузить приложение",
}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Theme(_Strict):
    accent: str = Field(default="#39ff88", pattern=COLOR)
    accent_2: str = Field(default="#22d3ee", pattern=COLOR)
    background: str = Field(default="#070b12", pattern=COLOR)
    surface: str = Field(default="#0e1522", pattern=COLOR)
    text: str = Field(default="#e8f1ff", pattern=COLOR)
    muted: str = Field(default="#8a99b3", pattern=COLOR)
    danger: str = Field(default="#ff5c7a", pattern=COLOR)
    radius: int = Field(default=16, ge=0, le=32)


def _safe_url(value: str) -> str:
    value = (value or "").strip()
    if value and not re.match(r"^(https://|tg://|#[a-z0-9/_-]*$)", value):
        raise ValueError("Ссылка должна начинаться с https://, tg:// или #раздел")
    return value


class PromoCard(_Strict):
    id: str = Field(pattern=r"^[a-z0-9_-]{1,32}$")
    title: str = Field(min_length=1, max_length=80)
    text: str = Field(default="", max_length=300)
    discount: str = Field(default="", max_length=16)
    ends_at: datetime | None = None
    button_text: str = Field(default="", max_length=40)
    link: str = Field(default="#plans", max_length=1024)
    _link = field_validator("link")(classmethod(lambda cls, v: _safe_url(v)))


class ServerCategory(_Strict):
    id: str = Field(pattern=r"^[a-z0-9_-]{1,32}$")
    title: str = Field(min_length=1, max_length=60)
    icon: Icon = "globe"
    countries: list[str] = Field(default_factory=list, max_length=60)
    match: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("countries")
    @classmethod
    def iso(cls, value):
        out = [x.strip().upper() for x in value if x.strip()]
        if any(not re.fullmatch(r"[A-Z]{2}", x) for x in out):
            raise ValueError("Коды стран — две латинские буквы (DE, NL, US)")
        return out

    @field_validator("match")
    @classmethod
    def words(cls, value):
        return [x.strip()[:40] for x in value if x.strip()]


class Servers(_Strict):
    categories: list[ServerCategory] = Field(default_factory=list, max_length=12)
    show_load: bool = True


class PaymentMethod(_Strict):
    id: str = Field(pattern=r"^[a-z0-9_-]{1,32}$")
    title: str = Field(min_length=1, max_length=40)
    icon: Icon = "card"
    provider: Literal["yookassa", "platega", "rollypay", "sandbox", "telegram_stars"]
    # YooKassa payment_method_data.type, for example "sbp" or "bank_card".
    yookassa_method: Literal["", "bank_card", "sbp", "yoo_money", "sberbank", "tinkoff_bank"] = ""


class Stars(_Strict):
    enabled: bool = False
    rate: Decimal = Field(default=Decimal("1.50"), gt=0, le=1000, description="Сколько единиц валюты магазина даёт 1 Star")
    min_stars: int = Field(default=50, ge=1, le=10000)


class Wallet(_Strict):
    amounts: list[int] = Field(default_factory=lambda: [100, 250, 500, 1000, 2000], max_length=8)
    methods: list[PaymentMethod] = Field(default_factory=list, max_length=8)
    stars: Stars = Field(default_factory=Stars)

    @field_validator("amounts")
    @classmethod
    def bounds(cls, value):
        if any(x < 50 or x > 100000 for x in value):
            raise ValueError("Суммы пополнения — от 50 до 100000")
        return sorted(set(value))


class Referral(_Strict):
    conditions: str = Field(default="Приглашайте друзей по своей ссылке и получайте процент с каждой их оплаты. Начисления можно потратить на подписку или вывести.", max_length=2000)
    withdraw_enabled: bool = True


class SupportButton(_Strict):
    title: str = Field(min_length=1, max_length=40)
    icon: Icon = "message"
    link: str = Field(max_length=1024)
    _link = field_validator("link")(classmethod(lambda cls, v: _safe_url(v)))


class Support(_Strict):
    buttons: list[SupportButton] = Field(default_factory=list, max_length=8)
    ticket_form: bool = True


class InfoPage(_Strict):
    slug: str = Field(pattern=r"^[a-z0-9-]{1,80}$")
    title: str = Field(min_length=1, max_length=80)
    kind: Literal["faq", "rules", "privacy", "offer", "other"] = "other"


class Info(_Strict):
    pages: list[InfoPage] = Field(default_factory=list, max_length=12)
    include_published_legal: bool = True


class Consent(_Strict):
    enabled: bool = False
    required_for_payment: bool = True
    version: str = Field(default="1", pattern=r"^[A-Za-z0-9._-]{1,64}$")
    text: str = Field(default="Я прочитал(а) и принимаю условия публичной оферты", min_length=1, max_length=300)
    page_slug: str = Field(default="offer", pattern=r"^[a-z0-9-]{1,80}$")


class Overrides(_Strict):
    theme: Theme = Field(default_factory=Theme)
    texts: dict[str, str] = Field(default_factory=dict)
    banners_enabled: bool = True
    promo_cards: list[PromoCard] = Field(default_factory=list, max_length=10)
    servers: Servers = Field(default_factory=Servers)
    wallet: Wallet = Field(default_factory=Wallet)
    referral: Referral = Field(default_factory=Referral)
    support: Support = Field(default_factory=Support)
    info: Info = Field(default_factory=Info)
    consent: Consent = Field(default_factory=Consent)

    @field_validator("texts")
    @classmethod
    def known_texts(cls, value):
        unknown = sorted(set(value) - set(DEFAULT_TEXTS))
        if unknown:
            raise ValueError("Неизвестные тексты: " + ", ".join(unknown[:5]))
        if any(len(v) > 300 for v in value.values()):
            raise ValueError("Текст длиннее 300 символов")
        return {k: v for k, v in value.items() if v.strip()}


async def load_overrides(db: AsyncSession) -> Overrides:
    row = await db.get(AppSetting, SETTING_KEY)
    if not row or not row.value:
        return Overrides()
    try:
        return Overrides.model_validate(json.loads(row.value))
    except (ValueError, ValidationError) as exc:
        # A broken stored value must not take the Mini App down: fall back to defaults.
        logger.warning("stored app_config is invalid, defaults are used: %s", exc)
        return Overrides()


def _flag(country: str) -> str:
    code = (country or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{2}", code):
        return ""
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in code)


def _info_kind(slug: str) -> str:
    s = slug.lower()
    for kind, words in (("offer", ("offer", "oferta", "terms-of-sale")), ("privacy", ("privacy", "personal", "konfid")),
                        ("faq", ("faq", "help", "voprosy")), ("rules", ("rules", "terms", "pravila"))):
        if any(w in s for w in words):
            return kind
    return "other"


def _viewer(request: Request) -> dict | None:
    raw = request.headers.get("X-Telegram-Init-Data", "")
    if not raw or len(raw) > 4096:
        return None
    from .main import telegram_user_from_init_data
    try:
        user = telegram_user_from_init_data(raw)
    except HTTPException:
        return None
    return {"first_name": str(user.get("first_name") or "")[:64], "username": str(user.get("username") or "")[:64],
            "language": str(user.get("language_code") or "")[:8]}


async def _banners(db: AsyncSession, enabled: bool) -> dict[str, str]:
    from .bot_banners import _public_url, load_state, resolve
    if not enabled:
        return {}
    state = await load_state(db)
    out = {}
    for kind, key in SECTION_BANNERS.items():
        source, _, url = resolve(key, state)
        if source in {"custom", "default"}:
            out[kind] = _public_url(key, source, url)
    return out


def _promos(plans: list[dict], ads, overrides: Overrides, currency: str) -> list[dict]:
    cards, seen = [], set()
    for plan in plans:
        promo = plan.get("promotion")
        if not promo or promo["id"] in seen:
            continue
        seen.add(promo["id"])
        discount = f"-{promo['value']:g}%" if promo["kind"] == "percent" else f"-{promo['value']:g} {currency}"
        cards.append({"id": f"promotion-{promo['id']}", "title": promo["name"], "text": promo.get("description") or "",
                      "discount": discount, "ends_at": promo.get("ends_at"), "button_text": "Выбрать тариф", "link": "#plans"})
    for ad in ads:
        link = ad.button_url if (ad.button_url or "").startswith("https://") else ""
        cards.append({"id": f"ad-{ad.id}", "title": ad.title, "text": ad.text or "", "discount": "",
                      "ends_at": ad.ends_at.isoformat() + "Z" if ad.ends_at else None,
                      "button_text": ad.button_text or "", "link": link, "image": ad.image_url or ""})
    for card in overrides.promo_cards:
        if card.ends_at and card.ends_at.replace(tzinfo=None) < datetime.utcnow():
            continue
        data = card.model_dump(mode="json")
        cards.append(data)
    return cards[:12]


async def build_config(db: AsyncSession, request: Request | None = None) -> dict:
    from . import main
    from .cabinet_api import public_cabinet_menu
    from .content_publishing import catalog
    overrides = await load_overrides(db)
    public = await main.public_config(db)
    plans = await main.plans(db)
    currency = settings.default_currency or "RUB"
    now = datetime.utcnow()
    from .models import Advertisement, Promotion
    ads = [a for a in (await db.execute(select(Advertisement).where(Advertisement.enabled.is_(True)).order_by(Advertisement.sort_order, Advertisement.id))).scalars().all()
           if (not a.starts_at or now >= a.starts_at) and (not a.ends_at or now <= a.ends_at)]
    ends = {p.id: p.ends_at for p in (await db.execute(select(Promotion))).scalars().all()}
    for plan in plans:
        if plan.get("promotion"):
            end = ends.get(plan["promotion"]["id"])
            plan["promotion"]["ends_at"] = end.isoformat() + "Z" if end else None
    menu = await public_cabinet_menu(db)
    banners = await _banners(db, overrides.banners_enabled)
    navigation = [{"slug": m["slug"], "title": m["title"], "kind": m["kind"], "icon": NAV_ICONS.get(m["kind"], "file"),
                   "banner": banners.get(m["kind"], ""), "body": m.get("body", "")} for m in menu]
    if not any(n["kind"] == "info" for n in navigation):
        navigation.append({"slug": "info", "title": "Информация", "kind": "info", "icon": "info", "banner": banners.get("info", ""), "body": ""})

    providers = [str(p) for p in public.get("payment_providers") or []]
    methods = [m.model_dump() for m in overrides.wallet.methods]
    if not methods:
        names = {"yookassa": ("Банковская карта", "card"), "platega": ("СБП", "sbp"), "rollypay": ("Криптовалюта", "crypto"), "sandbox": ("Тестовая оплата", "card")}
        methods = [{"id": p, "title": names[p][0], "icon": names[p][1], "provider": p, "yookassa_method": ""} for p in providers if p in names]
        if "yookassa" in providers:
            methods.insert(1, {"id": "yookassa-sbp", "title": "СБП", "icon": "sbp", "provider": "yookassa", "yookassa_method": "sbp"})
    stars = overrides.wallet.stars
    stars_ready = stars.enabled and bool(settings.bot_token)
    if stars_ready and not any(m["provider"] == "telegram_stars" for m in methods):
        methods.append({"id": "stars", "title": "Telegram Stars", "icon": "star", "provider": "telegram_stars", "yookassa_method": ""})
    for m in methods:
        m["available"] = stars_ready if m["provider"] == "telegram_stars" else m["provider"] in providers

    from .referral_program import percentages
    levels = [str(x) for x in await percentages(db)]
    pages = [p.model_dump() for p in overrides.info.pages]
    if overrides.info.include_published_legal:
        known = {p["slug"] for p in pages}
        for row in await catalog(locale="ru", kind="legal", offset=0, limit=20, db=db):
            if row["slug"] not in known:
                pages.append({"slug": row["slug"], "title": row["title"], "kind": _info_kind(row["slug"])})
    support_buttons = [b.model_dump() for b in overrides.support.buttons]
    if not support_buttons and settings.bot_username:
        support_buttons = [{"title": "Написать в Telegram", "icon": "send", "link": f"https://t.me/{settings.bot_username}?start=support"}]
    theme = overrides.theme
    texts = {**DEFAULT_TEXTS, **overrides.texts}
    config = {
        "schema": 1,
        "brand": {"name": public.get("app_name") or "VPN Shop by Corgi Lusi", "bot_username": settings.bot_username or "",
                  "currency": currency},
        "theme": {"vars": {"--cfg-accent": theme.accent, "--cfg-accent-2": theme.accent_2, "--cfg-bg": theme.background,
                           "--cfg-surface": theme.surface, "--cfg-text": theme.text, "--cfg-muted": theme.muted,
                           "--cfg-danger": theme.danger, "--cfg-radius": f"{theme.radius}px"}},
        "texts": texts,
        "navigation": navigation,
        "banners": banners,
        "promos": _promos(plans, ads, overrides, currency),
        "plans": plans,
        "servers": {"categories": [c.model_dump() for c in overrides.servers.categories], "show_load": overrides.servers.show_load},
        "wallet": {"currency": currency, "amounts": overrides.wallet.amounts, "min": 50, "max": 100000, "methods": methods,
                   "stars": {"enabled": stars_ready, "rate": str(stars.rate), "min_stars": stars.min_stars}},
        "referral": {"conditions": overrides.referral.conditions, "levels": levels, "withdraw_enabled": overrides.referral.withdraw_enabled,
                     "link_template": f"https://t.me/{settings.bot_username}?start=ref_{{code}}" if settings.bot_username else ""},
        "support": {"buttons": support_buttons, "ticket_form": overrides.support.ticket_form},
        "info": {"pages": pages},
        "consent": overrides.consent.model_dump(),
        "trial_days": public.get("trial_days"),
    }
    config["version"] = hashlib.sha256(json.dumps(config, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()[:16]
    config["viewer"] = _viewer(request) if request is not None else None
    return config


@router.get("/api/app-config")
async def app_config(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    response.headers["Cache-Control"] = "private, max-age=30"
    response.headers["Vary"] = "X-Telegram-Init-Data"
    return await build_config(db, request)


# ---------------------------------------------------------------- consent

async def has_consent(db: AsyncSession, user_id: int, consent: Consent) -> bool:
    return bool(await db.scalar(select(UserConsent.id).where(UserConsent.user_id == user_id, UserConsent.document == "offer", UserConsent.version == consent.version)))


async def require_consent(db: AsyncSession, user) -> None:
    """Raise 409 consent_required when the administrator requires the offer before paying."""
    consent = (await load_overrides(db)).consent
    if consent.enabled and consent.required_for_payment and not await has_consent(db, user.id, consent):
        raise HTTPException(409, {"code": "consent_required", "message": "Примите условия публичной оферты, чтобы продолжить оплату", "version": consent.version})


@router.get("/api/me/consent")
async def my_consent(request: Request, db: AsyncSession = Depends(get_db)):
    from .main import user_from_token
    user = await user_from_token(request, db)
    consent = (await load_overrides(db)).consent
    return {"enabled": consent.enabled, "version": consent.version, "accepted": await has_consent(db, user.id, consent)}


class ConsentIn(BaseModel):
    version: str = Field(pattern=r"^[A-Za-z0-9._-]{1,64}$")
    source: Literal["miniapp", "cabinet"] = "miniapp"


@router.post("/api/me/consent")
async def accept_consent(payload: ConsentIn, request: Request, db: AsyncSession = Depends(get_db)):
    from .main import audit, user_from_token
    user = await user_from_token(request, db)
    consent = (await load_overrides(db)).consent
    if payload.version != consent.version:
        raise HTTPException(409, "Условия оферты обновились — откройте их снова")
    if not await has_consent(db, user.id, consent):
        db.add(UserConsent(user_id=user.id, document="offer", version=consent.version, source=payload.source))
        await audit(db, "customer.consent.accepted", f"user:{user.id}", consent.version, {"source": payload.source})
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()  # a parallel request stored the same consent
    return {"accepted": True, "version": consent.version}


# ---------------------------------------------------------------- admin

@router.get("/api/admin/app-config")
async def admin_app_config(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("read"))):
    overrides = await load_overrides(db)
    return {"overrides": overrides.model_dump(mode="json"), "defaults": Overrides().model_dump(mode="json"),
            "texts": DEFAULT_TEXTS, "icons": list(ICONS), "preview": await build_config(db)}


@router.put("/api/admin/app-config")
async def admin_app_config_save(payload: Overrides, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("manage_content"))):
    from .main import audit
    value = payload.model_dump_json()
    row = await db.get(AppSetting, SETTING_KEY)
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=SETTING_KEY, value=value))
    await audit(db, "content.app_config.updated", admin.email, None, {"consent_version": payload.consent.version, "stars": payload.wallet.stars.enabled})
    await db.commit()
    return {"ok": True, "config": await build_config(db)}


@router.delete("/api/admin/app-config")
async def admin_app_config_reset(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("manage_content"))):
    from .main import audit
    row = await db.get(AppSetting, SETTING_KEY)
    if row:
        row.value = ""
    await audit(db, "content.app_config.reset", admin.email)
    await db.commit()
    return {"ok": True}
