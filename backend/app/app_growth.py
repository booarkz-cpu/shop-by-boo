"""App growth tools: segmented push campaigns and anonymous app analytics.

Push campaigns («Приложения: push-кампании») create one in-app notification per user of a
segment; the push worker (push.py) delivers it to every app installation of that user that has
push switched on. Segments are computed on the server at send time, the preview shows the reach.

App analytics («Приложения: аналитика») counts what happens in the Android/iOS apps: first
launch, sign-in, «Подключить», screens, checkout. Events carry a random installation id that the
server stores only as a keyed hash, the platform, the app version and the screen — no IP, no
device model, no advertising identifiers. The administrator switches collection off with the
layout feature «analytics»; the apps then send nothing and the server drops what arrives.
"""
from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import and_, distinct, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import get_db
from .models import AppEvent, Notification, Payment, PushCampaign, PushDevice, Subscription, User, UserSession
from .security import require_permission

router = APIRouter()

__all__ = ["router", "enqueue_expiry_notifications", "SEGMENTS", "EVENTS", "segment_users", "send_campaign", "record_events", "summary", "install_hash"]

SEGMENTS: dict[str, str] = {
    "all": "Все пользователи",
    "app_users": "Установили приложение (есть push)",
    "expiring": "Подписка заканчивается в ближайшие N дней",
    "expired": "Подписка закончилась за последние N дней",
    "no_subscription": "Ещё не покупали подписку",
    "inactive": "Не открывали приложение N дней",
}
EVENTS = ("install", "open", "sign_in_view", "sign_in", "screen", "connect_tap", "connected", "trial_tap",
          "checkout_start", "checkout_done", "promo_tap", "giveaway_enter")
PLATFORMS = ("android", "ios")
ACTIVE = ("active", "cancel_scheduled")
RETENTION_DAYS = 180
DAILY_LIMIT = 500


# ------------------------------------------------------------------ campaigns

def _segment_query(segment: str, days: int, now: datetime):
    live = select(User.id).where(User.deleted_at.is_(None), User.merged_into_user_id.is_(None))
    has_active = exists().where(Subscription.user_id == User.id, Subscription.lifecycle_status.in_(ACTIVE),
                                Subscription.expires_at > now)
    if segment == "all":
        return live
    if segment == "app_users":
        return live.where(exists().where(PushDevice.user_id == User.id, PushDevice.revoked_at.is_(None)))
    if segment == "expiring":
        soon = exists().where(Subscription.user_id == User.id, Subscription.lifecycle_status.in_(ACTIVE),
                              Subscription.expires_at > now, Subscription.expires_at <= now + timedelta(days=days))
        # Someone with a second, longer subscription is not «about to lose VPN».
        later = exists().where(Subscription.user_id == User.id, Subscription.lifecycle_status.in_(ACTIVE),
                               Subscription.expires_at > now + timedelta(days=days))
        return live.where(soon, ~later)
    if segment == "expired":
        ended = exists().where(Subscription.user_id == User.id, Subscription.expires_at <= now,
                               Subscription.expires_at > now - timedelta(days=days))
        return live.where(ended, ~has_active)
    if segment == "no_subscription":
        return live.where(~exists().where(Subscription.user_id == User.id))
    if segment == "inactive":
        recent = exists().where(UserSession.user_id == User.id, UserSession.last_seen_at > now - timedelta(days=days))
        return live.where(exists().where(PushDevice.user_id == User.id, PushDevice.revoked_at.is_(None)), ~recent)
    raise HTTPException(422, "Unknown segment")


async def segment_users(db: AsyncSession, segment: str, days: int, now: datetime | None = None) -> list[int]:
    now = now or datetime.utcnow()
    return list((await db.execute(_segment_query(segment, days, now).order_by(User.id))).scalars().all())


