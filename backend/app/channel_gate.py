"""Required channels: the customer must be subscribed to Telegram channels before a purchase, a trial or at all.

Each channel has a scope: ``all`` (bot start, Mini App, cabinet — everything), ``trial`` (activating the trial) or
``buy`` (purchases, top-ups, gifts). The old single ``REQUIRED_TELEGRAM_CHANNEL`` still works as a ``buy`` channel.
Membership is asked from Telegram (``getChatMember``; the bot must be an admin of the channel) and cached for
a minute per customer. «Маркетинг → Обязательные каналы» (web) and the mobile admin card.
"""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import require_permission

router = APIRouter()
CONFIG_KEY = "channels.gate"
SCOPES = ("all", "trial", "buy")
_cache: dict = {"at": 0.0, "channels": None}
_members: dict[tuple[int, str], tuple[float, bool]] = {}


class ChannelIn(BaseModel):
    chat: str = Field(min_length=2, max_length=128, pattern=r"^(@[A-Za-z0-9_]{4,64}|-100\d{5,20})$")
    title: str = Field(min_length=1, max_length=80)
    url: str = Field("", max_length=300, pattern=r"^(https://t\.me/.*)?$")
    scope: str = Field("buy", pattern="^(all|trial|buy)$")


class GateIn(BaseModel):
    channels: list[ChannelIn] = Field(default_factory=list, max_length=10)


async def load(db: AsyncSession) -> list[dict]:
    from .config import settings
    from .node_health import _load
    channels = list((await _load(db, CONFIG_KEY, {"channels": []})).get("channels") or [])
    legacy = (settings.required_telegram_channel or "").strip()
    if legacy and not any(c["chat"] == legacy for c in channels):
        channels.append({"chat": legacy, "title": "Канал", "url": f"https://t.me/{legacy.lstrip('@')}" if legacy.startswith("@") else "",
                         "scope": "buy"})
    return channels


async def _channels() -> list[dict]:
    if _cache["channels"] is None or time.monotonic() - _cache["at"] > 60:
        from .db import SessionLocal
        async with SessionLocal() as db:
            _cache["channels"] = await load(db)
        _cache["at"] = time.monotonic()
    return _cache["channels"]


async def is_member(telegram_id: int, chat: str, client=None) -> bool:
    from . import tg
    key = (int(telegram_id), chat)
    hit = _members.get(key)
    if hit and time.monotonic() - hit[0] < 60:
        return hit[1]
    try:
        result = await tg.call("getChatMember", {"chat_id": chat, "user_id": int(telegram_id)}, client)
    except tg.TelegramError as exc:
        if exc.code == 400 and "user not found" in exc.description.lower():
            ok = False
        else:
            raise HTTPException(503, "Не удалось проверить подписку на канал") from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, "Не удалось проверить подписку на канал") from exc
    else:
        ok = (result or {}).get("status") in {"member", "administrator", "creator"}
    _members[key] = (time.monotonic(), ok)
    return ok


async def missing(telegram_id: int | None, scope: str, channels: list[dict] | None = None, client=None) -> list[dict]:
    """Channels of this scope (and ``all``) the customer is not in. No Telegram account → all of them."""
    channels = [c for c in (channels if channels is not None else await _channels()) if c["scope"] in ("all", scope)]
    if not channels:
        return []
    if not telegram_id:
        return channels
    return [c for c in channels if not await is_member(telegram_id, c["chat"], client)]


async def ensure(user, scope: str) -> None:
    lacking = await missing(getattr(user, "telegram_id", None), scope)
    if lacking:
        names = ", ".join(c["title"] for c in lacking)
        raise HTTPException(403, f"Подпишитесь на {('каналы' if len(lacking) > 1 else 'канал')}: {names}")


@router.get("/api/me/channels")
async def my_channels(request: Request, scope: str = "all", db: AsyncSession = Depends(get_db)):
    """For the cabinet, Mini App and apps: which channels to join (with links) before the action."""
    from .main import user_from_token
    if scope not in SCOPES:
        raise HTTPException(400, "Unknown scope")
    user = await user_from_token(request, db)
    lacking = await missing(user.telegram_id, scope)
    return {"missing": [{"title": c["title"], "url": c.get("url") or ""} for c in lacking]}


@router.get("/api/admin/channels")
async def get_gate(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("marketing.read"))):
    return {"channels": await load(db), "scopes": {"all": "везде", "trial": "пробный период", "buy": "покупки и пополнения"}}


@router.put("/api/admin/channels")
async def put_gate(payload: GateIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("manage_marketing"))):
    from .main import audit
    from .node_health import _save
    value = {"channels": [c.model_dump() for c in payload.channels]}
    await _save(db, CONFIG_KEY, value)
    await audit(db, "channels.gate", admin.email, None, value)
    await db.commit()
    _cache["channels"] = None
    _members.clear()
    return value
