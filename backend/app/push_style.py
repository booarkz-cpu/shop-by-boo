"""Look of the push notifications of the apps («Приложения: стиль push-уведомлений»).

The administrator edits, for every kind of notification, the title and text templates, the
banner picture, up to two buttons (each opens a section of the app), the Android group
(channel), sound and priority, and the brand colour and icon of all pushes. push.py renders a
notification with ``render()`` right before sending, so changes apply to the next push.

Templates take ``{title}`` and ``{body}`` (the in-app notification), ``{brand}``; anything
else is left as written. Lock-screen privacy is kept: kinds in push.PRIVATE_KINDS never show
their text whatever the template says.
"""
from __future__ import annotations

import json
import re

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .models import AppSetting
from .security import require_permission

router = APIRouter()
SETTING_KEY = "push_style"
COLOR = r"^#[0-9a-fA-F]{6}$"
SECTION = r"^(|[a-z][a-z0-9_-]{0,31})$"
CHANNELS = {"important": "Важное: подписка и оплата", "service": "Сервис и поддержка", "promo": "Акции и розыгрыши"}
KINDS = {
    "subscription_expiring": "Подписка заканчивается",
    "payment": "Оплата и выдача подписки",
    "campaign": "Push-кампании",
    "support": "Ответ поддержки",
    "giveaway": "Розыгрыши и бонусы",
    "default": "Остальные уведомления",
}
# Notification kind of the shop → style kind.
KIND_MAP = {"subscription_expiring": "subscription_expiring", "payment_success": "payment", "subscription_ready": "payment",
            "payment": "payment", "fulfillment": "payment", "campaign": "campaign", "admin.bulk": "campaign",
            "automation": "campaign", "support.reply": "support", "giveaway_reward": "giveaway", "survey_reward": "giveaway"}

