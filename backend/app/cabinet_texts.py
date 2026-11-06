"""BACKLOG A4 (v28.88.0): every text of the web cabinet can be replaced from the admin panel, per language.

The cabinet's own texts live in cabinet/src/i18n.tsx (the Russian text is the key); their list with the English
and Ukrainian defaults is ``assets/cabinet_strings.json`` (scripts/generate-cabinet-strings.py keeps it in step).
The owner's versions are stored in ``app_settings.cabinet_texts`` as ``{lang: {key: text}}``; the cabinet reads
them from ``GET /api/public/cabinet-texts`` and shows them instead of its defaults, without a rebuild.

Texts are plain text: the cabinet puts them into the page as text nodes, never as HTML."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import require_permission

router = APIRouter()
LANGS = ("ru", "en", "uk")
SETTING = "cabinet_texts"
MAX_LEN = 500
STRINGS_FILE = Path(__file__).resolve().parent / "assets" / "cabinet_strings.json"


@lru_cache(maxsize=1)
def defaults() -> dict[str, dict[str, str]]:
    """key → {"ru", "en", "uk"}; an empty Ukrainian default means the cabinet shows the English one."""
    raw = json.loads(STRINGS_FILE.read_text(encoding="utf-8"))
    return {key: {"ru": key, "en": value.get("en", ""), "uk": value.get("uk", "") or value.get("en", "")} for key, value in raw.items()}


def load(value: str | None) -> dict[str, dict[str, str]]:
    try:
        data = json.loads(value or "{}")
    except ValueError:
        return {lang: {} for lang in LANGS}
    if not isinstance(data, dict):
        return {lang: {} for lang in LANGS}
    known = defaults()
    return {lang: {k: v for k, v in (data.get(lang) or {}).items() if k in known and isinstance(v, str)} for lang in LANGS}


async def _overrides(db: AsyncSession) -> tuple[object | None, dict]:
    from .models import AppSetting
    row = await db.get(AppSetting, SETTING)
    return row, load(row.value if row else None)


class TextsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lang: str = Field(pattern=r"^(ru|en|uk)$")
    # key → text; an empty string returns the default
    texts: dict[str, str] = Field(max_length=500)


@router.get("/api/public/cabinet-texts")
async def public_texts(db: AsyncSession = Depends(get_db)):
    """The owner's versions only: the cabinet keeps its defaults for everything else."""
    _row, overrides = await _overrides(db)
    return {lang: overrides[lang] for lang in LANGS if overrides[lang]}


@router.get("/api/admin/cabinet-texts")
async def admin_texts(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("read"))):
    _row, overrides = await _overrides(db)
    items = [{"key": key, "default": default, "custom": {lang: overrides[lang][key] for lang in LANGS if key in overrides[lang]}}
             for key, default in defaults().items()]
    return {"languages": list(LANGS), "texts": items}


@router.put("/api/admin/cabinet-texts")
async def put_texts(payload: TextsIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("manage_content"))):
    """Saves one language; the cabinet shows the new texts on its next page load."""
    from .main import audit
    from .models import AppSetting
    row, overrides = await _overrides(db)
    known = defaults()
    current = dict(overrides[payload.lang])
    errors = []
    for key, text in payload.texts.items():
        if key not in known:
            errors.append(f"Нет текста «{key[:60]}»")
            continue
        text = text.strip()
        if not text or text == known[key][payload.lang]:
            current.pop(key, None)
            continue
        if len(text) > MAX_LEN or "\x00" in text:
            errors.append(f"«{key[:60]}»: от 1 до {MAX_LEN} символов")
            continue
        current[key] = text
    if errors:
        raise HTTPException(422, "; ".join(errors[:10]))
    overrides[payload.lang] = current
    value = json.dumps(overrides, ensure_ascii=False)
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=SETTING, value=value))
    await audit(db, "cabinet.texts.updated", admin.email, payload.lang, {"changed": len(payload.texts), "custom": len(current)})
    await db.commit()
    return {"lang": payload.lang, "custom": len(current)}
