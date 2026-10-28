"""Support auto-reply: a new ticket whose question is clearly covered by the knowledge base gets an answer at once.

When a customer opens a ticket (cabinet, Mini App, bot, apps), the shop compares it with the FAQ of «База знаний
ИИ-ассистента» (the same word match as the drafts). If the best answer shares at least ``min_score`` words with the
question — or an LLM is configured and «отвечать моделью» is on — the answer is posted to the ticket as «🤖 Автоответ»
and the customer is notified. The ticket stays open: an operator sees it and the customer can reply «не помогло».
Never for refunds, payments or account deletion (keywords) — those always wait for a person. Off by default;
«Поддержка → Автоответы» (web) and the mobile admin card. Each auto-answer is counted with «помогло / нет».
"""
from __future__ import annotations

import logging
import re

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import require_permission

logger = logging.getLogger("vpnshop.autoreply")
router = APIRouter()
KEY = "support.autoreply"
DEFAULT = {"enabled": False, "min_score": 3, "use_llm": False, "sent": 0}
HUMAN_ONLY = re.compile(r"возврат|верн[иу]те деньги|списал|списани|чарджбэк|удал(ить|ите) аккаунт|refund|chargeback|delete my account", re.I)


class AutoreplyIn(BaseModel):
    enabled: bool
    min_score: int = Field(3, ge=1, le=10)
    use_llm: bool = False


def best(question: str, items: list[dict]) -> tuple[int, dict | None]:
    from .support_ai import WORD
    words = {w.lower()[:6] for w in WORD.findall(question)}
    top, found = 0, None
    for item in items:
        bag = {w.lower()[:6] for w in WORD.findall(item["question"] + " " + item["answer"])}
        score = len(words & bag)
        if score > top:
            top, found = score, item
    return top, found


async def maybe_reply(db: AsyncSession, ticket_id: int, client=None) -> str | None:
    from .models import Notification, SupportTicket
    from .node_health import _load, _save
    from .support_ai import draft, faq, llm_settings
    from .support_threads import append_message
    config = await _load(db, KEY, DEFAULT)
    if not config["enabled"]:
        return None
    ticket = await db.get(SupportTicket, ticket_id)
    if not ticket or HUMAN_ONLY.search(f"{ticket.subject} {ticket.message}"):
        return None
    score, item = best(f"{ticket.subject} {ticket.message}", await faq(db))
    cfg = llm_settings()
    if config.get("use_llm") and cfg["url"] and cfg["key"] and score >= 1:
        text = (await draft(db, ticket_id, client))["draft"]
    elif item and score >= int(config["min_score"]):
        text = f"Здравствуйте! {item['answer']}"
    else:
        return None
    body = f"🤖 Автоответ\n\n{text}\n\nЕсли не помогло — ответьте в этом обращении, подключится оператор."
    message, created = await append_message(db, ticket, "admin", body, f"autoreply:{ticket_id}", None, "ai:autoreply")
    if created:
        db.add(Notification(user_id=ticket.user_id, channel="in_app", kind="support.reply", title=f"Ответ на обращение #{ticket.id}",
                            body=body[:1000], status="sent", dedupe_key=f"support-message:{message.id}"))
        config["sent"] = int(config.get("sent", 0)) + 1
        await _save(db, KEY, config)
    await db.commit()
    return body


async def after_ticket(ticket_id: int) -> None:
    from .db import SessionLocal
    try:
        async with SessionLocal() as db:
            body = await maybe_reply(db, ticket_id)
            if body:
                from .main import notify_user_telegram
                from .models import SupportTicket, User
                ticket = await db.get(SupportTicket, ticket_id)
                user = await db.get(User, ticket.user_id) if ticket else None
                if user and user.telegram_id:
                    await notify_user_telegram(user.telegram_id, f"Ответ на обращение #{ticket_id}:\n\n{body[:3500]}")
    except Exception as exc:  # noqa: BLE001 — the ticket simply waits for a person
        logger.info("auto-reply for ticket %s failed: %s", ticket_id, exc)


@router.get("/api/admin/support/autoreply")
async def get_autoreply(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("support.read"))):
    from .node_health import _load
    from .support_ai import faq, llm_settings
    cfg = llm_settings()
    return {**await _load(db, KEY, DEFAULT), "faq_items": len(await faq(db)), "llm_configured": bool(cfg["url"] and cfg["key"])}


@router.put("/api/admin/support/autoreply")
async def put_autoreply(payload: AutoreplyIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("support.write"))):
    from .main import audit
    from .node_health import _load, _save
    config = await _load(db, KEY, DEFAULT)
    config.update(payload.model_dump())
    await _save(db, KEY, config)
    await audit(db, "support.autoreply", admin.email, None, payload.model_dump())
    await db.commit()
    return {"ok": True}
