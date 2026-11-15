"""Customer activity timeline: everything a customer did, on every surface, in one list in the customer card.

Two sources, merged by time:

* events written as they happen (``record``): bot start and buttons, sign-ins, screens the cabinet, Mini App and apps
  report (``POST /api/me/activity`` with a fixed list of actions), diagnostics, cart, trial;
* what the shop already keeps: payments (created, paid, refunded), subscriptions, support tickets, sign-in sessions,
  admin actions on this customer (audit log).

Rows older than 180 days are removed. «Клиенты → карточка → Действия» (web) and the customer screen of the mobile admin.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import require_permission

router = APIRouter()
SURFACES = {"bot", "cabinet", "miniapp", "android", "ios", "admin", "system"}
CLIENT_ACTIONS = {"open", "screen", "connect", "disconnect", "copy_link", "qr", "plans", "checkout", "support", "settings",
                  "devices", "referral", "gift", "wallet", "status", "docs", "diagnostics", "server_pick"}
RETENTION = timedelta(days=180)


def record(db: AsyncSession, user_id: int, surface: str, action: str, detail: dict | None = None) -> None:
    """Add an event to the session (committed with the caller's transaction)."""
    from .models import UserActivity
    if not user_id:
        return
    db.add(UserActivity(user_id=int(user_id), surface=surface if surface in SURFACES else "system", action=action[:64],
                        detail={k: str(v)[:200] for k, v in (detail or {}).items()} or None))


async def timeline(db: AsyncSession, user_id: int, limit: int = 200) -> list[dict]:
    from .models import AuditLog, Payment, Subscription, SupportTicket, UserActivity, UserSession
    out: list[dict] = []
    for r in (await db.execute(select(UserActivity).where(UserActivity.user_id == user_id)
                               .order_by(UserActivity.created_at.desc()).limit(limit))).scalars():
        out.append({"at": r.created_at, "surface": r.surface, "action": r.action, "detail": r.detail or {}})
    for p in (await db.execute(select(Payment).where(Payment.user_id == user_id).order_by(Payment.id.desc()).limit(50))).scalars():
        out.append({"at": p.created_at, "surface": "system", "action": "payment.created",
                    "detail": {"id": p.id, "amount": f"{p.amount} {p.currency}", "provider": p.provider, "status": p.status}})
        if p.paid_at:
            out.append({"at": p.paid_at, "surface": "system", "action": "payment.paid", "detail": {"id": p.id, "amount": f"{p.amount} {p.currency}"}})
    for s in (await db.execute(select(Subscription).where(Subscription.user_id == user_id).limit(20))).scalars():
        if s.expires_at:
            out.append({"at": s.expires_at, "surface": "system", "action": "subscription.ends" if s.expires_at > datetime.utcnow() else "subscription.ended",
                        "detail": {"id": s.id, "status": s.lifecycle_status}})
    for t in (await db.execute(select(SupportTicket).where(SupportTicket.user_id == user_id).order_by(SupportTicket.id.desc()).limit(30))).scalars():
        out.append({"at": t.created_at, "surface": "system", "action": "support.ticket", "detail": {"id": t.id, "subject": t.subject, "status": t.status}})
    for s in (await db.execute(select(UserSession).where(UserSession.user_id == user_id).order_by(UserSession.id.desc()).limit(30))).scalars():
        out.append({"at": s.created_at, "surface": "system", "action": "auth.session", "detail": {}})
    for a in (await db.execute(select(AuditLog).where(AuditLog.target.in_((str(user_id), f"user:{user_id}")))
                               .order_by(AuditLog.id.desc()).limit(50))).scalars():
        out.append({"at": a.created_at, "surface": "admin", "action": a.action, "detail": {"actor": a.actor}})
    out.sort(key=lambda e: e["at"] or datetime.min, reverse=True)
    return [{**e, "at": e["at"].isoformat() if e["at"] else None} for e in out[:limit]]


async def prune(db: AsyncSession, now: datetime | None = None) -> None:
    from .models import UserActivity
    await db.execute(delete(UserActivity).where(UserActivity.created_at < (now or datetime.utcnow()) - RETENTION))


class ActivityIn(BaseModel):
    surface: str = Field(pattern="^(cabinet|miniapp|android|ios)$")
    action: str = Field(max_length=32)
    screen: str = Field("", max_length=48)


@router.post("/api/me/activity")
async def my_activity(payload: ActivityIn, request: Request, db: AsyncSession = Depends(get_db)):
    from .main import user_from_token
    if payload.action not in CLIENT_ACTIONS:
        raise HTTPException(400, "Unknown action")
    user = await user_from_token(request, db)
    record(db, user.id, payload.surface, payload.action, {"screen": payload.screen} if payload.screen else None)
    await db.commit()
    return {"ok": True}


@router.get("/api/admin/users/{user_id}/activity")
async def user_activity(user_id: int, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("users.read"))):
    return {"items": await timeline(db, user_id)}
