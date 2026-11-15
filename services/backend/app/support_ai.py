"""AI support assistant: a draft answer for a support ticket, built from the shop's FAQ.

The operator presses «Черновик ответа» in a ticket; the draft goes into the reply box and is never sent by
itself. With an LLM configured (OpenAI-compatible chat API or Anthropic Messages API: SUPPORT_AI_URL,
SUPPORT_AI_KEY, SUPPORT_AI_MODEL in .env or «Настройки без перезапуска») the model writes the answer
from the FAQ, the customer's subscription status and the conversation. Without it, the closest FAQ answers
are offered by keyword match. Personal data sent to the model is limited to the conversation text and the
subscription status (no e-mail, phone, payment or Telegram identifiers).
"""
from __future__ import annotations

import json
import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .models import AppSetting, Subscription, SupportMessage, SupportTicket
from .security import require_permission

FAQ_KEY = "support_ai.faq"
MAX_FAQ = 200
router = APIRouter()
WORD = re.compile(r"[a-zа-яё0-9]{3,}", re.I)
SYSTEM = ("Ты оператор поддержки VPN-сервиса «Корги Люси». Отвечай кратко, вежливо и по делу, на языке клиента. "
          "Опирайся только на базу знаний и статус подписки. Если ответа в базе нет, предложи уточнить детали "
          "и не выдумывай. Не обещай возвратов и компенсаций — это решает оператор.")