async def _with_push(db: AsyncSession, user_ids: list[int]) -> int:
    total = 0
    for start in range(0, len(user_ids), 1000):
        chunk = user_ids[start:start + 1000]
        total += int(await db.scalar(select(func.count(distinct(PushDevice.user_id))).where(
            PushDevice.user_id.in_(chunk), PushDevice.revoked_at.is_(None))) or 0)
    return total


class CampaignIn(BaseModel):
    segment: str = Field(pattern=r"^(all|app_users|expiring|expired|no_subscription|inactive)$")
    days: int = Field(default=3, ge=1, le=90)
    title: str = Field(default="", max_length=120)
    body: str = Field(default="", max_length=1000)


class CampaignPreviewIn(BaseModel):
    segment: str = Field(pattern=r"^(all|app_users|expiring|expired|no_subscription|inactive)$")
    days: int = Field(default=3, ge=1, le=90)


async def send_campaign(db: AsyncSession, payload: CampaignIn, actor: str, now: datetime | None = None) -> PushCampaign:
    now = now or datetime.utcnow()
    title, body = " ".join(payload.title.split()), payload.body.strip()
    if not title or not body:
        raise HTTPException(422, "Заголовок и текст обязательны")
    users = await segment_users(db, payload.segment, payload.days, now)
    campaign = PushCampaign(title=title, body=body, segment=payload.segment, days=payload.days, status="sending",
                            recipients=len(users), with_push=await _with_push(db, users), created_by=actor[:320], created_at=now)
    db.add(campaign)
    await db.flush()
    key = f"campaign:{campaign.id}"
    for user_id in users:
        # push_fanout_at stays empty: the push worker fans it out to the devices of the user.
        db.add(Notification(user_id=user_id, channel="in_app", kind="campaign", title=title, body=body,
                            dedupe_key=key, status="sent", sent_at=now, created_at=now))
    campaign.status = "sent"
    return campaign


def _campaign(row: PushCampaign) -> dict:
    return {"id": row.id, "title": row.title, "body": row.body, "segment": row.segment, "days": row.days,
            "status": row.status, "recipients": row.recipients, "with_push": row.with_push,
            "created_by": row.created_by, "created_at": row.created_at}


@router.get("/api/admin/push-campaigns")
async def list_campaigns(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("marketing.read"))):
    from .push import provider_ready

    rows = (await db.execute(select(PushCampaign).order_by(PushCampaign.id.desc()).limit(50))).scalars().all()
    return {"segments": SEGMENTS, "push_ready": {p: provider_ready(p) for p in ("fcm", "apns")},
            "items": [_campaign(r) for r in rows]}


@router.post("/api/admin/push-campaigns/preview")
async def preview_campaign(payload: CampaignPreviewIn, db: AsyncSession = Depends(get_db),
                           admin=Depends(require_permission("marketing.read"))):
    users = await segment_users(db, payload.segment, payload.days)
    return {"recipients": len(users), "with_push": await _with_push(db, users)}


@router.post("/api/admin/push-campaigns")
async def create_campaign(payload: CampaignIn, db: AsyncSession = Depends(get_db),
                          admin=Depends(require_permission("manage_broadcasts"))):
    from .main import audit

    row = await send_campaign(db, payload, admin.email)
    await audit(db, "push_campaign.sent", admin.email, str(row.id),
                {"segment": row.segment, "days": row.days, "recipients": row.recipients, "with_push": row.with_push})
    await db.commit()
    return _campaign(row)


# ------------------------------------------------------------------ expiry reminders

