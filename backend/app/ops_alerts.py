"""Operator alerts and launch readiness.

Every five minutes the worker looks for problems an operator must act on and sends them to the
alert recipients (``ALERT_TELEGRAM_CHAT_ID``, falling back to ``ADMIN_TELEGRAM_ID``, and
``ALERT_EMAIL``): a paid order whose VPN access failed or is stuck, a payment agent with an open
circuit breaker, a background worker without a heartbeat, Remnawave unreachable, a monitoring
check failing three times in a row, a failed backup. Each problem is sent once and repeated at
most every ``REPEAT`` hours while it lasts; when it disappears a short "resolved" note follows.

``GET /api/admin/ops/readiness`` lists what a live launch still needs (bot, Mini App address,
Remnawave and its webhook, payment agents, plans, backups, alert recipients).
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import get_db
from .models import (AppSetting, BackupJob, MonitoringCheck, Payment, PaymentProviderHealth, Plan, RemnawaveEvent,
                     User, WorkerState)
from .security import require_permission

logger = logging.getLogger(__name__)
router = APIRouter()
PREFIX = "ops_alert:"
REPEAT = timedelta(hours=6)
TICK_SECONDS = 300
STUCK_AFTER = timedelta(minutes=15)
STALE_WORKER = timedelta(minutes=3)


@dataclass
class Problem:
    key: str
    title: str
    detail: str
    severity: str = "high"


def recipients() -> dict:
    chat = str(settings.alert_telegram_chat_id or "") or (str(settings.admin_telegram_id) if settings.admin_telegram_id else "")
    return {"telegram": bool(chat and settings.bot_token), "telegram_chat": chat,
            "email": bool(settings.alert_email and settings.smtp_host)}


async def send(text: str) -> bool:
    """Telegram (alert chat, else the owner) and e-mail; never raises."""
    sent = False
    target = recipients()
    if target["telegram"]:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
                r = await client.post(f"https://api.telegram.org/bot{settings.bot_token}/sendMessage",
                                      json={"chat_id": target["telegram_chat"], "text": text[:4096]})
            sent = r.is_success
        except Exception as exc:
            logger.warning("Operator alert was not sent to Telegram: %s", exc)
    if target["email"]:
        try:
            await asyncio.to_thread(_email, text)
            sent = True
        except Exception as exc:
            logger.warning("Operator alert was not e-mailed: %s", exc)
    return sent


def _email(text: str) -> None:
    import smtplib
    from email.message import EmailMessage
    msg = EmailMessage()
    msg["Subject"] = "Корги Люси: " + text.splitlines()[0][:120]
    msg["From"] = settings.smtp_from or settings.smtp_user
    msg["To"] = settings.alert_email
    msg.set_content(text)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
        smtp.starttls()
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(msg)


async def collect(db: AsyncSession, now: datetime | None = None, remnawave=None) -> list[Problem]:
    now = now or datetime.utcnow()
    day = now - timedelta(days=1)
    out: list[Problem] = []
    failed = (await db.execute(select(Payment).where(Payment.status.in_(("paid", "fulfilled")), Payment.fulfillment_status == "failed",
                                                     Payment.paid_at >= day).order_by(Payment.id).limit(20))).scalars().all()
    for p in failed:
        out.append(Problem(f"fulfillment:{p.id}", f"Оплата №{p.id} без доступа",
                           f"Клиент {p.user_id} оплатил {p.amount} {p.currency}, но выдача VPN не удалась: {(p.fulfillment_error or 'ошибка')[:200]}. "
                           "Платежи → найдите платёж → «Повторить».", "critical"))
    stuck = (await db.execute(select(Payment).where(Payment.status == "paid", Payment.fulfillment_status.in_(("pending", "processing")),
                                                    Payment.paid_at <= now - STUCK_AFTER, Payment.paid_at >= day).limit(20))).scalars().all()
    for p in stuck:
        out.append(Problem(f"stuck:{p.id}", f"Оплата №{p.id} ждёт выдачи",
                           f"Оплачено {round((now - p.paid_at).total_seconds() / 60)} мин назад, доступ ещё не выдан. Проверьте Remnawave и фоновые процессы."))
    for h in (await db.execute(select(PaymentProviderHealth).where(PaymentProviderHealth.enabled.is_(True),
                                                                   PaymentProviderHealth.circuit_open_until > now))).scalars():
        out.append(Problem(f"provider:{h.provider}", f"Касса {h.provider} временно отключена",
                           f"После {h.failure_count} ошибок подряд приём через {h.provider} приостановлен до {h.circuit_open_until:%H:%M} UTC. "
                           "Тарифы и оплата → Платёжные агенты."))
    for w in (await db.execute(select(WorkerState).where(WorkerState.last_seen_at < now - STALE_WORKER, WorkerState.last_seen_at >= day,
                                                         WorkerState.status != "stopped"))).scalars():
        out.append(Problem(f"worker:{w.worker_id}", f"Фоновый процесс {w.role} не отвечает",
                           f"{w.worker_id}: последняя отметка {w.last_seen_at:%H:%M} UTC. Выдача, продления и рассылки могут стоять: ./manage.sh status."))
    for c in (await db.execute(select(MonitoringCheck).where(MonitoringCheck.enabled.is_(True), MonitoringCheck.failure_streak >= 3))).scalars():
        out.append(Problem(f"monitor:{c.id}", f"Проверка «{c.name}» не проходит",
                           f"{c.failure_streak} раз подряд: {(c.last_error or c.last_status or '')[:200]}.", "medium"))
    # A refunded or charged-back top-up that was already spent leaves a negative wallet:
    # what was bought with it stays active, so an operator decides (restrict, recover).
    for u in (await db.execute(select(User).where(User.wallet_balance < 0, User.deleted_at.is_(None)).order_by(User.id).limit(20))).scalars():
        out.append(Problem(f"wallet_debt:{u.id}", f"Отрицательный баланс клиента №{u.id}",
                           f"Баланс {u.wallet_balance}: возвращённое пополнение уже потрачено. Клиенты → №{u.id}: ограничьте доступ или договоритесь о погашении.", "warning"))
    backup = await db.scalar(select(BackupJob).order_by(BackupJob.id.desc()).limit(1))
    if backup and backup.status == "failed" and backup.created_at >= day:
        out.append(Problem(f"backup:{backup.id}", "Резервная копия не создана", (backup.error or "ошибка")[:300] + ". Безопасность → Резервные копии."))
    from .models import BackupVerification
    verification = await db.scalar(select(BackupVerification).where(BackupVerification.status.in_(("passed", "failed")))
                                   .order_by(BackupVerification.id.desc()).limit(1))
    if verification and verification.status == "failed" and verification.created_at >= now - timedelta(days=8):
        out.append(Problem(f"restore:{verification.id}", "Резервная копия не восстанавливается",
                           f"Проверка копии №{verification.backup_id}: {(verification.error or 'ошибка')[:300]}. Создайте новую копию и проверьте её."))
    if settings.remnawave_url and settings.remnawave_token:
        try:
            from .main import RemnawaveClient
            await (remnawave or RemnawaveClient()).list_nodes(start=0, size=1)
        except Exception as exc:
            out.append(Problem("remnawave", "Remnawave недоступен", f"Панель не отвечает: {str(exc)[:200]}. Новые подписки не выдаются."))
    return out


async def dispatch(db: AsyncSession, problems: list[Problem], now: datetime | None = None, sender=None) -> dict:
    """Send new and repeating problems, note resolved ones; state lives in app_settings."""
    now = now or datetime.utcnow()
    sender = sender or send
    rows = {r.key[len(PREFIX):]: r for r in (await db.execute(select(AppSetting).where(AppSetting.key.like(PREFIX + "%")))).scalars()}
    current = {p.key: p for p in problems}
    sent, resolved = [], []
    for key, p in current.items():
        row = rows.get(key)
        state = json.loads(row.value) if row else {}
        last = datetime.fromisoformat(state["sent_at"]) if state.get("sent_at") else None
        if last and now - last < REPEAT:
            continue
        icon = {"critical": "🚨", "high": "⚠️", "medium": "🔔"}.get(p.severity, "⚠️")
        if await sender(f"{icon} {p.title}\n\n{p.detail}"):
            value = json.dumps({"sent_at": now.isoformat(), "title": p.title, "severity": p.severity}, ensure_ascii=False)
            if row:
                row.value = value
            else:
                db.add(AppSetting(key=PREFIX + key, value=value))
            sent.append(key)
    for key, row in rows.items():
        if key not in current:
            title = json.loads(row.value).get("title", key)
            await sender(f"✅ Решено: {title}")
            await db.delete(row)
            resolved.append(key)
    await db.commit()
    return {"sent": sent, "resolved": resolved}


async def ops_alert_scheduler(session_factory=None):
    from sqlalchemy.ext.asyncio import AsyncSession as Session
    from .db import engine
    factory = session_factory or (lambda: Session(engine, expire_on_commit=False))
    await asyncio.sleep(60)  # let the other workers report their first heartbeat
    while True:
        try:
            if recipients()["telegram"] or recipients()["email"]:
                async with factory() as db:
                    await dispatch(db, await collect(db))
                async with factory() as db:
                    await send_weekly_summary(db)
        except Exception:
            logger.exception("operator alert scheduler failed")
        await asyncio.sleep(TICK_SECONDS)


@router.get("/api/admin/ops/alerts")
async def alerts_status(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("ops.diagnostics"))):
    target = recipients()
    open_rows = (await db.execute(select(AppSetting).where(AppSetting.key.like(PREFIX + "%")))).scalars().all()
    return {"recipients": {"telegram": target["telegram"], "email": target["email"]},
            "open": [{"key": r.key[len(PREFIX):], **json.loads(r.value)} for r in open_rows],
            "problems": [p.__dict__ for p in await collect(db)], "repeat_hours": int(REPEAT.total_seconds() // 3600)}


@router.post("/api/admin/ops/alerts/test")
async def alerts_test(admin=Depends(require_permission("ops.diagnostics"))):
    target = recipients()
    if not (target["telegram"] or target["email"]):
        from fastapi import HTTPException
        raise HTTPException(409, "Получатель оповещений не настроен: укажите ALERT_TELEGRAM_CHAT_ID или ADMIN_TELEGRAM_ID (и BOT_TOKEN) либо ALERT_EMAIL и SMTP")
    ok = await send(f"🐶 Проверка оповещений: {admin.email} — сообщения о сбоях приходят сюда.")
    return {"ok": ok}


@router.get("/api/admin/ops/readiness")
async def readiness(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("ops.diagnostics"))):
    """What a live launch still needs: a list of checks with a short hint each."""
    from .payment_policy import PAYMENT_AGENTS
    now = datetime.utcnow()
    checks = []

    def check(key, title, ok, hint, level="required"):
        checks.append({"key": key, "title": title, "ok": bool(ok), "hint": "" if ok else hint, "level": level})

    check("bot", "Telegram-бот", settings.bot_token and settings.bot_username, "Задайте BOT_TOKEN и BOT_USERNAME в .env.")
    check("miniapp", "Адрес Mini App", str(settings.mini_app_url or "").startswith("https://"), "MINI_APP_URL должен начинаться с https://.")
    check("remnawave", "Remnawave", settings.remnawave_url and settings.remnawave_token, "Задайте REMNAWAVE_URL и REMNAWAVE_TOKEN.")
    last_event = await db.scalar(select(RemnawaveEvent.created_at).order_by(RemnawaveEvent.id.desc()).limit(1))
    check("remnawave_webhook", "Вебхуки Remnawave", settings.remnawave_webhook_secret and last_event,
          "Задайте REMNAWAVE_WEBHOOK_SECRET и включите WEBHOOK_ENABLED в панели (модуль 18)" if not settings.remnawave_webhook_secret
          else "Секрет задан, но событий от панели ещё не было: проверьте WEBHOOK_URL и WEBHOOK_SECRET_HEADER в панели.", "recommended")
    configured = [p for p in PAYMENT_AGENTS if _agent_configured(p)]
    check("payments", "Платёжные агенты", configured, "Задайте ключи хотя бы одного агента: YooKassa, Platega, RollyPay или CryptoBot (модуль 07).")
    check("plans", "Тарифы в продаже", await db.scalar(select(Plan.id).where(Plan.enabled.is_(True)).limit(1)), "Создайте и включите тариф (модуль 06).")
    backup = await db.scalar(select(BackupJob).where(BackupJob.status.in_(("completed", "done", "succeeded", "ok"))).order_by(BackupJob.id.desc()).limit(1))
    check("backup", "Резервная копия за сутки", backup and (backup.finished_at or backup.created_at) >= now - timedelta(days=1),
          "Создайте копию: bash scripts/backup.sh или Безопасность → Резервные копии.")
    target = recipients()
    from .models import BackupVerification
    checked = await db.scalar(select(BackupVerification).where(BackupVerification.status == "passed", BackupVerification.created_at >= now - timedelta(days=8))
                              .order_by(BackupVerification.id.desc()).limit(1))
    check("restore", "Проверка восстановления за неделю", checked,
          "Магазин раз в неделю сам восстанавливает последнюю копию во временную базу; запустить вручную — Безопасность → Резервные копии → «Проверить восстановление».",
          "recommended")
    check("alerts", "Оповещения о сбоях", target["telegram"] or target["email"], "Укажите ALERT_TELEGRAM_CHAT_ID (или ADMIN_TELEGRAM_ID) либо ALERT_EMAIL.", "recommended")
    required = [c for c in checks if c["level"] == "required"]
    return {"ready": all(c["ok"] for c in required), "agents": configured, "checks": checks}


def _agent_configured(provider: str) -> bool:
    keys = {"yookassa": ("yookassa_shop_id", "yookassa_secret_key"), "platega": ("platega_merchant_id", "platega_secret"),
            "rollypay": ("rollypay_api_key", "rollypay_signing_secret"), "cryptobot": ("cryptobot_token",)}.get(provider, ())
    return bool(keys) and all(getattr(settings, k, "") for k in keys)


# ================================================================ weekly summary

SUMMARY_KEY = "ops_summary:last_week"


async def weekly_summary(db: AsyncSession, now: datetime | None = None) -> dict:
    """The last seven days in numbers: revenue, customers, churn, refunds, open problems."""
    from sqlalchemy import func
    from .models import RefundRequest, Subscription, User
    now = now or datetime.utcnow()
    since = now - timedelta(days=7)
    paid = (Payment.status.in_(("paid", "fulfilled")), Payment.paid_at >= since, Payment.paid_at < now, Payment.provider != "wallet")
    revenue = {cur: str(total) for cur, total in (await db.execute(
        select(Payment.currency, func.coalesce(func.sum(Payment.amount), 0)).where(*paid).group_by(Payment.currency))).all()}
    payments = int(await db.scalar(select(func.count()).select_from(Payment).where(*paid)) or 0)
    first_paid = select(Payment.user_id, func.min(Payment.paid_at).label("first")).where(
        Payment.status.in_(("paid", "fulfilled")), Payment.paid_at.is_not(None), Payment.purpose == "subscription").group_by(Payment.user_id).subquery()
    new_paying = int(await db.scalar(select(func.count()).select_from(first_paid).where(first_paid.c.first >= since, first_paid.c.first < now)) or 0)
    signups = int(await db.scalar(select(func.count()).select_from(User).where(User.created_at >= since, User.created_at < now)) or 0)
    # Ended this week and not renewed: the subscription's expiry is still in the past.
    ended = int(await db.scalar(select(func.count()).select_from(Subscription).where(
        Subscription.expires_at >= since, Subscription.expires_at < now)) or 0)
    active = int(await db.scalar(select(func.count()).select_from(Subscription).where(
        Subscription.expires_at > now, Subscription.lifecycle_status.in_(("active", "grace", "cancel_scheduled")))) or 0)
    refunds = (await db.execute(select(func.count(), func.coalesce(func.sum(RefundRequest.amount), 0)).where(
        RefundRequest.status == "refunded", RefundRequest.updated_at >= since, RefundRequest.updated_at < now))).one()
    problems = await collect(db, now)
    return {"from": since, "to": now, "revenue": revenue, "payments": payments, "new_paying": new_paying, "signups": signups,
            "ended": ended, "active": active, "refunds": {"count": int(refunds[0] or 0), "amount": str(refunds[1] or 0)},
            "problems": [p.title for p in problems]}


def summary_text(s: dict) -> str:
    money = ", ".join(f"{amount} {cur}" for cur, amount in sorted(s["revenue"].items())) or "0"
    lines = [f"📊 Неделя {s['from']:%d.%m}–{s['to']:%d.%m}",
             f"Выручка: {money} · оплат: {s['payments']}",
             f"Новые платящие: {s['new_paying']} · регистраций: {s['signups']}",
             f"Активных подписок: {s['active']} · закончились за неделю: {s['ended']}",
             f"Возвраты: {s['refunds']['count']} на {s['refunds']['amount']}"]
    lines.append("Сейчас проблем нет ✅" if not s["problems"] else "Открытые проблемы: " + "; ".join(s["problems"][:5]))
    return "\n".join(lines)


def summary_due(now: datetime, last: str | None) -> bool:
    """Monday from 09:00 Moscow time (06:00 UTC), once per ISO week."""
    week = f"{now.isocalendar()[0]}-{now.isocalendar()[1]:02d}"
    return now.weekday() == 0 and now.hour >= 6 and last != week


async def send_weekly_summary(db: AsyncSession, now: datetime | None = None, sender=None) -> bool:
    now = now or datetime.utcnow()
    row = await db.get(AppSetting, SUMMARY_KEY)
    if not summary_due(now, row.value if row else None):
        return False
    if not await (sender or send)(summary_text(await weekly_summary(db, now))):
        return False
    week = f"{now.isocalendar()[0]}-{now.isocalendar()[1]:02d}"
    if row:
        row.value = week
    else:
        db.add(AppSetting(key=SUMMARY_KEY, value=week))
    await db.commit()
    return True


@router.get("/api/admin/ops/summary")
async def summary_preview(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("ops.diagnostics"))):
    data = await weekly_summary(db)
    return {**data, "text": summary_text(data)}


@router.post("/api/admin/ops/summary/send")
async def summary_send_now(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("ops.diagnostics"))):
    target = recipients()
    if not (target["telegram"] or target["email"]):
        from fastapi import HTTPException
        raise HTTPException(409, "Получатель оповещений не настроен")
    return {"ok": await send(summary_text(await weekly_summary(db)))}
