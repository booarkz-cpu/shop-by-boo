"""v28.73 «Журнал уведомлений касс»: what the gateways sent and what the shop did with it.

Two sources, one list:

* **accepted** notifications — ``payment_provider_events`` (claimed once per provider event: processing, processed,
  retry with the error). They already make repeated and late notifications idempotent; here they become visible.
* **refused** notifications — every ``/api/webhooks/<gateway>`` answer with an error status (bad signature, amount or
  order mismatch, the gateway could not confirm the payment, unknown gateway). Before v28.73 these left no trace in
  the shop. A middleware keeps the last ``KEEP`` of them in Redis (``payments:webhook_refused``), without the body or
  headers — a refused request may carry anything, and the journal must not become a store of it.

Admin: «Кассы → Журнал уведомлений» and the mobile card «Уведомления касс»; ``GET /api/admin/payments/events``.
"""
from __future__ import annotations

import json
import logging
from collections import deque
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import require_permission

logger = logging.getLogger("vpnshop.payment_journal")
router = APIRouter()
KEY = "payments:webhook_refused"
KEEP = 300
_local: deque = deque(maxlen=KEEP)  # without Redis (tests, a single worker): the same list in memory
REASONS = {400: "неверный запрос", 401: "нет подписи", 403: "подпись, сумма или заказ не совпали", 404: "касса или заказ не найдены",
           409: "конфликт заказа", 422: "неверный формат", 429: "слишком часто", 503: "касса не подтвердила оплату"}
# Not gateways: the panel's own events and the generic recovery path have their own journals.
SKIP = {"remnawave"}


def gateway_of(path: str) -> str | None:
    if not path.startswith("/api/webhooks/"):
        return None
    name = path[len("/api/webhooks/"):].strip("/").split("/", 1)[0][:32]
    return name if name and name not in SKIP else None


async def remember(provider: str, status: int, at: datetime | None = None) -> None:
    entry = {"at": (at or datetime.utcnow()).isoformat(timespec="seconds"), "provider": provider, "status": int(status),
             "reason": REASONS.get(int(status), "ошибка обработки" if status >= 500 else "отклонено")}
    from . import main as shop
    redis = getattr(shop, "redis_client", None)
    if redis is not None:
        try:
            await redis.lpush(KEY, json.dumps(entry, ensure_ascii=False))
            await redis.ltrim(KEY, 0, KEEP - 1)
            return
        except Exception as exc:  # noqa: BLE001 — the journal never breaks a webhook answer
            logger.debug("refused webhook not kept in Redis: %s", exc)
    _local.appendleft(entry)


async def refused(limit: int = 100) -> list[dict]:
    from . import main as shop
    redis = getattr(shop, "redis_client", None)
    if redis is not None:
        try:
            rows = await redis.lrange(KEY, 0, max(0, limit - 1))
            return [json.loads(r) for r in rows]
        except Exception as exc:  # noqa: BLE001
            logger.debug("refused webhooks unavailable: %s", exc)
    return list(_local)[:limit]


def install(app) -> None:
    """Record refused gateway notifications (called once from main.py when the app is built)."""
    @app.middleware("http")
    async def webhook_journal(request: Request, call_next):
        provider = gateway_of(request.url.path)
        response = await call_next(request)
        if provider and request.method == "POST" and response.status_code >= 400:
            await remember(provider, response.status_code)
        return response


async def journal(db: AsyncSession, provider: str = "", days: int = 7, limit: int = 100) -> dict:
    from .models import Payment, PaymentProviderEvent
    since = datetime.utcnow() - timedelta(days=days)
    q = select(PaymentProviderEvent, Payment.order_id, Payment.amount, Payment.currency, Payment.status).outerjoin(
        Payment, Payment.id == PaymentProviderEvent.payment_id).where(PaymentProviderEvent.received_at >= since)
    if provider:
        q = q.where(PaymentProviderEvent.provider == provider)
    rows = (await db.execute(q.order_by(PaymentProviderEvent.id.desc()).limit(limit))).all()
    counts = dict((await db.execute(select(PaymentProviderEvent.status, func.count()).where(PaymentProviderEvent.received_at >= since)
                                    .group_by(PaymentProviderEvent.status))).all())
    bad = [r for r in await refused(KEEP) if (not provider or r["provider"] == provider) and r["at"] >= since.isoformat()]
    return {"days": days,
            "accepted": [{"provider": e.provider, "event_id": e.event_id, "payment_id": e.payment_id, "order_id": order, "status": e.status,
                          "attempts": e.attempts, "error": (e.last_error or "")[:300] or None, "received_at": e.received_at.isoformat(),
                          "processed_at": e.processed_at.isoformat() if e.processed_at else None,
                          "amount": str(amount) if amount is not None else None, "currency": currency, "payment_status": pstatus}
                         for e, order, amount, currency, pstatus in rows],
            "refused": bad[:limit],
            "summary": {"processed": int(counts.get("processed", 0)), "retry": int(counts.get("retry", 0)),
                        "processing": int(counts.get("processing", 0)), "refused": len(bad)}}


@router.get("/api/admin/payments/events")
async def payment_events(provider: str = "", days: int = 7, limit: int = 100, db: AsyncSession = Depends(get_db),
                         admin=Depends(require_permission("payments.read"))):
    return await journal(db, provider[:32], max(1, min(days, 90)), max(1, min(limit, 300)))
