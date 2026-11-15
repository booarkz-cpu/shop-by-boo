"""Push campaigns («Приложения: push-кампании»): now or at a Moscow time, with an A/B test of two texts.

A campaign goes to a segment (app_growth.SEGMENTS) computed when it is sent. Each recipient gets
one in-app notification that the push worker (push.py) delivers to every app with push switched on.

* **Later.** ``send_at`` is a Moscow wall-clock time («2026-11-01T10:00»). The campaign waits as
  «scheduled» and ``campaign_scheduler`` sends it within a minute of that time; until then it can be
  cancelled. The segment is computed at sending, so customers who renewed meanwhile are not reached.
* **A/B.** With a second text, ``b_percent`` of the recipients (chosen by a stable hash of campaign
  and user) get variant B, the rest variant A. Who got which is kept in push_campaign_recipients.
* **Results.** For each variant: recipients, customers who paid within ``conversion_days`` after the
  sending (the shop's own payments, paid or fulfilled), conversion, revenue and whether the
  difference is statistically meaningful (two-proportion z-test, p < 0.05, at least 30 per variant).
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import math
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .models import Notification, Payment, PushCampaign, PushCampaignRecipient
from .security import require_permission

logger = logging.getLogger(__name__)
router = APIRouter()
MSK = ZoneInfo("Europe/Moscow")
REPEAT_GUARD_MINUTES = 10  # a second click on «Отправить» does not message everyone twice
MAX_AHEAD_DAYS = 60
PAID = ("paid", "fulfilled")
SEGMENT_PATTERN = r"^(all|app_users|expiring|expired|no_subscription|inactive)$"

__all__ = ["router", "CampaignIn", "CampaignPreviewIn", "REPEAT_GUARD_MINUTES", "send_campaign", "deliver",
           "send_due", "campaign_results", "variant_of", "moscow_to_utc", "campaign_scheduler"]


class CampaignIn(BaseModel):
    segment: str = Field(pattern=SEGMENT_PATTERN)
    days: int = Field(default=3, ge=1, le=90)
    title: str = Field(default="", max_length=120)
    body: str = Field(default="", max_length=1000)
    title_b: str = Field(default="", max_length=120)
    body_b: str = Field(default="", max_length=1000)
    b_percent: int = Field(default=50, ge=1, le=90)
    send_at: str = Field(default="", pattern=r"^(|\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2})$")
    conversion_days: int = Field(default=7, ge=1, le=30)

    @model_validator(mode="after")
    def _both_or_neither(self):
        if bool(self.title_b.strip()) != bool(self.body_b.strip()):
            raise ValueError("Для варианта B нужны и заголовок, и текст")
        return self


class CampaignPreviewIn(BaseModel):
    segment: str = Field(pattern=SEGMENT_PATTERN)
    days: int = Field(default=3, ge=1, le=90)


def moscow_to_utc(value: str) -> datetime:
    local = datetime.fromisoformat(value.replace(" ", "T")).replace(tzinfo=MSK)
    return local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)


def utc_to_moscow(value: datetime | None) -> str | None:
    return value.replace(tzinfo=ZoneInfo("UTC")).astimezone(MSK).strftime("%Y-%m-%dT%H:%M") if value else None


def variant_of(campaign_id: int, user_id: int, b_percent: int) -> str:
    """Stable split: the same customer always lands in the same variant of a campaign."""
    if b_percent <= 0:
        return "a"
    bucket = int(hashlib.sha256(f"campaign:{campaign_id}:{user_id}".encode()).hexdigest()[:8], 16) % 100
    return "b" if bucket < b_percent else "a"


def _clean(text: str) -> str:
    return " ".join(text.split())


async def send_campaign(db: AsyncSession, payload: CampaignIn, actor: str, now: datetime | None = None) -> PushCampaign:
    """Create a campaign: send it now, or keep it «scheduled» for its Moscow time."""
    from .app_growth import _with_push, segment_users

    now = now or datetime.utcnow()
    title, body = _clean(payload.title), payload.body.strip()
    if not title or not body:
        raise HTTPException(422, "Заголовок и текст обязательны")
    title_b, body_b = _clean(payload.title_b), payload.body_b.strip()
    if title_b and (title_b, body_b) == (title, body):
        raise HTTPException(422, "Вариант B совпадает с вариантом A")
    scheduled_at = None
    if payload.send_at:
        try:
            scheduled_at = moscow_to_utc(payload.send_at)
        except ValueError:
            raise HTTPException(422, "Неверная дата отправки")
        if scheduled_at > now + timedelta(days=MAX_AHEAD_DAYS):
            raise HTTPException(422, f"Запланировать можно не дальше чем на {MAX_AHEAD_DAYS} дней")
        if scheduled_at <= now + timedelta(minutes=1):
            scheduled_at = None  # «now» or a minute that has passed: send right away
    twin = (await db.execute(select(PushCampaign.id).where(
        PushCampaign.title == title, PushCampaign.body == body, PushCampaign.segment == payload.segment,
        PushCampaign.status.in_(("sent", "sending", "scheduled")),
        PushCampaign.created_at >= now - timedelta(minutes=REPEAT_GUARD_MINUTES)).limit(1))).scalar_one_or_none()
    if twin:
        raise HTTPException(409, "Такая рассылка уже отправлена несколько минут назад")
    campaign = PushCampaign(title=title, body=body, segment=payload.segment, days=payload.days, created_by=actor[:320],
                            created_at=now, title_b=title_b or None, body_b=body_b or None,
                            b_percent=payload.b_percent if title_b else 0, conversion_days=payload.conversion_days,
                            scheduled_at=scheduled_at, status="scheduled" if scheduled_at else "sending")
    db.add(campaign)
    await db.flush()
    if scheduled_at:
        users = await segment_users(db, payload.segment, payload.days, now)
        campaign.recipients, campaign.with_push = len(users), await _with_push(db, users)  # an estimate until sending
        return campaign
    await deliver(db, campaign, now)
    return campaign


async def deliver(db: AsyncSession, campaign: PushCampaign, now: datetime | None = None) -> PushCampaign:
    from .app_growth import _with_push, segment_users

    now = now or datetime.utcnow()
    users = await segment_users(db, campaign.segment, campaign.days, now)
    key = f"campaign:{campaign.id}"
    for user_id in users:
        variant = variant_of(campaign.id, user_id, campaign.b_percent) if campaign.title_b else "a"
        title, body = (campaign.title_b, campaign.body_b) if variant == "b" else (campaign.title, campaign.body)
        db.add(PushCampaignRecipient(campaign_id=campaign.id, user_id=user_id, variant=variant, created_at=now))
        # push_fanout_at stays empty: the push worker fans it out to the devices of the user.
        db.add(Notification(user_id=user_id, channel="in_app", kind="campaign", title=title, body=body,
                            dedupe_key=key, status="sent", sent_at=now, created_at=now))
    campaign.recipients, campaign.with_push = len(users), await _with_push(db, users)
    campaign.status, campaign.sent_at = "sent", now
    return campaign


async def send_due(db: AsyncSession, now: datetime | None = None) -> int:
    """Send every scheduled campaign whose time has come; each exactly once, across workers."""
    now = now or datetime.utcnow()
    due = (await db.execute(select(PushCampaign).where(PushCampaign.status == "scheduled", PushCampaign.scheduled_at <= now)
                            .order_by(PushCampaign.scheduled_at).limit(20).with_for_update(skip_locked=True))).scalars().all()
    for campaign in due:
        await deliver(db, campaign, now)
    await db.commit()
    return len(due)


async def campaign_scheduler():
    from .db import engine

    while True:
        try:
            async with AsyncSession(engine, expire_on_commit=False) as db:
                await send_due(db)
        except Exception as exc:
            logger.warning("Scheduled push campaigns unavailable; retrying: %s", type(exc).__name__)
        await asyncio.sleep(60)


def _p_value(paid_a: int, n_a: int, paid_b: int, n_b: int) -> float | None:
    if min(n_a, n_b) == 0:
        return None
    pooled = (paid_a + paid_b) / (n_a + n_b)
    spread = math.sqrt(pooled * (1 - pooled) * (1 / n_a + 1 / n_b))
    if spread == 0:
        return 1.0
    z = abs(paid_a / n_a - paid_b / n_b) / spread
    return math.erfc(z / math.sqrt(2))


async def campaign_results(db: AsyncSession, campaign: PushCampaign, now: datetime | None = None) -> dict:
    now = now or datetime.utcnow()
    if not campaign.sent_at:
        return {"variants": [], "winner": None, "complete": False}
    until = campaign.sent_at + timedelta(days=campaign.conversion_days)
    variants = []
    for variant in (("a", "b") if campaign.title_b else ("a",)):
        recipients = select(PushCampaignRecipient.user_id).where(PushCampaignRecipient.campaign_id == campaign.id,
                                                                 PushCampaignRecipient.variant == variant)
        n = int(await db.scalar(select(func.count()).select_from(recipients.subquery())) or 0)
        paid_filter = (Payment.user_id.in_(recipients), Payment.status.in_(PAID), Payment.paid_at.is_not(None),
                       Payment.paid_at >= campaign.sent_at, Payment.paid_at < until)
        paid = int(await db.scalar(select(func.count(distinct(Payment.user_id))).where(*paid_filter)) or 0)
        revenue = await db.scalar(select(func.coalesce(func.sum(Payment.amount), 0)).where(*paid_filter)) or 0
        variants.append({"variant": variant, "title": campaign.title_b if variant == "b" else campaign.title,
                         "recipients": n, "paid": paid, "conversion": round(paid * 100 / n, 2) if n else 0.0,
                         "revenue": str(Decimal(str(revenue)).quantize(Decimal("0.01")))})
    winner, p_value = None, None
    if len(variants) == 2:
        a, b = variants
        p_value = _p_value(a["paid"], a["recipients"], b["paid"], b["recipients"])
        if p_value is not None and p_value < 0.05 and min(a["recipients"], b["recipients"]) >= 30 and a["paid"] != b["paid"]:
            winner = a["variant"] if a["conversion"] > b["conversion"] else b["variant"]
    return {"variants": variants, "winner": winner, "p_value": round(p_value, 4) if p_value is not None else None,
            "window_days": campaign.conversion_days, "complete": now >= until}


def _campaign(row: PushCampaign) -> dict:
    return {"id": row.id, "title": row.title, "body": row.body, "title_b": row.title_b, "body_b": row.body_b,
            "b_percent": row.b_percent, "segment": row.segment, "days": row.days, "status": row.status,
            "recipients": row.recipients, "with_push": row.with_push, "created_by": row.created_by,
            "created_at": row.created_at, "sent_at": row.sent_at, "scheduled_at": row.scheduled_at,
            "scheduled_msk": utc_to_moscow(row.scheduled_at), "conversion_days": row.conversion_days}


@router.get("/api/admin/push-campaigns")
async def list_campaigns(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("marketing.read"))):
    from .app_growth import SEGMENTS
    from .push import provider_ready

    rows = (await db.execute(select(PushCampaign).order_by(PushCampaign.id.desc()).limit(50))).scalars().all()
    items = []
    for row in rows:
        item = _campaign(row)
        if row.title_b and row.sent_at:
            item["results"] = await campaign_results(db, row)
        items.append(item)
    return {"segments": SEGMENTS, "push_ready": {p: provider_ready(p) for p in ("fcm", "apns")}, "items": items,
            "now_msk": utc_to_moscow(datetime.utcnow())}


@router.post("/api/admin/push-campaigns/preview")
async def preview_campaign(payload: CampaignPreviewIn, db: AsyncSession = Depends(get_db),
                           admin=Depends(require_permission("marketing.read"))):
    from .app_growth import _with_push, segment_users

    users = await segment_users(db, payload.segment, payload.days)
    return {"recipients": len(users), "with_push": await _with_push(db, users)}


@router.post("/api/admin/push-campaigns")
async def create_campaign(payload: CampaignIn, db: AsyncSession = Depends(get_db),
                          admin=Depends(require_permission("manage_broadcasts"))):
    from .main import audit

    row = await send_campaign(db, payload, admin.email)
    await audit(db, "push_campaign.scheduled" if row.status == "scheduled" else "push_campaign.sent", admin.email, str(row.id),
                {"segment": row.segment, "days": row.days, "recipients": row.recipients, "with_push": row.with_push,
                 "ab": bool(row.title_b), "b_percent": row.b_percent, "scheduled_at": row.scheduled_at})
    await db.commit()
    return _campaign(row)


@router.get("/api/admin/push-campaigns/{campaign_id}/results")
async def results(campaign_id: int, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("marketing.read"))):
    row = await db.get(PushCampaign, campaign_id)
    if not row:
        raise HTTPException(404, "Кампания не найдена")
    return {"campaign": _campaign(row), **await campaign_results(db, row)}


@router.post("/api/admin/push-campaigns/{campaign_id}/cancel")
async def cancel(campaign_id: int, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("manage_broadcasts"))):
    from .main import audit

    row = (await db.execute(select(PushCampaign).where(PushCampaign.id == campaign_id).with_for_update())).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Кампания не найдена")
    if row.status != "scheduled":
        raise HTTPException(409, "Отменить можно только запланированную кампанию")
    row.status = "cancelled"
    await audit(db, "push_campaign.cancelled", admin.email, str(row.id), {"scheduled_at": row.scheduled_at})
    await db.commit()
    return _campaign(row)
