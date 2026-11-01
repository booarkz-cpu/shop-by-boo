"""Family plans, retention analytics and the public status page.

Family plans
------------
A plan with ``family_seats > 0`` lets its buyer invite that many people. Each member gets
an own shop subscription and an own Remnawave user (own link and device limit) whose
expiry always follows the owner's subscription: renewing the owner renews everyone, an
expired or refunded owner subscription ends the members' access. The owner shares an
invite link (bot ``/start family_<code>`` or the cabinet ``?family=<code>``), sees the
members and can remove them; a member can leave. The worker synchronises members every
five minutes (``family_scheduler``) and right after a member joins.

Retention
---------
``GET /api/admin/analytics/retention`` — monthly cohorts by the first paid order: size,
share that paid again, share active now, revenue and revenue per customer (LTV), plus the
cancellation survey (``cancellation_feedback``) and the overall renewal rate.

Status page
-----------
``GET /api/public/service-status`` — no login: share of online servers by country (no addresses)
and open incidents of the «service» category from «Инциденты».
"""
from __future__ import annotations

import asyncio
import logging
import secrets
from datetime import datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .economics import window_start
from .db import get_db
from .models import CancellationFeedback, FamilyGroup, FamilyMember, Payment, Plan, Subscription, User
from .security import require_permission

logger = logging.getLogger(__name__)
router = APIRouter()
LIVE = {"active", "cancel_scheduled", "grace"}
SYNC_SECONDS = 300


# ================================================================ family

def _live(sub: Subscription | None, now: datetime | None = None) -> bool:
    now = now or datetime.utcnow()
    return bool(sub and sub.lifecycle_status in LIVE and sub.expires_at and sub.expires_at > now)


async def _seats(db: AsyncSession, sub: Subscription) -> int:
    plan = await db.get(Plan, sub.plan_id) if sub.plan_id else None
    return int(plan.family_seats or 0) if plan else 0


def _links(code: str) -> dict:
    out = {"code": code}
    if settings.bot_username:
        out["bot"] = f"https://t.me/{settings.bot_username}?start=family_{code}"
    base = (settings.cabinet_url or settings.mini_app_url or "").split("#")[0].rstrip("/")
    if base.startswith("https://"):
        out["cabinet"] = f"{base}/?family={code}"
    return out


async def _members(db: AsyncSession, group: FamilyGroup) -> list[FamilyMember]:
    return (await db.execute(select(FamilyMember).where(FamilyMember.group_id == group.id, FamilyMember.status == "active")
                             .order_by(FamilyMember.id))).scalars().all()


@router.get("/api/me/family")
async def my_family(request: Request, db: AsyncSession = Depends(get_db)):
    from .main import user_from_token
    user = await user_from_token(request, db)
    owned = []
    subs = (await db.execute(select(Subscription).where(Subscription.user_id == user.id).order_by(Subscription.id))).scalars().all()
    for sub in subs:
        seats = await _seats(db, sub)
        if seats <= 0 or not _live(sub):
            continue
        group = await db.scalar(select(FamilyGroup).where(FamilyGroup.owner_subscription_id == sub.id))
        members = await _members(db, group) if group else []
        names = {u.id: (u.username or u.email or f"#{u.id}") for u in (await db.execute(select(User).where(User.id.in_([m.user_id for m in members] or [0])))).scalars()}
        # v28.54: the filter of each member's subscription (the owner switches the children's mode, dns_filter.py).
        from .dns_filter import load as filter_config, modes as filter_modes
        fcfg = await filter_config(db)
        filters = {x.id: x.dns_filter for x in (await db.execute(select(Subscription).where(
            Subscription.id.in_([m.subscription_id for m in members if m.subscription_id] or [0])))).scalars()}
        owned.append({"subscription_id": sub.id, "name": sub.name, "seats": seats, "used": len(members), "expires_at": sub.expires_at,
                      "invite": _links(group.invite_code) if group else None,
                      "filter_modes": filter_modes(fcfg, sub.remnawave_profile_id_snapshot),
                      "members": [{"id": m.id, "name": names.get(m.user_id, ""), "joined_at": m.joined_at,
                                   "synced": bool(m.synced_at), "error": bool(m.sync_error), "filter": filters.get(m.subscription_id)} for m in members]})
    member_rows = (await db.execute(select(FamilyMember).where(FamilyMember.user_id == user.id, FamilyMember.status == "active"))).scalars().all()
    member_of = []
    for m in member_rows:
        group = await db.get(FamilyGroup, m.group_id)
        owner = await db.get(User, group.owner_user_id) if group else None
        owner_sub = await db.get(Subscription, group.owner_subscription_id) if group else None
        member_of.append({"id": m.id, "owner": (owner.username or "владелец") if owner else "", "expires_at": owner_sub.expires_at if owner_sub else None,
                          "subscription_id": m.subscription_id})
    return {"owned": owned, "member_of": member_of}


