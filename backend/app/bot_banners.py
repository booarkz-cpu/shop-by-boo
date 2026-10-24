"""Banners of Telegram bot sections and menu buttons.

Every bot section (/start, /buy, /subscription, wallet, support, …) and every button of the
bot menu can show a banner image above its text, like a chat-app "screen header".

* Default banners ship with the code: ``app/assets/bot_banners/<section>.jpg`` (corgi Lusi,
  rendered by ``scripts/bot-banners/render.py``).
* The administrator can upload an own image per section or per menu button, reset it to
  the default, or hide the banner. Settings live in ``app_settings``:
  ``bot_banner:<key>`` → ``/media/<file>`` and ``bot_banner_off:<key>`` → ``"1"``;
  ``bot_banners_enabled`` = ``"0"`` turns banners off for the whole bot.
* Menu buttons use keys ``menu-<id>``. A folder without its own image uses the ``menu``
  banner; a field button shows only its own image.

The bot reads uploaded files from the shared media volume (mounted read-only into the bot
container). Telegram ``file_id`` values are cached in memory so each file is uploaded once.
"""
from __future__ import annotations

import logging
import pathlib
import re
import secrets
from io import BytesIO

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import get_db
from .models import AppSetting, BotMenuItem
from .security import require_permission

logger = logging.getLogger(__name__)
router = APIRouter()

ASSETS = pathlib.Path(__file__).resolve().parent / "assets" / "bot_banners"
PREFIX = "bot_banner:"
OFF_PREFIX = "bot_banner_off:"
ENABLED_KEY = "bot_banners_enabled"
MAX_UPLOAD = 8 * 1024 * 1024
MAX_SIDE = 1600          # Telegram recompresses photos anyway; keep files light.
CAPTION_LIMIT = 1024     # Telegram limit for photo captions (text without HTML tags).

# key → (title in the admin panel, command that shows it)
SECTIONS: dict[str, tuple[str, str]] = {
    "start": ("Приветствие", "/start"),
    "menu": ("Меню", "папки без своего баннера"),
    "buy": ("Тарифы", "/buy"),
    "subscription": ("Подписка", "/subscription"),
    "promo": ("Промокод", "/promo"),
    "account": ("Мой кабинет", "/account"),
    "balance": ("Кошелёк", "/balance"),
    "payments": ("Платежи", "/payments"),
    "gifts": ("Подарки", "/gifts"),
    "referral": ("Пригласи друзей", "/referral"),
    "support": ("Поддержка", "/support"),
    "devices": ("Устройства", "/devices"),
    "surveys": ("Опросы", "/surveys"),
    # Mini App sections (the Mini App also uses buy, subscription, payments, gifts, referral,
    # support, devices, surveys and account from the list above).
    "home": ("Главная", "Mini App: главная"),
    "topup": ("Пополнение баланса", "Mini App: кошелёк"),
    "trial": ("Пробный период", "Mini App: пробный период"),
    "connection": ("Подключение", "Mini App: подключение"),
    "servers": ("Серверы", "Mini App: серверы"),
    "info": ("Информация", "Mini App: информация и оферта"),
}
MENU_KEY = re.compile(r"^menu-([1-9][0-9]{0,9})$")


def valid_key(key: str) -> bool:
    return key in SECTIONS or bool(MENU_KEY.match(key))


def default_path(key: str) -> pathlib.Path | None:
    path = ASSETS / f"{key}.jpg"
    return path if key in SECTIONS and path.is_file() else None


def media_path(url: str) -> pathlib.Path | None:
    if not url or not url.startswith("/media/"):
        return None
    path = pathlib.Path(settings.media_dir) / pathlib.Path(url.removeprefix("/media/")).name
    return path if path.is_file() else None


async def load_state(db: AsyncSession) -> dict[str, str]:
    rows = (await db.execute(select(AppSetting).where(
        (AppSetting.key.like(PREFIX + "%")) | (AppSetting.key.like(OFF_PREFIX + "%"))
        | (AppSetting.key.in_({ENABLED_KEY, "bot_start_image"}))))).scalars().all()
    return {row.key: row.value or "" for row in rows}


def resolve(key: str, state: dict[str, str]) -> tuple[str, pathlib.Path | None, str]:
    """Return (source, local file, uploaded url) for a banner key.

    source is ``custom``, ``default``, ``hidden`` or ``none``. The url is set for an
    uploaded image even if the file is not visible locally (bot without media volume).
    """
    if state.get(ENABLED_KEY) == "0" or state.get(OFF_PREFIX + key) == "1":
        return "hidden", None, ""
    url = state.get(PREFIX + key, "")
    if not url and key == "start":
        url = state.get("bot_start_image", "")  # image uploaded before v28.22.0
    if url.startswith("/media/") or url.startswith("https://"):
        return "custom", media_path(url), url
    if MENU_KEY.match(key):
        return "none", None, ""
    path = default_path(key)
    return ("default", path, "") if path else ("none", None, "")


# ---------------------------------------------------------------- bot side

_file_ids: dict[str, str] = {}