async def enqueue_expiry_notifications(db: AsyncSession, now: datetime | None = None) -> int:
    from . import main as shop
    """One «подписка заканчивается» notification per subscription and expiry date."""
    now=now or datetime.utcnow()
    until=now+timedelta(days=settings.notification_expiry_days)
    rows=(await db.execute(select(Subscription).join(User,User.id==Subscription.user_id).where(
        User.deleted_at.is_(None),Subscription.lifecycle_status.in_(("active","cancel_scheduled")),
        Subscription.expires_at>now,Subscription.expires_at<=until).limit(1000))).scalars().all()
    created=0
    for sub in rows:
        days=max(1,(sub.expires_at-now).days+(1 if (sub.expires_at-now).seconds else 0))
        key=f"expiry:{sub.id}:{sub.expires_at.date()}"
        before=await db.scalar(select(Notification.id).where(Notification.user_id==sub.user_id,Notification.dedupe_key==key))
        if before: continue
        await shop.enqueue_notification(db,user_id=sub.user_id,channel="in_app",kind="subscription_expiring",
            title="Подписка заканчивается",body=f"VPN работает до {sub.expires_at:%d.%m.%Y} — осталось {days} дн. Продлите, чтобы не потерять доступ.",dedupe_key=key)
        created+=1
    await db.commit()
    return created


# ------------------------------------------------------------------ analytics

def install_hash(install_id: str) -> str:
    return hmac.new(settings.app_secret.encode(), ("app-install:" + install_id).encode(), hashlib.sha256).hexdigest()


class EventIn(BaseModel):
    event: str = Field(pattern=r"^[a-z_]{2,32}$")
    screen: str = Field(default="", pattern=r"^[a-z0-9_-]{0,32}$")


class EventsIn(BaseModel):
    install_id: str = Field(pattern=r"^[A-Za-z0-9-]{16,64}$")
    platform: str = Field(pattern=r"^(android|ios)$")
    app_version: str = Field(default="", pattern=r"^[0-9A-Za-z.+-]{0,32}$")
    events: list[EventIn] = Field(min_length=1, max_length=50)


async def analytics_enabled(db: AsyncSession) -> bool:
    from .mobile_layout import load

    return (await load(db)).features.get("analytics", True)


async def record_events(db: AsyncSession, payload: EventsIn, user_id: int | None, now: datetime | None = None) -> int:
    now = now or datetime.utcnow()
    digest = install_hash(payload.install_id)
    # One installation cannot flood the table: at most DAILY_LIMIT events a day are stored.
    today = int(await db.scalar(select(func.count(AppEvent.id)).where(AppEvent.install_hash == digest,
                                                                   AppEvent.created_at >= now - timedelta(days=1))) or 0)
    room = max(0, DAILY_LIMIT - today)
    accepted = 0
    for item in payload.events[:room]:
        if item.event not in EVENTS:
            continue
        if item.event == "install" and await db.scalar(select(AppEvent.id).where(
                AppEvent.install_hash == digest, AppEvent.event == "install").limit(1)):
            continue  # a reinstall-free relaunch never counts twice
        db.add(AppEvent(install_hash=digest, user_id=user_id, platform=payload.platform, app_version=payload.app_version,
                        event=item.event, screen=item.screen if item.event == "screen" else "", created_at=now))
        accepted += 1
    return accepted


