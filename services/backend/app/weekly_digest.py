"""v28.52 «Еженедельная сводка»: one Telegram message to the owner on Monday morning.

Revenue of the week against the week before, new paying customers, customers who left, live subscriptions,
payment gateways that do not take payments, nodes offline, support ratings and NPS, frozen subscriptions and declined
renewals — and one recommendation picked by simple rules (the most urgent problem first).

Off by default (``digest.config``: weekday and Moscow time). Admin: «Аналитика → Еженедельная сводка» (preview,
«Отправить сейчас») and the mobile card.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import require_permission

logger = logging.getLogger("vpnshop.digest")
router = APIRouter()
CONFIG_KEY = "digest.config"
DEFAULT = {"enabled": False, "weekday": 0, "time": "09:00", "last_day": None}
DAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
PAID = ("paid", "fulfilled")


class DigestIn(BaseModel):
    enabled: bool = False
    weekday: int = Field(0, ge=0, le=6)
    time: str = Field("09:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


async def load(db: AsyncSession) -> dict:
    from .node_health import _load
    return {**DEFAULT, **(await _load(db, CONFIG_KEY, DEFAULT) or {})}


async def _revenue(db, start, end) -> Decimal:
    from .models import Payment
    value = await db.scalar(select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.status.in_(PAID), Payment.provider != "wallet",
                                                                                       Payment.paid_at >= start, Payment.paid_at < end))
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


async def collect(db: AsyncSession, now: datetime | None = None, nodes=None) -> dict:
    from .models import Payment, PaymentProviderHealth, Subscription
    now = now or datetime.utcnow()
    week, before = now - timedelta(days=7), now - timedelta(days=14)
    revenue, previous = await _revenue(db, week, now), await _revenue(db, before, week)
    first = select(Payment.user_id).where(Payment.status.in_(PAID), Payment.purpose == "subscription").group_by(Payment.user_id) \
        .having(func.min(Payment.paid_at) >= week)
    new = int(await db.scalar(select(func.count()).select_from(first.subquery())) or 0)
    left = int(await db.scalar(select(func.count(func.distinct(Subscription.user_id))).where(
        Subscription.lifecycle_status.in_(("expired", "cancelled")), Subscription.expires_at >= week, Subscription.expires_at < now)) or 0)
    live = int(await db.scalar(select(func.count()).select_from(Subscription).where(
        Subscription.lifecycle_status.in_(("active", "grace", "cancel_scheduled")), Subscription.expires_at > now)) or 0)
    frozen = int(await db.scalar(select(func.count()).select_from(Subscription).where(Subscription.lifecycle_status == "frozen")) or 0)
    gateways = [r.provider for r in (await db.execute(select(PaymentProviderHealth).where(PaymentProviderHealth.enabled.is_(True),
                                                                                         PaymentProviderHealth.circuit_open_until > now))).scalars()]
    if nodes is None:
        try:
            from .node_health import node_snapshot
            nodes = (await node_snapshot()).get("nodes") or []
        except Exception:  # noqa: BLE001 — the digest goes out without the node line
            nodes = []
    offline = [str(n.get("name") or n.get("uuid")) for n in nodes if n.get("status") == "offline"]
    from .dunning import stats as dunning_stats
    from .feedback import report as feedback_report
    fb = await feedback_report(db, 90, now)
    csat_week = await feedback_report(db, 7, now)
    dn = await dunning_stats(db)
    change = None if previous == 0 else round(float((revenue - previous) * 100 / previous))
    return {"revenue": str(revenue), "previous": str(previous), "change": change, "new": new, "left": left, "live": live, "frozen": frozen,
            "gateways_down": gateways, "nodes_offline": offline, "csat": csat_week["csat"]["average"], "csat_count": csat_week["csat"]["count"],
            "nps": fb["nps"]["score"], "past_due": dn["past_due"]}


async def advice(db: AsyncSession, d: dict) -> str:
    """The one thing worth doing this week (the most urgent first)."""
    if d["gateways_down"]:
        return f"Касса {', '.join(d['gateways_down'])} сейчас не принимает оплаты — проверьте ключи в разделе «Кассы»."
    if d["nodes_offline"]:
        return f"Не в сети: {', '.join(d['nodes_offline'][:3])} — перезапустите ноду в разделе «Ноды» или уберите её из выдачи."
    if d["change"] is not None and d["change"] <= -20:
        return f"Выручка упала на {abs(d['change'])}% — проверьте оплату на сайте и в боте и подумайте об акции на выходные."
    if d["left"] > d["new"]:
        from .dunning import load as dunning_load
        from .subscription_freeze import load as freeze_load
        if not (await freeze_load(db))["enabled"] or not (await dunning_load(db))["enabled"]:
            return "Ушло больше клиентов, чем пришло — включите заморозку подписки и повторные попытки автопродления («Тарифы»)."
        return "Ушло больше клиентов, чем пришло — предложите скидку тем, кто собирается уйти («Аналитика → Отток»)."
    if d["csat"] is not None and d["csat"] < 4:
        return "Средняя оценка поддержки ниже 4 — посмотрите комментарии клиентов («Поддержка → Оценки и NPS»)."
    if d["past_due"]:
        return f"У {d['past_due']} клиентов не прошло автопродление — включите сообщения о повторных попытках, если они выключены."
    return "Всё стабильно — хорошее время для реферального конкурса или акции для новых клиентов."


async def render(db: AsyncSession, now: datetime | None = None, nodes=None) -> str:
    d = await collect(db, now, nodes)
    change = "" if d["change"] is None else f" ({'+' if d['change'] >= 0 else ''}{d['change']}% к прошлой неделе)"
    lines = ["Сводка за неделю",
             f"Выручка: {d['revenue']} ₽{change}",
             f"Новых клиентов: {d['new']}",
             f"Ушло клиентов: {d['left']}",
             f"Действующих подписок: {d['live']}" + (f", заморожено {d['frozen']}" if d["frozen"] else ""),
             f"Кассы: {'все работают' if not d['gateways_down'] else 'не работают ' + ', '.join(d['gateways_down'])}",
             f"Ноды: {'все в сети' if not d['nodes_offline'] else 'не в сети ' + ', '.join(d['nodes_offline'][:5])}"]
    if d["csat_count"]:
        lines.append(f"Оценка поддержки: {d['csat']} из 5 ({d['csat_count']} оценок)")
    if d["nps"] is not None:
        lines.append(f"NPS за 90 дней: {d['nps']}")
    if d["past_due"]:
        lines.append(f"Не прошло автопродление: {d['past_due']}")
    lines += ["", "Совет: " + await advice(db, d)]
    return "\n".join(lines)


async def tick(db: AsyncSession, now: datetime | None = None, send=None, nodes=None) -> bool:
    from .node_health import MSK, _due, _save
    cfg = await load(db)
    now = now or datetime.now(timezone.utc)
    if not cfg["enabled"] or now.astimezone(MSK).weekday() != int(cfg["weekday"]) or not _due(now, cfg["time"], cfg.get("last_day")):
        return False
    text = await render(db, now.astimezone(timezone.utc).replace(tzinfo=None), nodes)
    if send is None:
        from .ops_alerts import send
    await send(text)
    await _save(db, CONFIG_KEY, {**cfg, "last_day": now.astimezone(MSK).date().isoformat()})
    await db.commit()
    return True


async def _loop():
    from .db import SessionLocal
    from .main import redis_client
    while True:
        await asyncio.sleep(900)
        try:
            if redis_client is not None and not await redis_client.set("lock:digest", "1", nx=True, ex=880):
                continue
            async with SessionLocal() as db:
                await tick(db)
        except Exception as exc:  # noqa: BLE001
            logger.warning("weekly digest failed: %s", exc)


def _start():
    from .main import _track_task
    _track_task(_loop())


router.add_event_handler("startup", _start)


@router.get("/api/admin/digest")
async def get_digest(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("analytics.read"))):
    return {"config": await load(db), "preview": await render(db), "weekdays": DAYS}


@router.put("/api/admin/digest")
async def put_digest(payload: DigestIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("analytics.read"))):
    from .main import audit
    from .node_health import _save
    cfg = await load(db)
    await _save(db, CONFIG_KEY, {**cfg, **payload.model_dump()})
    await audit(db, "digest.config", admin.email, None, payload.model_dump())
    await db.commit()
    return await load(db)


@router.post("/api/admin/digest/send")
async def send_digest(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("analytics.read"))):
    from .ops_alerts import send
    ok = await send(await render(db))
    return {"ok": bool(ok)}