@router.post("/api/me/family/{subscription_id}/invite")
async def family_invite(subscription_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    """Create (or rotate with ?rotate=1) the invite code of an owned family subscription."""
    from .main import audit, user_from_token
    user = await user_from_token(request, db)
    sub = await db.scalar(select(Subscription).where(Subscription.id == subscription_id, Subscription.user_id == user.id))
    if not sub or not _live(sub):
        raise HTTPException(404, "Активная подписка не найдена")
    if await _seats(db, sub) <= 0:
        raise HTTPException(409, "Тариф этой подписки не семейный")
    group = await db.scalar(select(FamilyGroup).where(FamilyGroup.owner_subscription_id == sub.id).with_for_update())
    if not group:
        group = FamilyGroup(owner_user_id=user.id, owner_subscription_id=sub.id)
        db.add(group)
    elif request.query_params.get("rotate") == "1":
        group.invite_code = secrets.token_urlsafe(9).replace("-", "x").replace("_", "y")
    await db.flush()
    await audit(db, "family.invite", f"user:{user.id}", str(sub.id))
    await db.commit()
    return _links(group.invite_code)


class JoinIn(BaseModel):
    code: str = Field(min_length=6, max_length=32, pattern=r"^[A-Za-z0-9]+$")


@router.post("/api/me/family/join")
async def family_join(payload: JoinIn, request: Request, db: AsyncSession = Depends(get_db)):
    from .main import _advisory_lock, audit, user_from_token
    from .platform_api import reject_restricted
    user = await user_from_token(request, db)
    reject_restricted(user)
    group = await db.scalar(select(FamilyGroup).where(FamilyGroup.invite_code == payload.code))
    if not group:
        raise HTTPException(404, "Приглашение не найдено или устарело")
    await _advisory_lock(db, 730000000 + int(group.id))
    owner_sub = await db.get(Subscription, group.owner_subscription_id)
    if not _live(owner_sub):
        raise HTTPException(409, "Семейная подписка владельца не активна")
    if group.owner_user_id == user.id:
        raise HTTPException(409, "Это ваша семейная подписка")
    existing = await db.scalar(select(FamilyMember).where(FamilyMember.group_id == group.id, FamilyMember.user_id == user.id))
    if existing and existing.status == "active":
        return {"ok": True, "member_id": existing.id, "already": True}
    if len(await _members(db, group)) >= await _seats(db, owner_sub):
        raise HTTPException(409, "Все места в семейной подписке заняты")
    count = await db.scalar(select(func.count()).select_from(Subscription).where(Subscription.user_id == user.id))
    if int(count or 0) >= 20:
        raise HTTPException(409, "Достигнут лимит 20 подписок")
    has_primary = await db.scalar(select(Subscription.id).where(Subscription.user_id == user.id, Subscription.is_primary.is_(True)))
    sub = Subscription(user_id=user.id, plan_id=owner_sub.plan_id, is_primary=not has_primary, lifecycle_status="pending",
                       name="Семейная подписка", expires_at=None, unit_price_per_day=0)
    db.add(sub)
    await db.flush()
    if existing:
        existing.status, existing.removed_at, existing.subscription_id, existing.joined_at = "active", None, sub.id, datetime.utcnow()
        member = existing
    else:
        member = FamilyMember(group_id=group.id, user_id=user.id, subscription_id=sub.id)
        db.add(member)
    await db.flush()
    await audit(db, "family.joined", f"user:{user.id}", str(group.id), {"member": member.id})
    await db.commit()
    try:
        await sync_member(db, member.id)
    except Exception as exc:  # the scheduler retries
        logger.warning("family member %s first sync failed: %s", member.id, exc)
    return {"ok": True, "member_id": member.id}


@router.delete("/api/me/family/members/{member_id}")
async def family_remove(member_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    """The owner removes a member, or a member leaves."""
    from .main import audit, user_from_token
    user = await user_from_token(request, db)
    member = await db.get(FamilyMember, member_id)
    group = await db.get(FamilyGroup, member.group_id) if member else None
    if not member or not group or user.id not in {member.user_id, group.owner_user_id} or member.status != "active":
        raise HTTPException(404, "Участник не найден")
    member.status, member.removed_at = "removed", datetime.utcnow()
    await audit(db, "family.removed", f"user:{user.id}", str(member.id), {"by_owner": user.id == group.owner_user_id})
    await db.commit()
    await sync_member(db, member.id)
    return {"ok": True}


async def sync_member(db: AsyncSession, member_id: int, rw=None) -> str:
    """Make the member's Remnawave user follow the owner's subscription (idempotent)."""
    from .main import RemnawaveClient
    rw = rw or RemnawaveClient()
    member = await db.get(FamilyMember, member_id)
    group = await db.get(FamilyGroup, member.group_id) if member else None
    if not member or not group:
        return "missing"
    sub = await db.get(Subscription, member.subscription_id) if member.subscription_id else None
    owner_sub = await db.get(Subscription, group.owner_subscription_id)
    now = datetime.utcnow()
    if not sub:
        return "missing"
    try:
        seats = await _seats(db, owner_sub) if owner_sub else 0
        seated = [m.id for m in (await _members(db, group))[:seats]]
        if member.status != "active" or not _live(owner_sub, now) or member.id not in seated:
            # Ended, owner not live, or the owner moved to a plan with fewer family seats:
            # the oldest members keep their seats, the rest lose access until seats return.
            if sub.remnawave_uuid and sub.lifecycle_status != "expired":
                await rw.disable_user(sub.remnawave_uuid)
            sub.lifecycle_status, sub.expires_at = "expired", min(sub.expires_at or now, now)
            result = "ended" if member.status != "active" or not _live(owner_sub, now) else "no_seat"
        else:
            plan = await db.get(Plan, owner_sub.plan_id)
            target = owner_sub.expires_at
            traffic = owner_sub.traffic_limit_gb_snapshot if owner_sub.traffic_limit_gb_snapshot is not None else (plan.traffic_limit_gb if plan else None)
            devices = owner_sub.device_limit_snapshot if owner_sub.device_limit_snapshot is not None else (plan.device_limit if plan else None)
            profile = owner_sub.remnawave_profile_id_snapshot or (plan.remnawave_profile_id if plan else None)
            if not sub.remnawave_uuid:
                user = await db.get(User, member.user_id)
                data = await rw.create_user(f"user_{member.user_id}_sub_{sub.id}", target, int(traffic) * 1024 ** 3 if traffic else 0,
                                            active_internal_squads=[profile] if profile else None,
                                            telegram_id=user.telegram_id if user else None, device_limit=devices)
                if not data or not data.get("id"):
                    raise RuntimeError("Remnawave returned no user id")
                sub.remnawave_uuid = str(data["id"])
                sub.subscription_url = data.get("subscriptionUrl") or data.get("subscription_url")
                result = "created"
            else:
                if sub.lifecycle_status == "expired":
                    await rw.enable_user(sub.remnawave_uuid)
                if not sub.expires_at or abs((sub.expires_at - target).total_seconds()) > 60:
                    await rw.patch_user(sub.remnawave_uuid, {"expireAt": target.isoformat()})
                if (sub.traffic_limit_gb_snapshot, sub.device_limit_snapshot, sub.remnawave_profile_id_snapshot) != (traffic, devices, profile):
                    # The owner changed plan: traffic, devices and squad follow, not only the expiry.
                    await rw.update_entitlements(sub.remnawave_uuid, traffic, profile, device_limit=devices)
                result = "updated"
            sub.expires_at, sub.lifecycle_status, sub.plan_id = target, "active", owner_sub.plan_id
            sub.traffic_limit_gb_snapshot, sub.device_limit_snapshot, sub.remnawave_profile_id_snapshot = traffic, devices, profile
        member.synced_at, member.sync_error = now, None
    except Exception as exc:
        member.sync_error = str(exc)[:500]
        await db.commit()
        raise
    await db.commit()
    return result


async def family_scheduler(session_factory=None):
    from .db import engine
    from sqlalchemy.ext.asyncio import AsyncSession as Session
    factory = session_factory or (lambda: Session(engine, expire_on_commit=False))
    while True:
        try:
            async with factory() as db:
                ids = (await db.execute(select(FamilyMember.id).join(Subscription, Subscription.id == FamilyMember.subscription_id).where(
                    (FamilyMember.status == "active") | (Subscription.lifecycle_status != "expired")))).scalars().all()
                for member_id in ids[:500]:
                    try:
                        await sync_member(db, member_id)
                    except Exception as exc:
                        logger.warning("family sync %s: %s", member_id, exc)
        except Exception:
            logger.exception("family scheduler failed")
        await asyncio.sleep(SYNC_SECONDS)


@router.get("/api/admin/family")
async def admin_family(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("read"))):
    groups = (await db.execute(select(FamilyGroup).order_by(FamilyGroup.id.desc()).limit(200))).scalars().all()
    by_group: dict[int, list] = {}
    if groups:  # one query for all members instead of one per family
        for m in (await db.execute(select(FamilyMember).where(FamilyMember.group_id.in_([g.id for g in groups])).order_by(FamilyMember.id))).scalars():
            by_group.setdefault(m.group_id, []).append(m)
    out = []
    for g in groups:
        members = by_group.get(g.id, [])
        out.append({"id": g.id, "owner_user_id": g.owner_user_id, "subscription_id": g.owner_subscription_id, "created_at": g.created_at,
                    "members": [{"id": m.id, "user_id": m.user_id, "status": m.status, "synced_at": m.synced_at, "error": m.sync_error} for m in members]})
    return out


# ================================================================ retention

REASONS = {"price": "Дорого", "speed": "Низкая скорость", "stability": "Нестабильно работает", "not_needed": "Больше не нужен",
           "other_service": "Перешёл к другому сервису", "other": "Другое"}


@router.get("/api/admin/analytics/retention")
async def retention(months: int = 12, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("read"))):
    months = max(1, min(months, 24))
    now = datetime.utcnow()
    # One row per customer, aggregated by the database: first payment, number of
    # payments and revenue. The payments table is never loaded into memory.
    per_user = (await db.execute(select(Payment.user_id, func.min(Payment.paid_at), func.count(Payment.id),
                                        func.coalesce(func.sum(Payment.amount), 0)).where(
        Payment.status.in_(("paid", "fulfilled")), Payment.paid_at.is_not(None), Payment.purpose == "subscription")
        .group_by(Payment.user_id))).all()
    active = set((await db.execute(select(Subscription.user_id).where(Subscription.lifecycle_status.in_(LIVE), Subscription.expires_at > now).distinct())).scalars())
    cohorts: dict[str, dict] = {}
    # Calendar months, not 30-day blocks: a 31-day step overshoots across a 30- or 28-day month and the
    # table then shows one month more than asked for.
    start = window_start(now, months)
    customers = len(per_user)
    total = Decimal("0")
    repeat = 0
    for user_id, first, count, revenue in per_user:
        revenue = Decimal(str(revenue or 0))
        total += revenue
        repeat += 1 if count > 1 else 0
        if isinstance(first, str):  # SQLite returns aggregated timestamps as text
            first = datetime.fromisoformat(first)
        if first < start:
            continue
        key = first.strftime("%Y-%m")
        c = cohorts.setdefault(key, {"month": key, "customers": 0, "repeat": 0, "active": 0, "revenue": Decimal("0")})
        c["customers"] += 1
        c["repeat"] += 1 if count > 1 else 0
        c["active"] += 1 if user_id in active else 0
        c["revenue"] += revenue
    table = []
    for key in sorted(cohorts):
        c = cohorts[key]
        n = c["customers"] or 1
        table.append({"month": key, "customers": c["customers"], "repeat_rate": round(c["repeat"] * 100 / n, 1),
                      "active_rate": round(c["active"] * 100 / n, 1), "revenue": str(c["revenue"].quantize(Decimal(".01"))),
                      "ltv": str((c["revenue"] / n).quantize(Decimal(".01")))})
    feedback = (await db.execute(select(CancellationFeedback.reason, func.count()).where(
        CancellationFeedback.created_at >= now - timedelta(days=90)).group_by(CancellationFeedback.reason))).all()
    comments = (await db.execute(select(CancellationFeedback).where(CancellationFeedback.comment != "").order_by(
        CancellationFeedback.id.desc()).limit(20))).scalars().all()
    return {"currency": settings.default_currency, "customers": customers,
            "ltv": str((total / customers).quantize(Decimal(".01"))) if customers else "0.00",
            "repeat_rate": round(repeat * 100 / customers, 1) if customers else 0.0,
            "active_customers": len(active), "cohorts": table,
            "cancel_reasons": [{"reason": r, "label": REASONS.get(r, r), "count": n} for r, n in sorted(feedback, key=lambda x: -x[1])],
            "recent_comments": [{"reason": REASONS.get(c.reason, c.reason), "comment": c.comment, "created_at": c.created_at} for c in comments]}


