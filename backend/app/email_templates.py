"""E-mail templates: the owner edits the subject and text of every letter the shop sends (password reset, e-mail
confirmation, guest purchase). ``{link}`` is replaced with the action link, ``{shop}`` with the shop name and
``{hours}`` with how long the link works. Kept in app settings and cached by every process (the mail worker reads
the cache synchronously); «Настройки → Шаблоны писем» (web) and the mobile admin card.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import require_permission

router = APIRouter()
KEY = "email.templates"
DEFAULTS = {
    "password_reset": {"subject": "Восстановление пароля",
                       "body": "Изменить пароль:\n{link}\n\nЕсли вы не запрашивали это действие, проигнорируйте письмо. Ссылка действует {hours}."},
    "verify_email": {"subject": "Подтверждение email",
                     "body": "Подтвердить почту:\n{link}\n\nЕсли вы не запрашивали это действие, проигнорируйте письмо. Ссылка действует {hours}."},
    "guest_setup": {"subject": "Ваша подписка {shop}",
                    "body": "Спасибо за покупку! Подписка и инструкции по подключению — в личном кабинете.\n"
                            "Задайте пароль, чтобы входить с любого устройства:\n{link}\n\nСсылка действует {hours}."},
}
TITLES = {"password_reset": "Восстановление пароля", "verify_email": "Подтверждение email", "guest_setup": "Покупка по email (гость)"}
_cache: dict = {}


class TemplateIn(BaseModel):
    subject: str = Field(min_length=1, max_length=150)
    body: str = Field(min_length=1, max_length=5000)


def render(purpose: str, link: str, hours: str) -> tuple[str, str]:
    template = {**DEFAULTS.get(purpose, DEFAULTS["verify_email"]), **_cache.get(purpose, {})}
    if "{link}" not in template["body"]:
        template["body"] += "\n{link}"
    values = {"link": link, "hours": hours, "shop": _cache.get("_shop_name") or "Корги Люси"}
    fill = lambda text: text.replace("{link}", values["link"]).replace("{hours}", values["hours"]).replace("{shop}", values["shop"])  # noqa: E731
    return fill(template["subject"]), fill(template["body"])


async def refresh(db: AsyncSession) -> dict:
    from .models import AppSetting
    from .node_health import _load
    _cache.clear()
    _cache.update(await _load(db, KEY, {}))
    name = await db.get(AppSetting, "app_name")
    templates = {k: v for k, v in _cache.items() if not k.startswith("_")}
    _cache["_shop_name"] = (name.value if name and name.value else "Корги Люси")
    return templates


async def _startup():
    from .db import SessionLocal
    try:
        async with SessionLocal() as db:
            await refresh(db)
    except Exception:  # noqa: BLE001 — defaults stay in force
        _cache.clear()


router.add_event_handler("startup", _startup)


@router.get("/api/admin/email-templates")
async def get_templates(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("manage_content"))):
    stored = await refresh(db)
    return {"templates": [{"purpose": p, "title": TITLES[p], **DEFAULTS[p], **stored.get(p, {}), "custom": p in stored} for p in DEFAULTS],
            "placeholders": ["{link}", "{hours}", "{shop}"]}


@router.put("/api/admin/email-templates/{purpose}")
async def put_template(purpose: str, payload: TemplateIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("manage_content"))):
    from .main import audit
    from .node_health import _save
    if purpose not in DEFAULTS:
        raise HTTPException(404, "Неизвестный шаблон")
    if "{link}" not in payload.body:
        raise HTTPException(400, "В тексте письма должна быть ссылка {link}")
    stored = await refresh(db)
    stored[purpose] = payload.model_dump()
    await _save(db, KEY, dict(stored))
    await audit(db, "email.template", admin.email, purpose, None)
    await db.commit()
    _cache[purpose] = payload.model_dump()
    return {"ok": True}


@router.delete("/api/admin/email-templates/{purpose}")
async def reset_template(purpose: str, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("manage_content"))):
    from .node_health import _save
    stored = await refresh(db)
    stored.pop(purpose, None)
    await _save(db, KEY, dict(stored))
    await db.commit()
    _cache.pop(purpose, None)
    return {"ok": True}
