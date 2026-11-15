"""Payment antifraud rules (v28.49) on top of the base risk score (``payment_platform_api._risk_score``).

«Фрод → Правила платежей». Each rule adds points; the sum is compared with ``PAYMENT_RISK_REVIEW_SCORE`` (review: the
payment goes on, the operator is told) and ``PAYMENT_RISK_BLOCK_SCORE`` (the payment is refused). Rules:

* **card testing** — ``failed_24h`` or more failed / cancelled payments of the customer in a day;
* **new account, big amount** — the account is younger than ``new_account_hours`` and pays ``new_account_amount`` or more;
* **many accounts from one address** — ``accounts_per_ip`` or more customers started payments from one address in a day
  (counted in Redis, no addresses are stored in the database);
* **chargebacks** — the customer already has a chargeback;
* **blocklist** — an address, e-mail, Telegram id or customer id from the list: refused at once.

Every check also covers wallet top-ups. A refused attempt is kept as a fraud signal (``payment_blocked``) and the operator
gets a Telegram card for refusals and reviews, at most once an hour per customer.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import require_permission

logger = logging.getLogger("vpnshop.payment_fraud")
router = APIRouter()
CONFIG_KEY = "fraud.payments"
DEFAULT = {"enabled": True, "failed_24h": 5, "failed_points": 35, "new_account_hours": 2, "new_account_amount": 3000,
           "new_account_points": 25, "accounts_per_ip": 4, "accounts_points": 40, "chargeback_points": 60, "alert": True,
           "block_ips": [], "block_emails": [], "block_telegram_ids": [], "block_user_ids": []}
FAILED = ("failed", "canceled", "cancelled", "creation_unknown")


class RulesIn(BaseModel):
    enabled: bool = True
    failed_24h: int = Field(5, ge=1, le=100)
    failed_points: int = Field(35, ge=0, le=100)
    new_account_hours: int = Field(2, ge=0, le=720)
    new_account_amount: int = Field(3000, ge=0)
    new_account_points: int = Field(25, ge=0, le=100)
    accounts_per_ip: int = Field(4, ge=2, le=1000)
    accounts_points: int = Field(40, ge=0, le=100)
    chargeback_points: int = Field(60, ge=0, le=100)
    alert: bool = True
    block_ips: list[str] = Field(default_factory=list, max_length=1000)
    block_emails: list[str] = Field(default_factory=list, max_length=1000)
    block_telegram_ids: list[int] = Field(default_factory=list, max_length=1000)
    block_user_ids: list[int] = Field(default_factory=list, max_length=1000)


async def load(db: AsyncSession) -> dict:
    from .node_health import _load
    return await _load(db, CONFIG_KEY, DEFAULT)


async def _ip_accounts(ip: str, user_id: int) -> int:
    """Distinct customers who started a payment from ``ip`` in the last day (a Redis set with a one-day life)."""
    from . import main as shop
    redis = shop.redis_client
    if redis is None or not ip:
        return 0
    key = f"fraud:ip-accounts:{ip}"
    try:
        await redis.sadd(key, str(user_id))
        await redis.expire(key, 86400)
        return int(await redis.scard(key))
    except Exception as exc:  # noqa: BLE001 — no Redis, no rule
        logger.debug("ip accounts: %s", exc)
        return 0


async def extra(db: AsyncSession, user, amount: Decimal, ip: str | None, now: datetime | None = None) -> tuple[int, dict]:
    """Points and signals of the configured rules; 100 for the blocklist."""
    from .models import Payment, PaymentChargeback
    cfg = await load(db)
    if not cfg.get("enabled"):
        return 0, {}
    now = now or datetime.utcnow()
    score, signals = 0, {}
    lowered = {str(x).strip().lower() for x in cfg.get("block_emails") or []}
    if (ip and ip in set(cfg.get("block_ips") or [])) or (user.email and user.email.lower() in lowered) \
            or (user.telegram_id and int(user.telegram_id) in set(cfg.get("block_telegram_ids") or [])) or user.id in set(cfg.get("block_user_ids") or []):
        return 100, {"blocklist": True}
    since = now - timedelta(hours=24)
    failed = int(await db.scalar(select(func.count()).select_from(Payment).where(Payment.user_id == user.id, Payment.created_at >= since,
                                                                                Payment.status.in_(FAILED))) or 0)
    if failed >= int(cfg["failed_24h"]):
        score += int(cfg["failed_points"])
        signals["failed_24h"] = failed
    created = getattr(user, "created_at", None)
    if created and now - created < timedelta(hours=int(cfg["new_account_hours"])) and Decimal(str(amount)) >= Decimal(int(cfg["new_account_amount"])):
        score += int(cfg["new_account_points"])
        signals["new_account"] = {"hours": round((now - created).total_seconds() / 3600, 1), "amount": str(amount)}
    accounts = await _ip_accounts(ip or "", user.id)
    if accounts >= int(cfg["accounts_per_ip"]):
        score += int(cfg["accounts_points"])
        signals["accounts_per_ip"] = accounts
    chargebacks = int(await db.scalar(select(func.count()).select_from(PaymentChargeback).join(Payment, Payment.id == PaymentChargeback.payment_id)
                                      .where(Payment.user_id == user.id)) or 0)
    if chargebacks:
        score += int(cfg["chargeback_points"])
        signals["chargebacks"] = chargebacks
    return score, signals


async def record_refusal(db: AsyncSession, user, ip: str | None, score: int, signals: dict, amount) -> None:
    from .models import FraudSignal
    import json
    db.add(FraudSignal(user_id=user.id, ip=(ip or "")[:64] or None, kind="payment_blocked", score=score,
                       details=json.dumps({"amount": str(amount), "signals": signals}, ensure_ascii=False, default=str)[:4000]))
    await db.commit()


async def alert(db: AsyncSession, user, decision: str, score: int, signals: dict, amount) -> bool:
    cfg = await load(db)
    if not cfg.get("alert") or decision == "allow":
        return False
    from . import main as shop
    redis = shop.redis_client
    if redis is not None:
        try:
            if not await redis.set(f"fraud:alerted:{user.id}:{decision}", "1", nx=True, ex=3600):
                return False
        except Exception as exc:  # noqa: BLE001 — without Redis every refusal is reported
            logger.debug("alert throttle: %s", exc)
    from .ops_alerts import send
    what = "отклонён" if decision == "block" else "на проверке"
    reasons = ", ".join(f"{k}: {v}" for k, v in signals.items()) or "—"
    await send(f"🛡 <b>Платёж {what}</b>\n<blockquote>Клиент #{user.id}, сумма {amount}, риск {score}. Признаки: {reasons}</blockquote>")
    return True


@router.get("/api/admin/fraud/payment-rules")
async def get_rules(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("read"))):
    return await load(db)


@router.put("/api/admin/fraud/payment-rules")
async def put_rules(body: RulesIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("security.manage"))):
    from . import main as shop
    from .node_health import _save
    data = body.model_dump()
    data["block_ips"] = sorted({x.strip() for x in data["block_ips"] if x.strip()})
    data["block_emails"] = sorted({x.strip().lower() for x in data["block_emails"] if x.strip()})
    await _save(db, CONFIG_KEY, data)
    await shop.audit(db, "fraud.payment_rules.updated", admin.email, None, {k: v for k, v in data.items() if not k.startswith("block_")})
    await db.commit()
    return data


@router.get("/api/admin/fraud/payment-reviews")
async def reviews(days: int = 7, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("read"))):
    """Payments that went to review and attempts that were refused in the last days."""
    from .models import FraudSignal, Payment, PaymentRiskAssessment
    since = datetime.utcnow() - timedelta(days=min(max(days, 1), 90))
    flagged = (await db.execute(select(PaymentRiskAssessment, Payment).join(Payment, Payment.id == PaymentRiskAssessment.payment_id)
                                .where(PaymentRiskAssessment.created_at >= since, PaymentRiskAssessment.decision != "allow")
                                .order_by(PaymentRiskAssessment.id.desc()).limit(200))).all()
    blocked = (await db.execute(select(FraudSignal).where(FraudSignal.kind == "payment_blocked", FraudSignal.created_at >= since)
                                .order_by(FraudSignal.id.desc()).limit(200))).scalars().all()
    return {"reviews": [{"payment_id": p.id, "user_id": p.user_id, "amount": str(p.amount), "status": p.status, "provider": p.provider,
                         "score": a.score, "signals": a.signals, "at": a.created_at.isoformat()} for a, p in flagged],
            "blocked": [{"user_id": s.user_id, "score": s.score, "details": s.details, "at": s.created_at.isoformat()} for s in blocked]}
