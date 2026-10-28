"""Telegram profile photo of the customer for the cabinet and Mini App header (also when signed in by e-mail on a
linked account). The bot asks Telegram (getUserProfilePhotos → getFile), the small size is cached in memory for an hour.
No photo or privacy settings that hide it → 404 and the interface shows the initial."""
from __future__ import annotations

import time

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db

router = APIRouter()
_cache: dict[int, tuple[float, bytes | None]] = {}
TTL = 3600


async def fetch(telegram_id: int, client: httpx.AsyncClient | None = None) -> bytes | None:
    from . import tg
    from .config import settings
    hit = _cache.get(telegram_id)
    if hit and time.monotonic() - hit[0] < TTL:
        return hit[1]
    data = None
    try:
        photos = await tg.call("getUserProfilePhotos", {"user_id": telegram_id, "limit": 1}, client)
        sizes = (photos.get("photos") or [[]])[0]
        if sizes:
            small = sorted(sizes, key=lambda s: s.get("width", 0))[min(1, len(sizes) - 1)]
            file = await tg.call("getFile", {"file_id": small["file_id"]}, client)
            own = client is None
            client = client or httpx.AsyncClient(timeout=10)
            try:
                response = await client.get(f"https://api.telegram.org/file/bot{settings.bot_token}/{file['file_path']}")
                if response.status_code == 200 and len(response.content) < 512 * 1024:
                    data = response.content
            finally:
                if own:
                    await client.aclose()
    except Exception:  # noqa: BLE001 — no avatar is a normal answer
        data = None
    if len(_cache) > 5000:
        _cache.clear()
    _cache[telegram_id] = (time.monotonic(), data)
    return data


@router.get("/api/me/avatar")
async def my_avatar(request: Request, db: AsyncSession = Depends(get_db)):
    from .main import user_from_token
    user = await user_from_token(request, db)
    if not user.telegram_id:
        raise HTTPException(404, "Нет фото")
    data = await fetch(int(user.telegram_id))
    if not data:
        raise HTTPException(404, "Нет фото")
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})
