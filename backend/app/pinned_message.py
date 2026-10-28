"""Pinned message: one message the bot sends and pins in every customer's chat (an important announcement, a new
domain, holiday hours). Customers who start the bot later get it on ``/start``. Replacing it unpins the previous one.
Delivery runs in the background with Telegram's rate limits; customers who blocked the bot are skipped.
«Маркетинг → Закреплённое сообщение» (web) and the mobile admin card.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import require_permission

logger = logging.getLogger("vpnshop.pinned")
router = APIRouter()
KEY = "pinned.message"
_task: asyncio.Task | None = None


class PinnedIn(BaseModel):
    text: str = Field(min_length=1, max_length=3500)
    button_text: str = Field("", max_length=40)
    button_url: str = Field("", max_length=300, pattern=r"^(https://.*)?$")


async def _load(db):
    from .node_health import _load as load
    return await load(db, KEY, {})


async def _save(db, value):
    from .node_health import _save as save
    await save(db, KEY, value)


async def deliver(db: AsyncSession, user_id: int, telegram_id: int, message: dict, client=None) -> bool:
    """Send and pin one copy; remembers the Telegram message id for a later unpin."""
    from . import tg
    from .activity_log import record
    body = {"chat_id": telegram_id, "text": message["text"], "parse_mode": "HTML", "disable_web_page_preview": True}
    if message.get("button_text") and message.get("button_url"):
        body["reply_markup"] = {"inline_keyboard": [[{"text": message["button_text"], "url": message["button_url"]}]]}
    try:
        sent = await tg.call("sendMessage", body, client)
        await tg.call("pinChatMessage", {"chat_id": telegram_id, "message_id": sent["message_id"], "disable_notification": True}, client)
    except tg.TelegramError as exc:
        if exc.code == 429:
            raise
        return False
    record(db, user_id, "bot", "pinned.delivered", {"id": message["id"], "message_id": sent["message_id"]})
    return True


async def broadcast(message: dict, client=None, pause: float = 0.05) -> dict:
    from . import tg
    from .db import SessionLocal
    from .models import User, UserActivity
    from .moderation import blocked_ids
    sent = failed = 0
    async with SessionLocal() as db:
        blocked = await blocked_ids(db)
        users = (await db.execute(select(User.id, User.telegram_id).where(User.telegram_id.is_not(None), User.deleted_at.is_(None)))).all()
        done = {uid for uid, detail in (await db.execute(select(UserActivity.user_id, UserActivity.detail)
                                                         .where(UserActivity.action == "pinned.delivered"))).all()
                if (detail or {}).get("id") == message["id"]}
    for user_id, telegram_id in users:
        if telegram_id in blocked or user_id in done:
            continue
        async with SessionLocal() as db:
            current = await _load(db)
            if current.get("id") != message["id"]:
                break  # replaced or removed meanwhile
            for _ in range(3):
                try:
                    ok = await deliver(db, user_id, telegram_id, message, client)
                    break
                except tg.TelegramError as exc:
                    await asyncio.sleep(int("".join(ch for ch in exc.description if ch.isdigit()) or 3))
            else:
                ok = False
            sent, failed = sent + ok, failed + (not ok)
            if (sent + failed) % 100 == 0:
                current["progress"] = {"sent": sent, "failed": failed, "total": len(users)}
                await _save(db, current)
            await db.commit()
        await asyncio.sleep(pause)
    async with SessionLocal() as db:
        current = await _load(db)
        if current.get("id") == message["id"]:
            current["progress"] = {"sent": sent, "failed": failed, "total": len(users), "finished_at": datetime.utcnow().isoformat()}
            await _save(db, current)
            await db.commit()
    return {"sent": sent, "failed": failed}


async def unpin_previous(message_id: str, client=None) -> int:
    from . import tg
    from .db import SessionLocal
    from .models import User, UserActivity
    count = 0
    async with SessionLocal() as db:
        rows = (await db.execute(select(UserActivity.user_id, UserActivity.detail).where(UserActivity.action == "pinned.delivered"))).all()
        ids = {u.id: u.telegram_id for u in (await db.execute(select(User).where(User.id.in_({r[0] for r in rows})))).scalars()}
    for user_id, detail in rows:
        if (detail or {}).get("id") != message_id or not ids.get(user_id):
            continue
        try:
            await tg.call("unpinChatMessage", {"chat_id": ids[user_id], "message_id": int(detail["message_id"])}, client)
            count += 1
        except tg.TelegramError:
            continue
        await asyncio.sleep(0.05)
    return count


async def on_start(db: AsyncSession, user_id: int, telegram_id: int) -> None:
    """New customers get the current pinned message at /start (once)."""
    from .models import UserActivity
    message = await _load(db)
    if not message.get("id") or not message.get("active"):
        return
    seen = await db.scalar(select(UserActivity.id).where(UserActivity.user_id == user_id, UserActivity.action == "pinned.delivered")
                           .order_by(UserActivity.id.desc()).limit(1))
    if seen:
        return
    try:
        await deliver(db, user_id, telegram_id, message)
        await db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.info("pinned message at start failed: %s", exc)


@router.get("/api/admin/pinned-message")
async def get_pinned(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("marketing.read"))):
    return {"message": await _load(db), "sending": bool(_task and not _task.done())}


@router.post("/api/admin/pinned-message")
async def publish(payload: PinnedIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("manage_broadcasts"))):
    global _task
    import secrets

    from .main import audit
    if _task and not _task.done():
        raise HTTPException(409, "Предыдущее сообщение ещё рассылается")
    previous = await _load(db)
    message = {**payload.model_dump(), "id": secrets.token_hex(6), "active": True, "created_at": datetime.utcnow().isoformat(),
               "progress": {"sent": 0, "failed": 0}}
    await _save(db, message)
    await audit(db, "marketing.pinned.published", admin.email, message["id"], {"length": len(payload.text)})
    await db.commit()

    async def run():
        if previous.get("id"):
            await unpin_previous(previous["id"])
        await broadcast(message)
    _task = asyncio.create_task(run())
    return {"id": message["id"], "sending": True}


@router.delete("/api/admin/pinned-message")
async def remove(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("manage_broadcasts"))):
    global _task
    message = await _load(db)
    if not message.get("id"):
        raise HTTPException(404, "Закреплённого сообщения нет")
    message["active"] = False
    await _save(db, message)
    await db.commit()
    _task = asyncio.create_task(unpin_previous(message["id"]))
    return {"ok": True}