@router.post("/api/mobile/events")
async def collect_events(payload: EventsIn, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    if not await analytics_enabled(db):
        return {"accepted": 0, "enabled": False}
    user_id = None
    if request.headers.get("authorization", "").startswith("Bearer "):
        from .main import user_from_token

        try:
            user_id = (await user_from_token(request, db)).id
        except HTTPException:
            user_id = None  # an expired session still counts the event, without the account
    accepted = await record_events(db, payload, user_id)
    await db.commit()
    return {"accepted": accepted, "enabled": True}


async def summary(db: AsyncSession, days: int, platform: str = "", now: datetime | None = None) -> dict:
    now = now or datetime.utcnow()
    since = now - timedelta(days=days)
    scope = [AppEvent.created_at >= since]
    if platform:
        scope.append(AppEvent.platform == platform)

    async def installs_with(event: str) -> int:
        return int(await db.scalar(select(func.count(distinct(AppEvent.install_hash))).where(*scope, AppEvent.event == event)) or 0)

    counts = dict((await db.execute(select(AppEvent.event, func.count(AppEvent.id)).where(*scope).group_by(AppEvent.event))).all())
    active = int(await db.scalar(select(func.count(distinct(AppEvent.install_hash))).where(*scope)) or 0)
    app_users = select(distinct(AppEvent.user_id)).where(*scope, AppEvent.user_id.is_not(None))
    paid_users = int(await db.scalar(select(func.count(distinct(Payment.user_id))).where(
        Payment.user_id.in_(app_users), Payment.status == "paid", Payment.created_at >= since)) or 0)
    funnel = [
        {"step": "install", "title": "Установка", "count": await installs_with("install")},
        {"step": "sign_in", "title": "Вход", "count": await installs_with("sign_in")},
        {"step": "connect_tap", "title": "Нажали «Подключить»", "count": await installs_with("connect_tap")},
        {"step": "checkout_start", "title": "Открыли оплату", "count": await installs_with("checkout_start")},
        {"step": "paid", "title": "Оплатили (по платежам магазина)", "count": paid_users},
    ]
    screens = (await db.execute(select(AppEvent.screen, func.count(AppEvent.id), func.count(distinct(AppEvent.install_hash)))
                                .where(*scope, AppEvent.event == "screen").group_by(AppEvent.screen)
                                .order_by(func.count(AppEvent.id).desc()).limit(30))).all()
    checkout_installs = select(distinct(AppEvent.install_hash)).where(*scope, AppEvent.event == "checkout_start")
    screen_rows = []
    for screen, views, installs in screens:
        converted = int(await db.scalar(select(func.count(distinct(AppEvent.install_hash))).where(
            *scope, AppEvent.event == "screen", AppEvent.screen == screen, AppEvent.install_hash.in_(checkout_installs))) or 0)
        screen_rows.append({"screen": screen, "views": int(views), "installs": int(installs),
                            "to_checkout": round(converted * 100 / installs, 1) if installs else 0.0})
    by_platform = dict((await db.execute(select(AppEvent.platform, func.count(distinct(AppEvent.install_hash)))
                                         .where(AppEvent.created_at >= since).group_by(AppEvent.platform))).all())
    day = func.date(AppEvent.created_at)
    daily = [{"day": str(d), "installs": int(i), "active": int(a)} for d, i, a in (await db.execute(
        select(day, func.count(distinct(AppEvent.install_hash)).filter(AppEvent.event == "install"),
               func.count(distinct(AppEvent.install_hash))).where(*scope).group_by(day).order_by(day))).all()]
    versions = (await db.execute(select(AppEvent.platform, AppEvent.app_version, func.count(distinct(AppEvent.install_hash)))
                                 .where(*scope).group_by(AppEvent.platform, AppEvent.app_version)
                                 .order_by(func.count(distinct(AppEvent.install_hash)).desc()).limit(10))).all()
    return {"days": days, "platform": platform, "enabled": await analytics_enabled(db), "active_installs": active,
            "events": {k: int(v) for k, v in counts.items()}, "funnel": funnel, "screens": screen_rows,
            "platforms": {k: int(v) for k, v in by_platform.items()}, "daily": daily,
            "versions": [{"platform": p, "version": v or "—", "installs": int(n)} for p, v, n in versions]}


@router.get("/api/admin/app-analytics")
async def admin_analytics(days: int = Query(default=30, ge=1, le=RETENTION_DAYS), platform: str = Query(default="", pattern=r"^(|android|ios)$"),
                          db: AsyncSession = Depends(get_db), admin=Depends(require_permission("analytics.read"))):
    return await summary(db, days, platform)


async def cleanup(db: AsyncSession, now: datetime | None = None) -> int:
    from sqlalchemy import delete

    now = now or datetime.utcnow()
    result = await db.execute(delete(AppEvent).where(AppEvent.created_at < now - timedelta(days=RETENTION_DAYS)))
    await db.commit()
    return int(result.rowcount or 0)
