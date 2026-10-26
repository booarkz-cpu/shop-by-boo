"""Shop documents edited in the admin panel (v28.29.0): frequently asked questions, rules,
privacy policy and public offer.

One text per document and language (Russian is required, English and Ukrainian fall back to
it). Only administrators change them (permission ``legal.write``); every save is written to
the audit log with a new version number. The same text is shown in the Mini App, the
personal cabinet and the bot (/faq, /rules, /privacy, /offer, /info and menu buttons).

Text format, kept deliberately small so it renders the same everywhere:
  ``## Heading`` — a heading line;  ``- item`` — a list item;  ``**bold**``;
  an empty line starts a new paragraph;  links ``https://…`` are shown as is.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from html import escape
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .models import AppSetting
from .security import require_permission

router = APIRouter()
Kind = Literal["faq", "rules", "privacy", "offer"]
KINDS: tuple[str, ...] = ("faq", "rules", "privacy", "offer")
LANGS = ("ru", "en", "uk")
PREFIX = "info_page:"
TITLES = {
    "ru": {"faq": "Частые вопросы", "rules": "Правила", "privacy": "Политика конфиденциальности", "offer": "Публичная оферта"},
    "en": {"faq": "FAQ", "rules": "Rules", "privacy": "Privacy policy", "offer": "Public offer"},
    "uk": {"faq": "Часті питання", "rules": "Правила", "privacy": "Політика конфіденційності", "offer": "Публічна оферта"},
}
COMMANDS = {"faq": "/faq", "rules": "/rules", "privacy": "/privacy", "offer": "/offer"}
MAX_BODY = 30000


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FaqItem(_Strict):
    question: str = Field(min_length=1, max_length=300)
    answer: str = Field(min_length=1, max_length=3000)


class Translation(_Strict):
    title: str = Field(default="", max_length=120)
    body: str = Field(default="", max_length=MAX_BODY)
    items: list[FaqItem] = Field(default_factory=list, max_length=60)

    @field_validator("title", "body")
    @classmethod
    def _clean(cls, value: str) -> str:
        # Control characters other than line breaks never reach Telegram or the page.
        return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", value).replace("\r\n", "\n").strip()


class PageIn(_Strict):
    enabled: bool = True
    ru: Translation
    en: Translation = Field(default_factory=Translation)
    uk: Translation = Field(default_factory=Translation)


def _empty(t: dict) -> bool:
    return not (t.get("body") or t.get("items"))


async def load(db: AsyncSession, kind: str) -> dict | None:
    row = await db.get(AppSetting, PREFIX + kind)
    return json.loads(row.value) if row and row.value else None


async def load_all(db: AsyncSession) -> dict[str, dict]:
    rows = (await db.execute(select(AppSetting).where(AppSetting.key.in_([PREFIX + k for k in KINDS])))).scalars().all()
    return {r.key[len(PREFIX):]: json.loads(r.value) for r in rows if r.value}


def localized(kind: str, stored: dict | None, lang: str) -> dict | None:
    """The page in ``lang``; an unfilled translation falls back to Russian. None when unpublished."""
    if not stored or not stored.get("enabled", True):
        return None
    lang = lang if lang in LANGS else "ru"
    t = stored.get(lang) or {}
    if _empty(t):
        lang, t = "ru", stored.get("ru") or {}
    if _empty(t):
        return None
    return {"kind": kind, "lang": lang, "title": t.get("title") or TITLES[lang][kind], "body": t.get("body", ""),
            "items": t.get("items", []), "version": stored.get("version", 1), "updated_at": stored.get("updated_at")}


async def published(db: AsyncSession, lang: str) -> list[dict]:
    """Filled documents in the shop's order: FAQ, rules, privacy, offer."""
    stored = await load_all(db)
    return [p for k in KINDS if (p := localized(k, stored.get(k), lang))]


# ------------------------------------------------------------------ rendering

def _inline_html(text: str) -> str:
    out = escape(text, quote=False)
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", out)


def telegram_html(page: dict) -> str:
    """The page as Telegram HTML (b, i only), headings bold, list items with bullets."""
    lines = [f"<b>{escape(page['title'], quote=False)}</b>", ""]
    for raw in page.get("body", "").split("\n"):
        line = raw.rstrip()
        if line.startswith("## "):
            lines.append(f"<b>{_inline_html(line[3:].strip())}</b>")
        elif line.startswith(("- ", "* ")):
            lines.append("• " + _inline_html(line[2:].strip()))
        else:
            lines.append(_inline_html(line))
    for item in page.get("items", []):
        lines += ["", f"<b>❓ {_inline_html(item['question'])}</b>", _inline_html(item["answer"])]
    text = "\n".join(lines).strip()
    return re.sub(r"\n{3,}", "\n\n", text)


def split_message(text: str, limit: int = 3900) -> list[str]:
    """Telegram allows 4096 characters per message: split on paragraph, then line boundaries."""
    parts, current = [], ""
    for block in text.split("\n\n"):
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            parts.append(current)
        while len(block) > limit:
            cut = block.rfind("\n", 0, limit)
            cut = cut if cut > 0 else limit
            parts.append(block[:cut])
            block = block[cut:].lstrip("\n")
        current = block
    if current:
        parts.append(current)
    # A split never leaves a <b> tag open: bold spans are kept within one line above.
    return parts


# ------------------------------------------------------------------ API

def _lang(request: Request, lang: str | None) -> str:
    if lang in LANGS:
        return lang
    header = (request.headers.get("accept-language") or "ru")[:2].lower()
    return header if header in LANGS else "ru"


@router.get("/api/public/info-pages")
async def public_list(request: Request, lang: str | None = None, db: AsyncSession = Depends(get_db)):
    return [{"kind": p["kind"], "title": p["title"], "updated_at": p["updated_at"], "version": p["version"]}
            for p in await published(db, _lang(request, lang))]


@router.get("/api/public/info-pages/{kind}")
async def public_page(kind: Kind, request: Request, lang: str | None = None, db: AsyncSession = Depends(get_db)):
    page = localized(kind, await load(db, kind), _lang(request, lang))
    if not page:
        raise HTTPException(404, "Документ не опубликован")
    return page


@router.get("/api/admin/info-pages")
async def admin_list(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("read"))):
    from .security import PERMISSIONS
    stored = await load_all(db)
    return {"can_edit": "legal.write" in PERMISSIONS.get(admin.role, set()),
            "pages": [{"kind": k, "default_title": TITLES["ru"][k], "command": COMMANDS[k],
                       **(stored.get(k) or {"enabled": True, "ru": {}, "en": {}, "uk": {}, "version": 0})} for k in KINDS]}


@router.put("/api/admin/info-pages/{kind}")
async def admin_save(kind: Kind, payload: PageIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("legal.write"))):
    from .main import audit
    if payload.enabled and _empty(payload.ru.model_dump()):
        raise HTTPException(400, "Заполните текст на русском или выключите документ")
    row = await db.get(AppSetting, PREFIX + kind)
    previous = json.loads(row.value) if row and row.value else {}
    value = {**payload.model_dump(), "version": int(previous.get("version", 0)) + 1,
             "updated_at": datetime.utcnow().isoformat(timespec="seconds"), "updated_by": admin.email}
    if row:
        row.value = json.dumps(value, ensure_ascii=False)
    else:
        db.add(AppSetting(key=PREFIX + kind, value=json.dumps(value, ensure_ascii=False)))
    await audit(db, "info_page.saved", admin.email, kind, {"version": value["version"], "enabled": payload.enabled})
    await db.commit()
    return value