def _cache_key(path: pathlib.Path | None, url: str) -> str:
    if path is not None:
        try:
            return f"{path}:{path.stat().st_mtime_ns}"
        except OSError:
            return str(path)
    return url


def caption_length(html: str) -> int:
    from html import unescape
    return len(unescape(re.sub(r"<[^>]+>", "", html or "")))


async def banner_for(key: str, fallback: str | None = None):
    """Photo argument for aiogram (cached file_id, local file or public URL) or None."""
    from aiogram.types import FSInputFile
    from .db import engine
    async with AsyncSession(engine, expire_on_commit=False) as db:
        state = await load_state(db)
    source, path, url = resolve(key, state)
    if source == "none" and fallback:
        source, path, url = resolve(fallback, state)
    if source in {"hidden", "none"}:
        return None
    cache = _cache_key(path, url)
    if cache in _file_ids:
        return _file_ids[cache], cache
    if path is not None:
        return FSInputFile(path), cache
    if url.startswith("https://"):
        return url, cache
    base = (settings.public_base_url or "").rstrip("/")
    return (base + url, cache) if base.startswith("https://") else None


def remember(cache: str, message) -> None:
    photos = getattr(message, "photo", None) or []
    if photos and cache:
        _file_ids[cache] = photos[-1].file_id


async def send_section(message, key: str, text: str, reply_markup=None, *, fallback: str | None = None,
                       edit: bool = False, parse_mode: str = "HTML"):
    """Send (or, for callback navigation, edit in place) a section with its banner.

    Banner problems never break the bot: any Telegram error falls back to plain text.
    """
    from aiogram.exceptions import TelegramBadRequest
    from aiogram.types import InputMediaPhoto
    from .bot import menu_answer
    banner = None
    try:
        banner = await banner_for(key, fallback)
    except Exception as exc:  # database hiccup — still answer
        logger.warning("banner lookup failed for %s: %s", key, exc)
    if edit:
        try:
            if banner and getattr(message, "photo", None) and caption_length(text) <= CAPTION_LIMIT:
                sent = await menu_answer(message.edit_media, media=InputMediaPhoto(media=banner[0], caption=text, parse_mode=parse_mode), reply_markup=reply_markup)
                remember(banner[1], sent if not isinstance(sent, bool) else None)
                return sent
            if not banner and getattr(message, "text", None):
                return await menu_answer(message.edit_text, text, reply_markup=reply_markup, parse_mode=parse_mode)
        except TelegramBadRequest as exc:
            if "not modified" in str(exc).lower():
                return message
            logger.info("edit of bot section %s failed, sending a new message: %s", key, exc)
    if banner:
        try:
            if caption_length(text) <= CAPTION_LIMIT:
                sent = await menu_answer(message.answer_photo, photo=banner[0], caption=text, reply_markup=reply_markup, parse_mode=parse_mode)
                remember(banner[1], sent)
                return sent
            sent = await message.answer_photo(photo=banner[0])
            remember(banner[1], sent)
        except Exception as exc:
            _file_ids.pop(banner[1], None)
            logger.warning("bot banner %s was not delivered; sending text: %s", key, exc)
    return await menu_answer(message.answer, text, reply_markup=reply_markup, parse_mode=parse_mode)


# ---------------------------------------------------------------- admin API

def _public_url(key: str, source: str, url: str) -> str:
    if source == "custom":
        return url
    if source == "default" or (source == "hidden" and default_path(key)):
        return f"/api/bot/banners/default/{key}.jpg"
    return ""


async def _upsert(db: AsyncSession, key: str, value: str) -> str:
    row = await db.get(AppSetting, key)
    old = row.value if row else ""
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))
    return old or ""


def _unlink(url: str) -> None:
    if url.startswith("/media/") and pathlib.Path(url).name.startswith(("bot-banner-", "bot-start-")):
        try:
            (pathlib.Path(settings.media_dir) / pathlib.Path(url).name).unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("old bot banner was not removed: %s", exc)


def normalize_image(data: bytes) -> bytes:
    """Validate an upload and re-encode it as a JPEG suitable for Telegram photos."""
    from PIL import Image, ImageOps
    try:
        with Image.open(BytesIO(data)) as im:
            im.verify()
        with Image.open(BytesIO(data)) as im:
            if im.width * im.height > 40_000_000:
                raise ValueError("too many pixels")
            im = ImageOps.exif_transpose(im)
            if im.mode in ("RGBA", "LA", "P"):
                rgba = im.convert("RGBA")
                canvas = Image.new("RGB", rgba.size, (15, 21, 40))
                canvas.paste(rgba, mask=rgba.split()[3])
                im = canvas
            else:
                im = im.convert("RGB")
            if max(im.size) / max(1, min(im.size)) > 20:
                raise HTTPException(400, "Слишком вытянутое изображение: Telegram принимает соотношение сторон до 20:1")
            im.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
            out = BytesIO()
            im.save(out, "JPEG", quality=88, optimize=True, progressive=True)
            return out.getvalue()
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(400, "Файл не является корректным изображением")