class FaqItem(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    answer: str = Field(min_length=3, max_length=4000)


class FaqIn(BaseModel):
    items: list[FaqItem] = Field(max_length=MAX_FAQ)


def llm_settings() -> dict:
    from .config import settings
    return {"url": settings.support_ai_url, "key": settings.support_ai_key, "model": settings.support_ai_model or "gpt-4o-mini"}


async def faq(db: AsyncSession) -> list[dict]:
    """Custom Q&A from «Поддержка → База знаний» plus the published FAQ page."""
    items: list[dict] = []
    row = await db.get(AppSetting, FAQ_KEY)
    try:
        items = [x for x in json.loads(row.value) if isinstance(x, dict)] if row and row.value else []
    except ValueError:
        items = []
    try:
        from .info_pages import load
        page = await load(db, "faq")
        text = ((page or {}).get("ru") or {}).get("body") or (page or {}).get("body") or ""
        for block in re.split(r"\n\s*\n", str(text)):
            lines = [x.strip(" #*") for x in block.strip().splitlines() if x.strip()]
            if len(lines) >= 2:
                items.append({"question": lines[0], "answer": " ".join(lines[1:])})
    except Exception as exc:  # noqa: BLE001 — the FAQ page is optional
        import logging
        logging.getLogger("vpnshop.support_ai").debug("FAQ page unavailable: %s", exc)
    return items[:MAX_FAQ]


def rank(question: str, items: list[dict], top: int = 3) -> list[dict]:
    words = {w.lower()[:6] for w in WORD.findall(question)}  # crude stemming: «подписка/подписки» match
    scored = []
    for item in items:
        bag = {w.lower()[:6] for w in WORD.findall(item["question"] + " " + item["answer"])}
        score = len(words & bag)
        if score:
            scored.append((score, item))
    scored.sort(key=lambda x: -x[0])
    return [item for _, item in scored[:top]]


async def ticket_context(db: AsyncSession, ticket: SupportTicket) -> tuple[list[dict], str]:
    messages = (await db.execute(select(SupportMessage).where(SupportMessage.ticket_id == ticket.id)
                                 .order_by(SupportMessage.id.desc()).limit(12))).scalars().all()
    convo = [{"role": "user", "content": ticket.message}] if not messages else []
    for m in reversed(messages):
        convo.append({"role": "assistant" if m.role in {"admin", "operator", "staff"} else "user", "content": m.body[:3000]})
    sub = await db.scalar(select(Subscription).where(Subscription.user_id == ticket.user_id, Subscription.is_primary.is_(True)))
    if sub is None:
        status = "У клиента нет подписки."
    else:
        left = (sub.expires_at - datetime.utcnow()).days if sub.expires_at else None
        status = f"Подписка: статус {sub.lifecycle_status}, " + (f"до окончания {left} дн." if left is not None else "без срока") + \
                 f", лимит устройств {sub.device_limit_snapshot or '—'}, трафик {sub.traffic_limit_gb_snapshot or 'без лимита'} ГБ."
    return convo, status


async def call_llm(cfg: dict, system: str, convo: list[dict], client=None) -> str:
    import httpx
    own = client is None
    client = client or httpx.AsyncClient(timeout=40, trust_env=False)
    try:
        if "anthropic" in cfg["url"]:
            response = await client.post(cfg["url"], headers={"x-api-key": cfg["key"], "anthropic-version": "2023-06-01"},
                                         json={"model": cfg["model"], "max_tokens": 700, "system": system, "messages": convo})
            response.raise_for_status()
            return "".join(b.get("text", "") for b in response.json().get("content", []) if b.get("type") == "text").strip()
        response = await client.post(cfg["url"], headers={"Authorization": f"Bearer {cfg['key']}"},
                                     json={"model": cfg["model"], "temperature": 0.2, "max_tokens": 700,
                                           "messages": [{"role": "system", "content": system}, *convo]})
        response.raise_for_status()
        return str(response.json()["choices"][0]["message"]["content"]).strip()
    finally:
        if own:
            await client.aclose()


async def draft(db: AsyncSession, ticket_id: int, client=None) -> dict:
    ticket = await db.get(SupportTicket, ticket_id)
    if ticket is None:
        raise HTTPException(404, "Обращение не найдено")
    convo, status = await ticket_context(db, ticket)
    last_question = next((m["content"] for m in reversed(convo) if m["role"] == "user"), ticket.message)
    items = await faq(db)
    matched = rank(f"{ticket.subject} {last_question}", items)
    cfg = llm_settings()
    if cfg["url"] and cfg["key"]:
        knowledge = "\n\n".join(f"В: {x['question']}\nО: {x['answer']}" for x in (matched or items[:20]))
        system = f"{SYSTEM}\n\nБаза знаний:\n{knowledge or '—'}\n\nКонтекст: {status}"
        if convo and convo[0]["role"] != "user":
            convo = [{"role": "user", "content": ticket.subject}, *convo]
        try:
            text = await call_llm(cfg, system, convo, client)
            if text:
                return {"draft": text, "source": "llm", "matched": [x["question"] for x in matched]}
        except Exception as exc:  # noqa: BLE001 — fall back to the FAQ
            matched = matched or []
            fallback_reason = str(exc)[:120]
        else:
            fallback_reason = "пустой ответ модели"
    else:
        fallback_reason = "модель не настроена"
    if matched:
        body = matched[0]["answer"]
        text = f"Здравствуйте! {body}\n\nЕсли не поможет, напишите, пожалуйста, подробнее — разберёмся."
    else:
        text = "Здравствуйте! Спасибо за обращение. Уточните, пожалуйста, на каком устройстве и в каком приложении возникает проблема — так мы поможем быстрее."
    return {"draft": text, "source": "faq", "matched": [x["question"] for x in matched], "note": fallback_reason}


@router.post("/api/admin/support/tickets/{ticket_id}/draft")
async def support_draft(ticket_id: int, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("support.write"))):
    return await draft(db, ticket_id)


@router.get("/api/admin/support/ai")
async def support_ai_settings(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("support.read"))):
    row = await db.get(AppSetting, FAQ_KEY)
    try:
        items = json.loads(row.value) if row and row.value else []
    except ValueError:
        items = []
    cfg = llm_settings()
    return {"items": items, "llm_configured": bool(cfg["url"] and cfg["key"]), "model": cfg["model"] if cfg["url"] else None}


@router.put("/api/admin/support/ai")
async def save_support_ai(payload: FaqIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("support.write"))):
    from .main import audit
    row = await db.get(AppSetting, FAQ_KEY)
    value = json.dumps([x.model_dump() for x in payload.items], ensure_ascii=False)
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=FAQ_KEY, value=value))
    await audit(db, "support.ai.faq", admin.email, None, {"items": len(payload.items)})
    await db.commit()
    return {"items": len(payload.items)}