__all__ = ["router", "PushStyle", "KINDS", "CHANNELS", "load", "render", "style_kind"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PushButton(_Strict):
    label: str = Field(min_length=1, max_length=24)
    section: str = Field(default="", pattern=SECTION)


class KindStyle(_Strict):
    enabled: bool = True
    title: str = Field(default="{title}", min_length=1, max_length=120)
    body: str = Field(default="{body}", min_length=1, max_length=300)
    image: str = Field(default="", max_length=512)  # banner key (app-*) or https:// URL
    section: str = Field(default="", pattern=SECTION)  # opened on tap
    buttons: list[PushButton] = Field(default_factory=list, max_length=2)
    channel: str = Field(default="service", pattern=r"^(important|service|promo)$")
    sound: bool = True
    emoji: str = Field(default="", max_length=4)

    @field_validator("image")
    @classmethod
    def _image(cls, value):
        value = value.strip()
        if value and not (value.startswith("https://") or re.fullmatch(r"app-[a-z0-9-]{2,40}", value)):
            raise ValueError("Картинка — ключ баннера app-… или ссылка https://")
        return value


def _k(title, body, image, section, buttons, channel, emoji="", sound=True) -> dict:
    return {"title": title, "body": body, "image": image, "section": section, "channel": channel, "emoji": emoji, "sound": sound,
            "buttons": [{"label": l, "section": s} for l, s in buttons]}


DEFAULT_KINDS = {
    "subscription_expiring": _k("{title}", "{body}", "app-premium", "premium", [("Продлить", "premium"), ("Подписка", "subscription")], "important", "⏳"),
    "payment": _k("{title}", "{body}", "app-vpn", "vpn", [("Подключить", "vpn")], "important", "✅"),
    "campaign": _k("{title}", "{body}", "app-premium", "premium", [("Открыть", "premium")], "promo", "🐾"),
    "support": _k("{title}", "{body}", "", "support", [("Ответить", "support")], "service", "💬"),
    "giveaway": _k("{title}", "{body}", "app-giveaways", "giveaways", [("Розыгрыши", "giveaways")], "promo", "🎁"),
    "default": _k("{title}", "{body}", "", "notifications", [], "service"),
}


class PushStyle(_Strict):
    accent: str = Field(default="#FF8A1F", pattern=COLOR)
    brand: str = Field(default="Корги Люси", min_length=1, max_length=40)
    large_icon: bool = True  # the shop logo next to the text
    images: bool = True  # banner pictures at all
    group: bool = True  # stack pushes of one kind
    kinds: dict[str, KindStyle] = Field(default_factory=lambda: {k: KindStyle.model_validate(v) for k, v in DEFAULT_KINDS.items()})

    @field_validator("kinds")
    @classmethod
    def _kinds(cls, value):
        unknown = set(value) - set(KINDS)
        if unknown:
            raise ValueError(f"Неизвестные типы: {', '.join(sorted(unknown))}")
        merged = {k: KindStyle.model_validate(v) for k, v in DEFAULT_KINDS.items()}
        merged.update(value)
        return merged


async def load(db: AsyncSession) -> PushStyle:
    row = await db.get(AppSetting, SETTING_KEY)
    if row and row.value:
        try:
            return PushStyle.model_validate(json.loads(row.value))
        except Exception:
            pass
    return PushStyle()


def style_kind(kind: str) -> str:
    return KIND_MAP.get(kind or "", "default")


def _fill(template: str, values: dict[str, str]) -> str:
    return re.sub(r"\{(title|body|brand)\}", lambda m: values[m.group(1)], template)


def _image_url(image: str, base: str) -> str:
    if not image:
        return ""
    if image.startswith("https://"):
        return image
    return f"{base.rstrip('/')}/api/bot/banners/default/{image}.jpg" if base.startswith("https://") else ""


def render(style: PushStyle, kind: str, title: str, body: str, base: str = "") -> dict:
    """Title, body and extra fields of one push. ``base`` is the public https address of the API."""
    k = style.kinds.get(style_kind(kind)) or style.kinds["default"]
    values = {"title": title, "body": body, "brand": style.brand}
    out_title = " ".join(_fill(k.title, values).split())
    if k.emoji and not out_title.startswith(k.emoji):
        out_title = f"{k.emoji} {out_title}"
    return {
        "enabled": k.enabled,
        "title": out_title,
        "body": " ".join(_fill(k.body, values).split()),
        "image": _image_url(k.image, base) if style.images else "",
        "section": k.section,
        "buttons": [b.model_dump() for b in k.buttons],
        "channel": k.channel,
        "sound": k.sound,
        "accent": style.accent,
        "large_icon": style.large_icon,
        "group": style_kind(kind) if style.group else "",
    }


@router.get("/api/mobile/push-style")
async def public_push_style(response: Response, db: AsyncSession = Depends(get_db)):
    """Channels and button sets the apps register (Android channels, iOS categories)."""
    style = await load(db)
    response.headers["Cache-Control"] = "no-cache"
    return {"accent": style.accent, "channels": CHANNELS,
            "categories": {k: [b.model_dump() for b in v.buttons] for k, v in style.kinds.items()}}


@router.get("/api/admin/push-style")
async def admin_push_style(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("marketing.read"))):
    from .app_login import api_base

    style = await load(db)
    samples = {"subscription_expiring": ("Подписка заканчивается", "VPN работает до 30.10.2026 — осталось 3 дн. Продлите, чтобы не потерять доступ."),
               "payment": ("Подписка активна", "Оплата прошла — нажмите «Подключить»."),
               "campaign": ("Скидка 20% на год", "Только до воскресенья — промокод LUSI20."),
               "support": ("Ответ поддержки", "Откройте приложение, чтобы прочитать ответ поддержки."),
               "giveaway": ("Вы выиграли 300 ₽", "Приз уже на балансе."),
               "default": ("Уведомление", "Новое сообщение от магазина.")}
    kinds_of = {k: [s for s, v in KIND_MAP.items() if v == k] for k in KINDS}
    return {"style": style.model_dump(), "kinds": KINDS, "channels": CHANNELS, "shop_kinds": kinds_of,
            "preview": {k: render(style, next(iter(kinds_of[k]), k), *samples[k], base=api_base()) for k in KINDS}}


@router.put("/api/admin/push-style")
async def admin_push_style_save(payload: PushStyle, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("manage_content"))):
    from .main import audit

    row = await db.get(AppSetting, SETTING_KEY)
    text = payload.model_dump_json()
    if row:
        row.value = text
    else:
        db.add(AppSetting(key=SETTING_KEY, value=text))
    await audit(db, "push_style.updated", admin.email, None, {"accent": payload.accent, "kinds": sorted(payload.kinds)})
    await db.commit()
    return {"style": payload.model_dump()}


@router.delete("/api/admin/push-style")
async def admin_push_style_reset(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("manage_content"))):
    from .main import audit

    row = await db.get(AppSetting, SETTING_KEY)
    if row:
        await db.delete(row)
    await audit(db, "push_style.reset", admin.email)
    await db.commit()
    return {"style": PushStyle().model_dump()}