# ================================================================ status page

@router.get("/api/public/service-status")
async def public_status(db: AsyncSession = Depends(get_db)):
    from .models import SecurityIncidentEvent
    from .tariff_api import remnawave_server_status
    servers = await remnawave_server_status("public")
    countries: dict[str, dict] = {}
    for node in servers.get("nodes", []):
        c = countries.setdefault(str(node.get("country") or "—"), {"country": str(node.get("country") or "—"), "total": 0, "online": 0})
        c["total"] += 1
        c["online"] += 1 if node.get("status") == "online" else 0
    incidents = (await db.execute(select(SecurityIncidentEvent).where(SecurityIncidentEvent.category == "service",
                                                                      SecurityIncidentEvent.status != "resolved")
                                  .order_by(SecurityIncidentEvent.id.desc()).limit(10))).scalars().all()
    from .models import StatusComponent
    components = (await db.execute(select(StatusComponent).where(StatusComponent.enabled.is_(True))
                                   .order_by(StatusComponent.sort_order, StatusComponent.id))).scalars().all()
    total, online = servers.get("total", 0), servers.get("online", 0)
    broken = any(c.status != "operational" for c in components)
    level = "unknown" if not servers.get("ok") else "ok" if total and online == total and not incidents and not broken else "degraded" if online else "down"
    return {"status": level, "checked_at": datetime.utcnow(), "servers": {"total": total, "online": online},
            "countries": sorted(countries.values(), key=lambda c: c["country"]),
            "components": [{"name": c.name, "status": c.status, "message": c.message} for c in components],
            "incidents": [{"title": i.title, "severity": i.severity, "since": i.created_at} for i in incidents]}
