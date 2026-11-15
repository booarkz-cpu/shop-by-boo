"""Referral contests: «кто больше приведёт друзей за месяц».

A contest has a period, a metric — ``paid`` (invited friends who paid in the period, the default: no farming with fake
accounts) or ``invited`` (friends who joined) — and prizes by place: free days (the bonus-days worker adds them to
the subscription or issues a gift code) and/or money on the balance. While it runs, customers see the leaderboard with
masked names and their own place (bot ``/contest``, cabinet, Mini App, apps). When it ends the shop fixes the results
and hands out the prizes once. «Рефералы → Конкурсы» (web) and the mobile admin card.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import require_permission

logger = logging.getLogger("vpnshop.contests")
router = APIRouter()


class PrizeIn(BaseModel):
    place: int = Field(ge=1, le=100)
    days: int = Field(0, ge=0, le=365)
    amount: Decimal = Field(Decimal("0"), ge=0, le=1_000_000)


class ContestIn(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    starts_at: datetime
    ends_at: datetime
    metric: str = Field("paid", pattern="^(paid|invited)$")
    prizes: list[PrizeIn] = Field(min_length=1, max_length=20)


def mask(name: str | None, user_id: int) -> str:
    name = (name or "").strip() or f"клиент {user_id}"
    return name[:2] + "•••" if len(name) > 2 else name + "•••"


async def leaderboard(db: AsyncSession, contest, limit: int = 20) -> list[dict]:
    from .models import Payment, User
    friend = User.__table__.alias("friend")
    if contest.metric == "invited":
        query = (select(friend.c.referred_by_id, func.count(friend.c.id)).where(
            friend.c.referred_by_id.is_not(None), friend.c.created_at >= contest.starts_at, friend.c.created_at < contest.ends_at,
            friend.c.deleted_at.is_(None)).group_by(friend.c.referred_by_id))
    else:
        query = (select(friend.c.referred_by_id, func.count(func.distinct(friend.c.id))).select_from(friend)
                 .join(Payment, Payment.user_id == friend.c.id).where(
            friend.c.referred_by_id.is_not(None), Payment.paid_at >= contest.starts_at, Payment.paid_at < contest.ends_at,
            Payment.purpose == "subscription", Payment.status.in_(("paid", "fulfilled"))).group_by(friend.c.referred_by_id))
    rows = sorted(((int(uid), int(n)) for uid, n in (await db.execute(query)).all()), key=lambda r: (-r[1], r[0]))
    users = {u.id: u for u in (await db.execute(select(User).where(User.id.in_([r[0] for r in rows[:limit]])))).scalars()}
    return [{"place": i + 1, "user_id": uid, "name": mask(users.get(uid).username if users.get(uid) else None, uid), "score": n}
            for i, (uid, n) in enumerate(rows[:limit])]


async def current(db: AsyncSession, now: datetime | None = None):
    from .models import ReferralContest
    now = now or datetime.utcnow()
    return await db.scalar(select(ReferralContest).where(ReferralContest.status == "active", ReferralContest.starts_at <= now,
                                                         ReferralContest.ends_at > now).order_by(ReferralContest.id.desc()).limit(1))


async def finish_due(db: AsyncSession, now: datetime | None = None) -> list[int]:
    """Fix the results of ended contests and hand out the prizes (each contest once)."""
    from .main import record_financial_event
    from .models import Job, ReferralContest, User
    now = now or datetime.utcnow()
    done = []
    for contest in (await db.execute(select(ReferralContest).where(ReferralContest.status == "active", ReferralContest.ends_at <= now)
                                     .with_for_update())).scalars().all():
        board = await leaderboard(db, contest, limit=100)
        prizes = {int(p["place"]): p for p in contest.prizes}
        results = []
        for row in board:
            prize = prizes.get(row["place"])
            if not prize or row["score"] <= 0:
                continue
            if int(prize.get("days") or 0) > 0:
                key = f"bonus_days:contest:{contest.id}:{row['user_id']}"
                if not await db.scalar(select(Job.id).where(Job.job_key == key)):
                    db.add(Job(job_key=key, kind="bonus_days", status="queued",
                               payload={"user_id": row["user_id"], "days": int(prize["days"]), "reason": "contest"}))
            amount = Decimal(str(prize.get("amount") or 0))
            if amount > 0:
                user = await db.scalar(select(User).where(User.id == row["user_id"]).with_for_update())
                if user:
                    user.wallet_balance = (Decimal(str(user.wallet_balance or 0)) + amount).quantize(Decimal("0.01"))
                    await record_financial_event(db, operation_key=f"contest:{contest.id}:{user.id}", user_id=user.id, payment_id=None,
                                                 kind="contest_prize", direction="credit", amount=amount, currency="RUB",
                                                 metadata={"contest_id": contest.id, "place": row["place"]})
            results.append({**row, "days": int(prize.get("days") or 0), "amount": str(amount)})
        contest.results = results
        contest.status = "finished"
        done.append(contest.id)
    await db.commit()
    return done


async def _loop():
    from .db import SessionLocal
    from .main import redis_client
    while True:
        await asyncio.sleep(600)
        try:
            if redis_client is not None and not await redis_client.set("lock:contests", "1", nx=True, ex=550):
                continue
            async with SessionLocal() as db:
                await finish_due(db)
        except Exception as exc:  # noqa: BLE001
            logger.warning("contest pass failed: %s", exc)


def _start():
    from .main import _track_task
    _track_task(_loop())


router.add_event_handler("startup", _start)


def public(contest, board: list[dict], me: int | None) -> dict:
    mine = next((r for r in board if r["user_id"] == me), None)
    return {"id": contest.id, "title": contest.title, "ends_at": contest.ends_at.isoformat(), "metric": contest.metric,
            "prizes": contest.prizes, "top": [{k: r[k] for k in ("place", "name", "score")} for r in board[:10]],
            "me": {"place": mine["place"], "score": mine["score"]} if mine else None}


@router.get("/api/me/referral-contest")
async def my_contest(request: Request, db: AsyncSession = Depends(get_db)):
    from .main import user_from_token
    user = await user_from_token(request, db)
    contest = await current(db)
    if not contest:
        return {"contest": None}
    return {"contest": public(contest, await leaderboard(db, contest, 100), user.id)}


@router.get("/api/admin/referral-contests")
async def list_contests(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("referrals.read"))):
    from .models import ReferralContest
    rows = (await db.execute(select(ReferralContest).order_by(ReferralContest.id.desc()).limit(50))).scalars().all()
    out = []
    for c in rows:
        out.append({"id": c.id, "title": c.title, "starts_at": c.starts_at.isoformat(), "ends_at": c.ends_at.isoformat(),
                    "metric": c.metric, "prizes": c.prizes, "status": c.status,
                    "top": (c.results if c.status == "finished" else await leaderboard(db, c, 10))})
    return {"contests": out}


@router.post("/api/admin/referral-contests")
async def create_contest(payload: ContestIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("referrals.reconcile"))):
    from .main import audit
    from .models import ReferralContest
    if payload.ends_at <= payload.starts_at:
        raise HTTPException(400, "Конец конкурса должен быть позже начала")
    places = [p.place for p in payload.prizes]
    if len(set(places)) != len(places):
        raise HTTPException(400, "Места призов повторяются")
    row = ReferralContest(title=payload.title.strip(), starts_at=payload.starts_at.replace(tzinfo=None),
                          ends_at=payload.ends_at.replace(tzinfo=None), metric=payload.metric,
                          prizes=[{"place": p.place, "days": p.days, "amount": str(p.amount)} for p in payload.prizes], created_at=datetime.utcnow())
    db.add(row)
    await db.flush()
    await audit(db, "referrals.contest.created", admin.email, str(row.id), {"title": row.title})
    await db.commit()
    return {"id": row.id}


@router.delete("/api/admin/referral-contests/{contest_id}")
async def cancel_contest(contest_id: int, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("referrals.reconcile"))):
    from .models import ReferralContest
    row = await db.get(ReferralContest, contest_id)
    if not row or row.status != "active":
        raise HTTPException(404, "Активный конкурс не найден")
    row.status = "cancelled"
    await db.commit()
    return {"ok": True}
