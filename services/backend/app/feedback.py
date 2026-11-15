"""v28.52 «Оценка поддержки и NPS»: how customers rate the answers of support and whether they would recommend the shop.

* **CSAT.** ``csat_delay_minutes`` after an operator answered (the ticket is «resolved»), the customer gets «Оцените
  ответ» with 1–5 in Telegram (and an in-app notice; the cabinet shows the stars on the ticket). One rating per ticket,
  the operator is the last one who replied (``support.ticket.replied`` in the audit log). A score of 1–2 is sent to
  the owner at once.
* **NPS.** Once per ``nps_interval_days`` (a quarter by default) a paying customer who has been with the shop at least
  ``nps_min_days`` gets «Порекомендуете нас?» with 0–10. NPS = promoters (9–10) − detractors (0–6), in percent.

Both off by default (``feedback.config``). Admin: «Поддержка → Оценки и NPS» (by operator, by month, last comments)
and the mobile card. Ratings: ``feedback_ratings``.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import require_permission

logger = logging.getLogger("vpnshop.feedback")
router = APIRouter()
CONFIG_KEY = "feedback.config"
DEFAULT = {"csat_enabled": False, "csat_delay_minutes": 30, "nps_enabled": False, "nps_interval_days": 90, "nps_min_days": 30, "nps_batch": 200}


class FeedbackConfigIn(BaseModel):
    csat_enabled: bool = False
    csat_delay_minutes: int = Field(30, ge=0, le=1440)
    nps_enabled: bool = False
    nps_interval_days: int = Field(90, ge=30, le=365)
    nps_min_days: int = Field(30, ge=0, le=365)
    nps_batch: int = Field(200, ge=10, le=5000)


class RatingIn(BaseModel):
    score: int = Field(..., ge=0, le=10)
    ticket_id: int | None = None
    comment: str = Field("", max_length=1000)


async def load(db: AsyncSession) -> dict:
    from .node_health import _load
    return {**DEFAULT, **(await _load(db, CONFIG_KEY, DEFAULT) or {})}


def period(now: datetime, days: int) -> str:
    """The NPS wave a moment belongs to (a quarter for 90 days)."""
    if days >= 85 and days <= 95:
        return f"{now.year}Q{(now.month - 1) // 3 + 1}"
    return f"{now.year}W{int(now.strftime('%j')) // max(1, days)}"


def nps_of(scores: list[int]) -> int | None:
    if not scores:
        return None
    promoters = sum(1 for s in scores if s >= 9)
    detractors = sum(1 for s in scores if s <= 6)
    return round((promoters - detractors) * 100 / len(scores))


async def operator_of(db: AsyncSession, ticket_id: int) -> str | None:
    from .models import AuditLog
    return await db.scalar(select(AuditLog.actor).where(AuditLog.action == "support.ticket.replied", AuditLog.target == str(ticket_id))
                           .order_by(AuditLog.id.desc()).limit(1))


async def send_buttons(chat_id, text: str, rows: list[list[tuple[str, str]]]) -> bool:
    """A Telegram message with inline buttons (``(label, callback_data)``); never raises."""
    from .config import settings
    if not chat_id or not settings.bot_token:
        return False
    try:
        import httpx
        markup = {"inline_keyboard": [[{"text": label, "callback_data": data} for label, data in row] for row in rows]}
        async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
            r = await client.post(f"https://api.telegram.org/bot{settings.bot_token}/sendMessage",
                                  json={"chat_id": chat_id, "text": text[:1000], "reply_markup": markup})
        return r.is_success
    except Exception as exc:  # noqa: BLE001
        logger.debug("feedback message to %s failed: %s", chat_id, exc)
        return False


def csat_rows(ticket_id: int) -> list[list[tuple[str, str]]]:
    return [[(f"{s}⭐", f"csat:{ticket_id}:{s}") for s in range(1, 6)]]


def nps_rows(wave: str) -> list[list[tuple[str, str]]]:
    return [[(str(s), f"nps:{wave}:{s}") for s in range(0, 6)], [(str(s), f"nps:{wave}:{s}") for s in range(6, 11)]]


async def record(db: AsyncSession, user_id: int, kind: str, score: int, *, ticket_id: int | None = None, wave: str | None = None,
                 comment: str = "", alert=None) -> dict:
    """Store one rating (a repeat only updates the comment or the score of the same ticket or wave)."""
    from .models import FeedbackRating, SupportTicket
    if kind == "csat":
        if not 1 <= score <= 5:
            raise HTTPException(400, "Оценка — от 1 до 5")
        ticket = await db.get(SupportTicket, ticket_id) if ticket_id else None
        if not ticket or ticket.user_id != user_id:
            raise HTTPException(404, "Обращение не найдено")
        row = await db.scalar(select(FeedbackRating).where(FeedbackRating.kind == "csat", FeedbackRating.ticket_id == ticket_id))
        operator = await operator_of(db, ticket_id)
    else:
        if not 0 <= score <= 10:
            raise HTTPException(400, "Оценка — от 0 до 10")
        cfg = await load(db)
        wave = wave or period(datetime.utcnow(), int(cfg["nps_interval_days"]))
        row = await db.scalar(select(FeedbackRating).where(FeedbackRating.kind == "nps", FeedbackRating.user_id == user_id, FeedbackRating.period == wave))
        operator = None
    if row:
        row.score = score
        row.comment = (comment or row.comment or "")[:1000] or None
    else:
        row = FeedbackRating(user_id=user_id, kind=kind, ticket_id=ticket_id, period=wave, operator=operator, score=score, comment=comment[:1000] or None)
        db.add(row)
    await db.commit()
    if kind == "csat" and score <= 2:
        if alert is None:
            from .ops_alerts import send as alert
        try:
            await alert(f"Низкая оценка поддержки: {score} из 5\nОбращение: #{ticket_id}\nОператор: {operator or '—'}\nКлиент: #{user_id}"
                        + (f"\nКомментарий: {comment[:300]}" if comment else ""))
        except Exception as exc:  # noqa: BLE001
            logger.debug("low rating alert skipped: %s", exc)
    return {"ok": True, "id": row.id}


async def ask_pass(db: AsyncSession, now: datetime | None = None, send=None) -> dict:
    """Ask for CSAT on answered tickets and for NPS once per wave."""
    from .main import enqueue_notification
    from .models import FeedbackRating, Notification, Payment, Subscription, SupportTicket, User
    cfg = await load(db)
    now = now or datetime.utcnow()
    send = send or send_buttons
    out = {"csat": 0, "nps": 0}
    if cfg["csat_enabled"]:
        tickets = (await db.execute(select(SupportTicket).where(SupportTicket.status == "resolved", SupportTicket.merged_into_id.is_(None),
                                                                SupportTicket.updated_at <= now - timedelta(minutes=int(cfg["csat_delay_minutes"])),
                                                                SupportTicket.updated_at >= now - timedelta(days=3)).limit(200))).scalars().all()
        for t in tickets:
            key = f"csat:{t.id}"
            if await db.scalar(select(Notification.id).where(Notification.user_id == t.user_id, Notification.dedupe_key == key)):
                continue
            if await db.scalar(select(FeedbackRating.id).where(FeedbackRating.kind == "csat", FeedbackRating.ticket_id == t.id)):
                continue
            await enqueue_notification(db, user_id=t.user_id, channel="in_app", kind="support.rate", title=f"Оцените ответ по обращению #{t.id}",
                                       body="Поставьте оценку от 1 до 5 — это помогает нам отвечать лучше.", dedupe_key=key)
            await db.commit()
            user = await db.get(User, t.user_id)
            if user and user.telegram_id:
                await send(user.telegram_id, f"Как вам ответ поддержки по обращению #{t.id} «{t.subject[:60]}»? Оцените от 1 до 5.", csat_rows(t.id))
            out["csat"] += 1
    if cfg["nps_enabled"]:
        wave = period(now, int(cfg["nps_interval_days"]))
        key = f"nps:{wave}"
        asked = select(Notification.user_id).where(Notification.dedupe_key == key)
        answered = select(FeedbackRating.user_id).where(FeedbackRating.kind == "nps", FeedbackRating.period == wave)
        first_paid = select(Payment.user_id).where(Payment.status.in_(("paid", "fulfilled")), Payment.purpose == "subscription",
                                                   Payment.paid_at <= now - timedelta(days=int(cfg["nps_min_days"])))
        live = select(Subscription.user_id).where(Subscription.lifecycle_status.in_(("active", "cancel_scheduled", "frozen")), Subscription.expires_at > now)
        users = (await db.execute(select(User).where(User.deleted_at.is_(None), User.id.in_(first_paid), User.id.in_(live),
                                                     User.id.not_in(asked), User.id.not_in(answered)).limit(int(cfg["nps_batch"])))).scalars().all()
        for user in users:
            await enqueue_notification(db, user_id=user.id, channel="in_app", kind="nps", title="Порекомендуете нас друзьям?",
                                       body="Оцените от 0 до 10, насколько вероятно, что вы порекомендуете нас.", dedupe_key=key)
            await db.commit()
            if user.telegram_id:
                await send(user.telegram_id, "Насколько вероятно, что вы порекомендуете нас другу? 0 — точно нет, 10 — обязательно.", nps_rows(wave))
            out["nps"] += 1
    return out


async def report(db: AsyncSession, days: int = 90, now: datetime | None = None) -> dict:
    from .models import FeedbackRating
    now = now or datetime.utcnow()
    rows = (await db.execute(select(FeedbackRating).where(FeedbackRating.created_at >= now - timedelta(days=days)).order_by(FeedbackRating.id.desc()))).scalars().all()
    csat = [r for r in rows if r.kind == "csat"]
    nps = [r for r in rows if r.kind == "nps"]
    operators: dict[str, list[int]] = {}
    for r in csat:
        operators.setdefault(r.operator or "—", []).append(r.score)
    months: dict[str, list[int]] = {}
    for r in nps:
        months.setdefault(r.created_at.strftime("%Y-%m"), []).append(r.score)
    return {"days": days,
            "csat": {"count": len(csat), "average": round(sum(r.score for r in csat) / len(csat), 2) if csat else None,
                     "satisfied_percent": round(sum(1 for r in csat if r.score >= 4) * 100 / len(csat)) if csat else None,
                     "operators": sorted(({"operator": k, "count": len(v), "average": round(sum(v) / len(v), 2)} for k, v in operators.items()),
                                         key=lambda x: (-x["count"], x["operator"]))},
            "nps": {"count": len(nps), "score": nps_of([r.score for r in nps]),
                    "promoters": sum(1 for r in nps if r.score >= 9), "passives": sum(1 for r in nps if 7 <= r.score <= 8),
                    "detractors": sum(1 for r in nps if r.score <= 6),
                    "months": [{"month": k, "count": len(v), "score": nps_of(v)} for k, v in sorted(months.items())]},
            "comments": [{"kind": r.kind, "score": r.score, "comment": r.comment, "ticket_id": r.ticket_id, "operator": r.operator,
                          "at": r.created_at.isoformat()} for r in rows if r.comment][:30]}


async def _loop():
    from .db import SessionLocal
    from .main import redis_client
    while True:
        await asyncio.sleep(600)
        try:
            if redis_client is not None and not await redis_client.set("lock:feedback", "1", nx=True, ex=580):
                continue
            async with SessionLocal() as db:
                await ask_pass(db)
        except Exception as exc:  # noqa: BLE001
            logger.warning("feedback pass failed: %s", exc)


def _start():
    from .main import _track_task
    _track_task(_loop())


router.add_event_handler("startup", _start)


@router.get("/api/me/feedback")
async def my_feedback(request: Request, db: AsyncSession = Depends(get_db)):
    """What the customer can rate now: answered tickets without a score, and the NPS question of this wave."""
    from .main import user_from_token
    from .models import FeedbackRating, Notification, SupportTicket
    user = await user_from_token(request, db)
    cfg = await load(db)
    tickets = []
    if cfg["csat_enabled"]:
        rated = select(FeedbackRating.ticket_id).where(FeedbackRating.kind == "csat", FeedbackRating.ticket_id.is_not(None))
        tickets = [{"id": t.id, "subject": t.subject} for t in (await db.execute(
            select(SupportTicket).where(SupportTicket.user_id == user.id, SupportTicket.status == "resolved", SupportTicket.id.not_in(rated))
            .order_by(SupportTicket.id.desc()).limit(5))).scalars()]
    wave = period(datetime.utcnow(), int(cfg["nps_interval_days"]))
    nps_due = bool(cfg["nps_enabled"] and await db.scalar(select(Notification.id).where(Notification.user_id == user.id, Notification.dedupe_key == f"nps:{wave}"))
                   and not await db.scalar(select(FeedbackRating.id).where(FeedbackRating.kind == "nps", FeedbackRating.user_id == user.id, FeedbackRating.period == wave)))
    return {"tickets": tickets, "nps": {"wave": wave} if nps_due else None}


@router.post("/api/me/feedback/csat")
async def rate_ticket(payload: RatingIn, request: Request, db: AsyncSession = Depends(get_db)):
    from .main import user_from_token
    user = await user_from_token(request, db)
    if not (await load(db))["csat_enabled"]:
        raise HTTPException(409, "Оценки поддержки сейчас не собираются")
    return await record(db, user.id, "csat", payload.score, ticket_id=payload.ticket_id, comment=payload.comment)


@router.post("/api/me/feedback/nps")
async def rate_shop(payload: RatingIn, request: Request, db: AsyncSession = Depends(get_db)):
    from .main import user_from_token
    user = await user_from_token(request, db)
    if not (await load(db))["nps_enabled"]:
        raise HTTPException(409, "Опрос сейчас не проводится")
    return await record(db, user.id, "nps", payload.score, comment=payload.comment)


@router.get("/api/admin/feedback")
async def admin_feedback(days: int = 90, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("support.read"))):
    return {"config": await load(db), **await report(db, max(7, min(days, 365)))}


@router.put("/api/admin/feedback")
async def admin_feedback_config(payload: FeedbackConfigIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("support.write"))):
    from .main import audit
    from .node_health import _save
    await _save(db, CONFIG_KEY, payload.model_dump())
    await audit(db, "feedback.config", admin.email, None, payload.model_dump())
    await db.commit()
    return await load(db)

