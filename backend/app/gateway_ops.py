"""«Платёжные агенты → Здоровье касс» (v28.45): the gateway table, a regular probe of every gateway, the report of
notifications that never came, and the automatic choice of the best-converting gateway.

* **Probe.** Every ``probe_hours`` each configured extra gateway gets one cheap authenticated call (``probe()`` of its
  class: a «not found» for a made-up order means the keys work). After ``fail_threshold`` failures in a row the gateway
  is taken out of the queue for ``cooldown_hours`` (``PaymentProviderHealth.circuit_open_until``) and the operator gets
  a Telegram card; when the probe passes again, a gateway the probe took out comes back and the operator is told.
* **Notifications that never came.** A paid order with no verified notification from its gateway was found by the
  recovery poll, not by the notification: the gateway's notification address or signature is wrong. Pending orders
  older than ``notify_minutes`` are counted too. Above ``missing_alert_share`` % (from 5 paid orders) the operator gets
  a card, at most once a day per gateway.
* **Best gateway first.** With ``auto_priority`` on, once a day the gateways with at least ``auto_min_orders`` orders in
  ``auto_days`` are reordered by conversion (ties: more orders first); the others keep their places after them. Every
  change goes to the audit log.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import require_permission

logger = logging.getLogger("vpnshop.gateway_ops")
router = APIRouter()
CONFIG_KEY = "gateways.ops"
STATE_KEY = "gateways.probe_state"
DEFAULT = {"probe_enabled": True, "probe_hours": 6, "fail_threshold": 2, "cooldown_hours": 6, "notify_minutes": 30,
           "missing_alert_share": 20, "auto_priority": False, "auto_days": 14, "auto_min_orders": 20}
PAID = ("paid", "fulfilled", "refunded", "refunded_pending_revoke")


class OpsIn(BaseModel):
    probe_enabled: bool = True
    probe_hours: int = Field(6, ge=1, le=72)
    fail_threshold: int = Field(2, ge=1, le=10)
    cooldown_hours: int = Field(6, ge=1, le=168)
    notify_minutes: int = Field(30, ge=5, le=1440)
    missing_alert_share: int = Field(20, ge=1, le=100)
    auto_priority: bool = False
    auto_days: int = Field(14, ge=1, le=90)
    auto_min_orders: int = Field(20, ge=5, le=10000)


async def _load(db, key, default):
    from .node_health import _load as load
    return await load(db, key, default)


async def _save(db, key, value):
    from .node_health import _save as save
    await save(db, key, value)


async def _alert(text: str) -> None:
    from .ops_alerts import send
    await send(text)


# ------------------------------------------------------------------ probe
async def probe_all(db: AsyncSession, now: datetime | None = None, alert=None) -> dict:
    """Probe every configured extra gateway once; take broken ones out of the queue and bring recovered ones back."""
    from .gateways import GATEWAYS
    from .models import PaymentProviderHealth
    now = now or datetime.utcnow()
    alert = alert or _alert
    cfg = {**DEFAULT, **(await _load(db, CONFIG_KEY, DEFAULT))}
    state = await _load(db, STATE_KEY, {})
    messages = []
    for name, g in GATEWAYS.items():
        if not g.configured():
            state.pop(name, None)
            continue
        started = datetime.utcnow()
        try:
            error = await g.cls().probe()
        except Exception as exc:  # noqa: BLE001 — a probe never breaks the job
            error = f"ошибка пробы: {type(exc).__name__}"
        ms = int((datetime.utcnow() - started).total_seconds() * 1000)
        item = state.get(name) or {}
        fails = (int(item.get("fails") or 0) + 1) if error else 0
        item.update({"ok": not error, "error": error or None, "at": now.isoformat(), "latency_ms": ms, "fails": fails})
        row = (await db.execute(select(PaymentProviderHealth).where(PaymentProviderHealth.provider == name))).scalar_one_or_none()
        if error and fails >= int(cfg["fail_threshold"]) and not item.get("taken_out"):
            if row is None:
                row = PaymentProviderHealth(provider=name, priority=900, enabled=True)
                db.add(row)
            row.circuit_open_until = now + timedelta(hours=int(cfg["cooldown_hours"]))
            row.last_error = f"probe: {error}"[:500]
            row.updated_at = now
            item["taken_out"] = True
            messages.append(f"🔴 <b>Касса {g.title} выведена из очереди</b>\n<blockquote>Проба: {error}. Проверьте ключи в «Настройках»; "
                            f"касса вернётся сама, когда проба пройдёт.</blockquote>")
        elif error and item.get("taken_out") and row is not None:
            row.circuit_open_until = now + timedelta(hours=int(cfg["cooldown_hours"]))  # still broken: keep it out
        elif not error and item.get("taken_out"):
            if row is not None and (row.last_error or "").startswith("probe:"):
                row.circuit_open_until = None
                row.last_error = None
                row.updated_at = now
            item["taken_out"] = False
            messages.append(f"🟢 <b>Касса {g.title} снова в очереди</b>\n<blockquote>Проба прошла за {ms} мс.</blockquote>")
        state[name] = item
    await _save(db, STATE_KEY, state)
    await db.commit()
    for text in messages:
        await alert(text)
    return state


# ------------------------------------------------------------------ notifications that never came
async def notifications_report(db: AsyncSession, days: int = 7, now: datetime | None = None, notify_minutes: int = 30) -> dict:
    from .models import Payment, PaymentProviderEvent
    from .payment_policy import PAYMENT_AGENTS
    now = now or datetime.utcnow()
    since = now - timedelta(days=days)
    rows = (await db.execute(select(Payment.id, Payment.provider, Payment.status, Payment.created_at)
                             .where(Payment.created_at >= since, Payment.provider.in_(PAYMENT_AGENTS)))).all()
    noticed = set((await db.execute(select(PaymentProviderEvent.payment_id)
                                    .where(PaymentProviderEvent.payment_id.is_not(None), PaymentProviderEvent.received_at >= since))).scalars().all())
    stale = now - timedelta(minutes=notify_minutes)
    out: dict[str, dict] = {}
    for pid, provider, status, created in rows:
        item = out.setdefault(provider, {"provider": provider, "paid": 0, "without_notification": 0, "stuck_pending": 0})
        if status in PAID:
            item["paid"] += 1
            if pid not in noticed:
                item["without_notification"] += 1
        elif status == "pending" and created and created < stale:
            item["stuck_pending"] += 1
    for item in out.values():
        item["missing_share"] = round(item["without_notification"] * 100 / item["paid"], 1) if item["paid"] else 0.0
    return {"days": days, "providers": sorted(out.values(), key=lambda x: (-x["missing_share"], x["provider"]))}


async def check_notifications(db: AsyncSession, now: datetime | None = None, alert=None) -> list[str]:
    now = now or datetime.utcnow()
    alert = alert or _alert
    cfg = {**DEFAULT, **(await _load(db, CONFIG_KEY, DEFAULT))}
    report = await notifications_report(db, 1, now, int(cfg["notify_minutes"]))
    state = await _load(db, STATE_KEY, {})
    sent = state.setdefault("_notify_alerts", {})
    flagged = []
    for item in report["providers"]:
        if item["paid"] >= 5 and item["missing_share"] >= int(cfg["missing_alert_share"]):
            last = sent.get(item["provider"])
            if last and now - datetime.fromisoformat(last) < timedelta(hours=23):
                continue
            sent[item["provider"]] = now.isoformat()
            flagged.append(item["provider"])
            await alert(f"🟠 <b>Касса {item['provider']}: не приходят уведомления</b>\n<blockquote>За сутки {item['without_notification']} из "
                        f"{item['paid']} оплат найдены сверкой, без уведомления. Проверьте адрес уведомлений и ключ подписи.</blockquote>")
    await _save(db, STATE_KEY, state)
    await db.commit()
    return flagged


# ------------------------------------------------------------------ best gateway first
async def auto_priority(db: AsyncSession, now: datetime | None = None, dry_run: bool = False, actor: str = "system") -> dict:
    """Reorder the queue by conversion among the gateways with enough orders; the rest keep their order after them."""
    from .models import PaymentProviderHealth
    from .payment_policy import PAYMENT_AGENTS
    from .provider_report import build_report
    cfg = {**DEFAULT, **(await _load(db, CONFIG_KEY, DEFAULT))}
    report = await build_report(db, int(cfg["auto_days"]), now)
    ranked = [x["provider"] for x in sorted(report["providers"], key=lambda x: (-x["conversion"], -x["orders"]))
              if x["orders"] >= int(cfg["auto_min_orders"]) and x["provider"] in PAYMENT_AGENTS]
    rows = (await db.execute(select(PaymentProviderHealth).order_by(PaymentProviderHealth.priority, PaymentProviderHealth.provider))).scalars().all()
    rows = [r for r in rows if r.provider in PAYMENT_AGENTS]
    current = [r.provider for r in rows]
    order = [p for p in ranked if p in current] + [p for p in current if p not in ranked]
    changed = order != current
    if changed and not dry_run:
        by_name = {r.provider: r for r in rows}
        for i, name in enumerate(order, 1):
            by_name[name].priority = i * 10
            by_name[name].updated_at = datetime.utcnow()
        from . import main as shop
        await shop.audit(db, "payment_provider.auto_priority", actor, ",".join(order), {"before": current, "ranked": ranked})
        await db.commit()
    return {"before": current, "after": order, "ranked": ranked, "changed": changed, "applied": changed and not dry_run}


# ------------------------------------------------------------------ admin
@router.get("/api/admin/gateways")
async def gateways_table(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("payments.read"))):
    from .gateways import GATEWAYS
    state = await _load(db, STATE_KEY, {})
    cfg = {**DEFAULT, **(await _load(db, CONFIG_KEY, DEFAULT))}
    rows = []
    for g in GATEWAYS.values():
        rows.append({"name": g.name, "title": g.title, "configured": g.configured(), "missing_keys": g.missing_keys(), "webhook": g.webhook,
                     "signature": g.signature, "recheck": g.recheck, "methods": sorted(g.methods), "refunds": g.refunds,
                     "recurring": g.recurring, "since": g.since, "probe": state.get(g.name)})
    return {"config": cfg, "gateways": rows}


@router.put("/api/admin/gateways/config")
async def put_config(body: OpsIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("ops.providers"))):
    await _save(db, CONFIG_KEY, body.model_dump())
    from . import main as shop
    await shop.audit(db, "gateways.ops.updated", admin.email, None, body.model_dump())
    await db.commit()
    return {"ok": True, "config": body.model_dump()}


@router.post("/api/admin/gateways/probe")
async def probe_now(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("ops.providers"))):
    return {"state": await probe_all(db)}


@router.get("/api/admin/gateways/notifications")
async def notifications(days: int = 7, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("payments.read"))):
    cfg = {**DEFAULT, **(await _load(db, CONFIG_KEY, DEFAULT))}
    return await notifications_report(db, min(max(days, 1), 90), notify_minutes=int(cfg["notify_minutes"]))


@router.post("/api/admin/gateways/auto-priority")
async def auto_priority_now(dry_run: bool = True, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("ops.providers"))):
    if not dry_run and not (await _load(db, CONFIG_KEY, DEFAULT)).get("auto_priority"):
        raise HTTPException(409, "Включите «Лучшая касса первой» в настройках здоровья касс")
    return await auto_priority(db, dry_run=dry_run, actor=admin.email)


# ------------------------------------------------------------------ background
async def _loop() -> None:
    from .db import SessionLocal
    from .main import redis_client
    hours_since_auto = 24
    while True:
        wait_min = 60
        try:
            async with SessionLocal() as db:
                cfg = {**DEFAULT, **(await _load(db, CONFIG_KEY, DEFAULT))}
                wait_min = int(cfg["probe_hours"]) * 60
                if redis_client is None or await redis_client.set("lock:gateway_ops", "1", nx=True, ex=wait_min * 60 - 30):
                    if cfg["probe_enabled"]:
                        await probe_all(db)
                    await check_notifications(db)
                    hours_since_auto += int(cfg["probe_hours"])
                    if cfg["auto_priority"] and hours_since_auto >= 24:
                        await auto_priority(db)
                        hours_since_auto = 0
        except Exception as exc:  # noqa: BLE001
            logger.warning("Gateway operations pass failed: %s", exc)
        await asyncio.sleep(wait_min * 60)


def _start() -> None:
    from .main import _track_task
    _track_task(_loop())


router.add_event_handler("startup", _start)