@router.get("/api/bot/banners/default/{name}")
async def default_banner(name: str):
    key = name.removesuffix(".jpg")
    path = default_path(key)
    if not path or not name.endswith(".jpg"):
        raise HTTPException(404, "Баннер не найден")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})


@router.get("/api/admin/bot/banners")
async def list_banners(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("read"))):
    state = await load_state(db)
    def item(key, title, where):
        source, _, url = resolve(key, state)
        return {"key": key, "title": title, "where": where, "source": source,
                "hidden": state.get(OFF_PREFIX + key) == "1", "custom": bool(state.get(PREFIX + key) or (key == "start" and state.get("bot_start_image"))),
                "url": _public_url(key, source, url), "has_default": default_path(key) is not None}
    menu = (await db.execute(select(BotMenuItem).order_by(BotMenuItem.sort_order, BotMenuItem.id))).scalars().all()
    return {
        "enabled": state.get(ENABLED_KEY) != "0",
        "caption_limit": CAPTION_LIMIT,
        "sections": [item(key, title, where) for key, (title, where) in SECTIONS.items()],
        "menu": [item(f"menu-{row.id}", row.title, "папка" if row.item_type == "folder" else "кнопка-поле" if row.item_type == "field" else "ссылка")
                 for row in menu if row.item_type in {"folder", "field"}],
    }


async def _check_key(db: AsyncSession, key: str) -> None:
    if not valid_key(key):
        raise HTTPException(404, "Неизвестный раздел бота")
    match = MENU_KEY.match(key)
    if match:
        row = await db.get(BotMenuItem, int(match.group(1)))
        if not row or row.item_type not in {"folder", "field"}:
            raise HTTPException(404, "Кнопка меню не найдена или не открывает раздел")


@router.post("/api/admin/bot/banners/{key}")
async def upload_banner(key: str, file: UploadFile = File(...), db: AsyncSession = Depends(get_db), admin=Depends(require_permission("manage_content"))):
    from .main import _read_upload_limited, audit
    await _check_key(db, key)
    if file.content_type not in {"image/png", "image/jpeg", "image/webp"}:
        raise HTTPException(400, "Разрешены PNG, JPG и WEBP")
    data = normalize_image(await _read_upload_limited(file, MAX_UPLOAD))
    root = pathlib.Path(settings.media_dir)
    root.mkdir(parents=True, exist_ok=True)
    name = f"bot-banner-{key}-{secrets.token_hex(12)}.jpg"
    (root / name).write_bytes(data)
    old = await _upsert(db, PREFIX + key, "/media/" + name)
    off = await db.get(AppSetting, OFF_PREFIX + key)
    if off:
        off.value = ""
    if key == "start":
        legacy = await db.get(AppSetting, "bot_start_image")
        if legacy and legacy.value:
            _unlink(legacy.value)
            legacy.value = ""
    await audit(db, "content.bot.banner.updated", admin.email, key)
    await db.commit()
    _unlink(old)
    return {"ok": True, "url": "/media/" + name}


@router.delete("/api/admin/bot/banners/{key}")
async def reset_banner(key: str, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("manage_content"))):
    from .main import audit
    if not valid_key(key):
        raise HTTPException(404, "Неизвестный раздел бота")
    removed = []
    for setting_key in (PREFIX + key, OFF_PREFIX + key) + (("bot_start_image",) if key == "start" else ()):
        row = await db.get(AppSetting, setting_key)
        if row:
            removed.append(row.value or "")
            row.value = ""
    await audit(db, "content.bot.banner.reset", admin.email, key)
    await db.commit()
    for url in removed:
        _unlink(url)
    return {"ok": True}


async def forget_menu_banner(db: AsyncSession, item_id: int) -> str:
    """Drop banner settings of a deleted menu button; returns the file to remove after commit."""
    url = ""
    for key in (PREFIX + f"menu-{item_id}", OFF_PREFIX + f"menu-{item_id}"):
        row = await db.get(AppSetting, key)
        if row:
            url = url or (row.value if key.startswith(PREFIX) else "")
            await db.delete(row)
    return url


def remove_file(url: str) -> None:
    _unlink(url)


class Visibility(BaseModel):
    hidden: bool


@router.put("/api/admin/bot/banners/{key}/visibility")
async def banner_visibility(key: str, payload: Visibility, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("manage_content"))):
    from .main import audit
    await _check_key(db, key)
    await _upsert(db, OFF_PREFIX + key, "1" if payload.hidden else "")
    await audit(db, "content.bot.banner.hidden" if payload.hidden else "content.bot.banner.shown", admin.email, key)
    await db.commit()
    return {"ok": True, "hidden": payload.hidden}


class Enabled(BaseModel):
    enabled: bool


@router.put("/api/admin/bot/banners-enabled")
async def banners_enabled(payload: Enabled, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("manage_content"))):
    from .main import audit
    await _upsert(db, ENABLED_KEY, "1" if payload.enabled else "0")
    await audit(db, "content.bot.banners.enabled" if payload.enabled else "content.bot.banners.disabled", admin.email)
    await db.commit()
    return {"ok": True, "enabled": payload.enabled}
