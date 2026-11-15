"""Automation engine: rules "event → conditions → actions" and scheduled campaigns.

Rules run in the worker every few minutes. An event is a state the shop can see in
its own tables (an expiring subscription, a fulfilled payment, a new customer...).
Each (rule, anchor) pair is executed once: the ``automation_executions`` row is the
idempotency key, so a restart or a second worker never repeats an action.

Actions are deliberately few and bounded:
* ``notify`` — an in-app notification (push fans out from it) and, optionally, a
  Telegram message;
* ``wallet_bonus`` — a credit to the shop wallet, recorded in the financial ledger,
  limited per action and per rule per day.

Campaigns with status ``scheduled`` are handed to the existing broadcast queue at
their start time, and their counters follow the broadcast.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import exists, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import get_db
from .models import AutomationExecution, AutomationRule, Broadcast, Campaign, Payment, Subscription, User
from .security import require_permission

logger = logging.getLogger(__name__)
router = APIRouter()

TICK_SECONDS = 300
MAX_PER_TICK = 200
MAX_BONUS = Decimal("1000")
DEFAULT_DAILY_LIMIT = 500

EVENTS: dict[str, dict[str, Any]] = {
    "subscription.expiring": {"label": "Подписка скоро закончится", "days": (3, 1, 30),
                              "hint": "Срабатывает один раз на каждый срок подписки за N дней до конца."},
    "subscription.expired": {"label": "Подписка закончилась и не продлена", "days": (1, 0, 30),
                             "hint": "Через N дней после окончания, если у клиента нет другой активной подписки."},
    "payment.paid": {"label": "Оплата прошла и доступ выдан", "days": None,
                     "hint": "Каждая оплата после создания правила."},
    "user.registered": {"label": "Новый клиент", "days": None,
                        "hint": "Каждый клиент, зарегистрированный после создания правила."},
    "user.no_purchase": {"label": "Клиент не купил за N дней", "days": (3, 1, 60),
                         "hint": "Через N дней после регистрации, если не было ни одной оплаты."},
    "trial.ended": {"label": "Пробный период закончился без покупки", "days": (1, 0, 30),
                    "hint": "Через N дней после конца пробного периода, если клиент ничего не купил."},
    # «days» of this event counts minutes (unit «мин.»): a forgotten checkout is worth a nudge within the hour.
    "payment.abandoned": {"label": "Начал оплату и не заплатил", "days": (15, 5, 4320), "unit": "мин.",
                          "hint": "Через N минут после открытия оплаты, если ни этот, ни другой платёж клиента не прошёл."},
    "auto_renew.failed": {"label": "Автопродление не прошло", "days": (0, 0, 14),
                          "hint": "Через N дней после третьего отказа банка, если клиент не оплатил подписку сам."},
}
# Remnawave webhook events (see remnawave_events.py): each received event triggers once.
for _event, _label in (("remnawave.traffic_threshold", "Remnawave: трафик заканчивается"), ("remnawave.limited", "Remnawave: трафик закончился"),
                       ("remnawave.expired", "Remnawave: подписка истекла"), ("remnawave.first_connected", "Remnawave: первое подключение"),
                       ("remnawave.not_connected", "Remnawave: клиент не подключился"), ("remnawave.expiration", "Remnawave: срок скоро закончится")):
    EVENTS[_event] = {"label": _label, "days": None, "hint": "Каждое событие из вебхука Remnawave после создания правила (нужен REMNAWAVE_WEBHOOK_SECRET)."}
MAX_PROMO_PERCENT = 90

# Ready-made win-back scenarios: created disabled, the administrator reviews and enables them.
PRESETS = {
    "winback_expired": {"name": "Возврат: подписка истекла 3 дня назад", "event": "subscription.expired", "conditions": {"days": 3, "daily_limit": 300},
                        "actions": {"notify": {"title": "Скучаем! −20% на продление", "body": "Подписка закончилась {expires_at}. Ваш личный промокод {promo} даёт скидку 20% на 48 часов.", "telegram": True},
                                    "promo_code": {"percent": 20, "days": 2}}},
    "trial_no_purchase": {"name": "Возврат: пробный период закончился", "event": "trial.ended", "conditions": {"days": 1, "daily_limit": 300},
                          "actions": {"notify": {"title": "Понравился VPN? −15% на первый месяц", "body": "Пробный период закончился. Промокод {promo} действует 3 дня.", "telegram": True},
                                      "promo_code": {"percent": 15, "days": 3}}},
    "expiring_reminder": {"name": "Напоминание: подписка закончится через 3 дня", "event": "subscription.expiring", "conditions": {"days": 3, "daily_limit": 500},
                          "actions": {"notify": {"title": "Подписка скоро закончится", "body": "Подписка действует до {expires_at}. Продлите заранее, чтобы VPN не отключился.", "telegram": True}}},
    "no_purchase_week": {"name": "Возврат: зарегистрировался, но не купил за 7 дней", "event": "user.no_purchase", "conditions": {"days": 7, "daily_limit": 300},
                         "actions": {"notify": {"title": "Первый месяц со скидкой 10%", "body": "Промокод {promo} на первую покупку действует 3 дня.", "telegram": True},
                                     "promo_code": {"percent": 10, "days": 3}}},
    "checkout_nudge": {"name": "Возврат оплаты: начал и не заплатил 15 минут", "event": "payment.abandoned", "conditions": {"days": 15, "daily_limit": 500},
                       "actions": {"notify": {"title": "Оплата не прошла?", "body": "Если карта не подошла, выберите другой способ — СБП или другую кассу — в разделе «Тарифы». Подписка включится сразу после оплаты.", "telegram": True}}},
    "checkout_promo": {"name": "Возврат оплаты: не заплатил за сутки — промокод", "event": "payment.abandoned", "conditions": {"days": 1440, "daily_limit": 300},
                       "actions": {"notify": {"title": "−10% на подписку", "body": "Вы начали оформлять подписку, но не закончили. Промокод {promo} даёт скидку 10% на 48 часов.", "telegram": True},
                                   "promo_code": {"percent": 10, "days": 2}}},
    "renew_failed_now": {"name": "Автопродление не прошло: сразу", "event": "auto_renew.failed", "conditions": {"days": 0, "daily_limit": 500},
                         "actions": {"notify": {"title": "Не удалось продлить подписку", "body": "Банк трижды отклонил автоплатёж. Продлите подписку в разделе «Тарифы» любым способом оплаты, чтобы VPN не отключился.", "telegram": True}}},
    "renew_failed_day1": {"name": "Автопродление не прошло: через день", "event": "auto_renew.failed", "conditions": {"days": 1, "daily_limit": 500},
                          "actions": {"notify": {"title": "Подписку ещё можно продлить", "body": "Продлите подписку в разделе «Тарифы»: СБП, карта или криптовалюта.", "telegram": True}}},
    "renew_failed_day3": {"name": "Автопродление не прошло: через 3 дня — скидка", "event": "auto_renew.failed", "conditions": {"days": 3, "daily_limit": 300},
                          "actions": {"notify": {"title": "−15% на продление", "body": "Промокод {promo} даёт скидку 15% на продление в течение 3 дней.", "telegram": True},
                                      "promo_code": {"percent": 15, "days": 3}}},
    "traffic_limited": {"name": "Допродажа: трафик закончился", "event": "remnawave.limited", "conditions": {"daily_limit": 500},
                        "actions": {"notify": {"title": "Трафик закончился", "body": "VPN приостановлен до конца периода. Докупите пакет трафика в разделе «Моя подписка» — доступ вернётся сразу.", "telegram": True}}},
    "traffic_upsell": {"name": "Допродажа: трафик заканчивается", "event": "remnawave.traffic_threshold", "conditions": {"daily_limit": 500},
                       "actions": {"notify": {"title": "Трафик заканчивается", "body": "Докупите пакет трафика в разделе «Моя подписка» — VPN продолжит работать без перерыва.", "telegram": True}}},
}
SEGMENTS = {"all": "Все клиенты с Telegram", "active": "С активной подпиской", "inactive": "Без активной подписки"}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _decimal(value, field: str) -> Decimal:
    try:
        number = Decimal(str(value)).quantize(Decimal(".01"))
    except (InvalidOperation, ValueError):
        raise HTTPException(400, f"{field}: нужно число")
    return number


def validate_rule(event: str, conditions: dict, actions: dict) -> tuple[dict, dict]:
    """Return normalized conditions and actions or raise HTTP 400 with the reason."""
    if event not in EVENTS:
        raise HTTPException(400, "Неизвестное событие: " + ", ".join(EVENTS))
    spec = EVENTS[event]
    cond: dict[str, Any] = {}
    if spec["days"]:
        default, low, high = spec["days"]
        try:
            days = int(conditions.get("days", default))
        except (TypeError, ValueError):
            raise HTTPException(400, "Дни: нужно целое число")
        if not low <= days <= high:
            raise HTTPException(400, f"Дни: от {low} до {high}")
        cond["days"] = days
    plan_ids = conditions.get("plan_ids") or []
    if not isinstance(plan_ids, list) or not all(isinstance(x, int) and x > 0 for x in plan_ids):
        raise HTTPException(400, "Тарифы: список ID")
    if plan_ids:
        cond["plan_ids"] = sorted(set(plan_ids))
    for key in ("min_amount", "max_amount"):
        if conditions.get(key) not in (None, ""):
            if event != "payment.paid":
                raise HTTPException(400, "Сумма оплаты применима только к событию «Оплата прошла»")
            cond[key] = str(_decimal(conditions[key], "Сумма"))
    try:
        daily = int(conditions.get("daily_limit", DEFAULT_DAILY_LIMIT))
    except (TypeError, ValueError):
        raise HTTPException(400, "Лимит в сутки: нужно целое число")
    if not 1 <= daily <= 10000:
        raise HTTPException(400, "Лимит в сутки: от 1 до 10000")
    cond["daily_limit"] = daily

    act: dict[str, Any] = {}
    notify = actions.get("notify")
    if notify:
        title, body = str(notify.get("title") or "").strip(), str(notify.get("body") or "").strip()
        if not title or not body or len(title) > 120 or len(body) > 2000:
            raise HTTPException(400, "Уведомление: заголовок до 120 и текст до 2000 символов")
        act["notify"] = {"title": title, "body": body, "telegram": bool(notify.get("telegram"))}
    bonus = actions.get("wallet_bonus")
    if bonus:
        amount = _decimal(bonus.get("amount"), "Бонус")
        if not Decimal("0.01") <= amount <= MAX_BONUS:
            raise HTTPException(400, f"Бонус: от 0.01 до {MAX_BONUS}")
        act["wallet_bonus"] = {"amount": str(amount)}
    promo = actions.get("promo_code")
    if promo:
        try:
            percent, days = int(promo.get("percent")), int(promo.get("days", 2))
        except (TypeError, ValueError):
            raise HTTPException(400, "Промокод: процент и дни — целые числа")
        if not 5 <= percent <= MAX_PROMO_PERCENT or not 1 <= days <= 30:
            raise HTTPException(400, f"Промокод: скидка 5–{MAX_PROMO_PERCENT}%, срок 1–30 дней")
        if not act.get("notify"):
            raise HTTPException(400, "Промокод отправляется в уведомлении: добавьте уведомление с {promo}")
        act["promo_code"] = {"percent": percent, "days": days}
    if not act:
        raise HTTPException(400, "Выберите хотя бы одно действие: уведомление или бонус")
    return cond, act


# ---------------------------------------------------------------------------
# Candidates
# ---------------------------------------------------------------------------

def _active_sub(now: datetime):
    return exists().where(Subscription.user_id == User.id, Subscription.expires_at.is_not(None), Subscription.expires_at > now)


async def candidates(db: AsyncSession, rule: AutomationRule, now: datetime, limit: int = MAX_PER_TICK) -> list[tuple[int, str, dict]]:
    """(user_id, anchor, context) of every pending execution of the rule, oldest first."""
    cond = rule.conditions or {}
    plans = cond.get("plan_ids") or []
    since = max(rule.created_at, now - timedelta(days=1))
    done = select(AutomationExecution.anchor).where(AutomationExecution.rule_id == rule.id)
    rows: list[tuple[int, str, dict]] = []
    if rule.event in {"subscription.expiring", "subscription.expired"}:
        days = int(cond.get("days", EVENTS[rule.event]["days"][0]))
        q = select(Subscription).join(User, User.id == Subscription.user_id).where(
            Subscription.expires_at.is_not(None), User.deleted_at.is_(None))
        if rule.event == "subscription.expiring":
            q = q.where(Subscription.expires_at > now, Subscription.expires_at <= now + timedelta(days=days))
        else:
            # Only expiries after the rule existed (and at most a week back): no mass mailing of old customers.
            q = q.where(Subscription.expires_at <= now - timedelta(days=days),
                        Subscription.expires_at >= max(now - timedelta(days=days + 7), rule.created_at - timedelta(days=days)),
                        ~_active_sub(now))
        if plans:
            q = q.where(Subscription.plan_id.in_(plans))
        for sub in (await db.execute(q.order_by(Subscription.expires_at).limit(limit * 3))).scalars():
            rows.append((sub.user_id, f"sub:{sub.id}:{sub.expires_at:%Y%m%d%H%M}", {"subscription_id": sub.id, "expires_at": sub.expires_at}))
    elif rule.event == "payment.paid":
        q = select(Payment).join(User, User.id == Payment.user_id).where(
            Payment.status.in_(("paid", "fulfilled")), Payment.fulfillment_status == "completed",
            Payment.paid_at.is_not(None), Payment.paid_at >= since, User.deleted_at.is_(None))
        if plans:
            q = q.where(Payment.plan_id.in_(plans))
        if cond.get("min_amount"):
            q = q.where(Payment.amount >= Decimal(cond["min_amount"]))
        if cond.get("max_amount"):
            q = q.where(Payment.amount <= Decimal(cond["max_amount"]))
        for p in (await db.execute(q.order_by(Payment.paid_at).limit(limit * 3))).scalars():
            rows.append((p.user_id, f"payment:{p.id}", {"payment_id": p.id, "amount": p.amount}))
    elif rule.event == "user.registered":
        q = select(User).where(User.created_at >= since, User.deleted_at.is_(None))
        for u in (await db.execute(q.order_by(User.created_at).limit(limit * 3))).scalars():
            rows.append((u.id, f"user:{u.id}", {}))
    elif rule.event.startswith("remnawave."):
        from .models import RemnawaveEvent
        source = rule.event.replace("remnawave.", "user.").replace("user.traffic_threshold", "user.bandwidth_usage_threshold_reached")
        q = select(RemnawaveEvent).where(RemnawaveEvent.event == source, RemnawaveEvent.user_id.is_not(None),
                                         RemnawaveEvent.created_at >= rule.created_at, RemnawaveEvent.created_at >= now - timedelta(days=7))
        for ev in (await db.execute(q.order_by(RemnawaveEvent.id).limit(limit * 3))).scalars():
            rows.append((ev.user_id, f"rwevent:{ev.id}", {"subscription_id": ev.subscription_id}))
    elif rule.event == "trial.ended":
        from .models import TrialGrant
        days = int(cond.get("days", 1))
        paid = exists().where(Payment.user_id == TrialGrant.user_id, Payment.status.in_(("paid", "fulfilled")))
        q = select(TrialGrant).where(TrialGrant.expires_at <= now - timedelta(days=days),
                                     TrialGrant.expires_at >= max(now - timedelta(days=days + 7), rule.created_at - timedelta(days=days)), ~paid)
        for grant in (await db.execute(q.order_by(TrialGrant.expires_at).limit(limit * 3))).scalars():
            rows.append((grant.user_id, f"trial:{grant.id}:ended:{days}", {"expires_at": grant.expires_at}))
    elif rule.event == "payment.abandoned":
        minutes = int(cond.get("days", 15))
        cutoff = now - timedelta(minutes=minutes)
        later = Payment.__table__.alias("later")
        paid_after = exists().where(later.c.user_id == Payment.user_id, later.c.status.in_(("paid", "fulfilled")),
                                    later.c.created_at >= Payment.created_at)
        q = select(Payment).join(User, User.id == Payment.user_id).where(
            Payment.purpose == "subscription", Payment.status.in_(("pending", "failed", "canceled", "cancelled", "expired")),
            Payment.created_at <= cutoff, Payment.created_at >= max(rule.created_at - timedelta(minutes=minutes), now - timedelta(minutes=minutes) - timedelta(days=2)),
            User.deleted_at.is_(None), ~paid_after)
        if plans:
            q = q.where(Payment.plan_id.in_(plans))
        seen: set[int] = set()
        for p in (await db.execute(q.order_by(Payment.created_at.desc()).limit(limit * 3))).scalars():
            if p.user_id in seen:
                continue  # several attempts of one customer: one message
            seen.add(p.user_id)
            rows.append((p.user_id, f"abandoned:{p.user_id}:{p.plan_id}:{p.created_at:%Y%m%d}:{minutes}", {"payment_id": p.id, "amount": p.amount}))
    elif rule.event == "auto_renew.failed":
        from .models import AutoRenewMethod
        days = int(cond.get("days", 0))
        paid_after = exists().where(Payment.user_id == AutoRenewMethod.user_id, Payment.status.in_(("paid", "fulfilled")),
                                    Payment.paid_at >= AutoRenewMethod.last_attempt_at)
        q = select(AutoRenewMethod).join(User, User.id == AutoRenewMethod.user_id).where(
            AutoRenewMethod.status == "payment_failed", AutoRenewMethod.last_attempt_at.is_not(None),
            AutoRenewMethod.last_attempt_at <= now - timedelta(days=days),
            AutoRenewMethod.last_attempt_at >= max(rule.created_at - timedelta(days=days), now - timedelta(days=days + 7)),
            User.deleted_at.is_(None), ~paid_after)
        for m in (await db.execute(q.order_by(AutoRenewMethod.last_attempt_at).limit(limit * 3))).scalars():
            rows.append((m.user_id, f"renew_failed:{m.id}:{m.last_attempt_at:%Y%m%d%H%M}:{days}", {}))
    elif rule.event == "user.no_purchase":
        days = int(cond.get("days", 3))
        cutoff = now - timedelta(days=days)
        paid = exists().where(Payment.user_id == User.id, Payment.status.in_(("paid", "fulfilled")))
        q = select(User).where(User.created_at <= cutoff, User.created_at >= rule.created_at - timedelta(days=days),
                               User.deleted_at.is_(None), ~paid)
        for u in (await db.execute(q.order_by(User.created_at).limit(limit * 3))).scalars():
            rows.append((u.id, f"user:{u.id}:no_purchase:{days}", {}))
    anchors = set((await db.execute(done.where(AutomationExecution.anchor.in_([a for _, a, _ in rows])))).scalars()) if rows else set()
    return [r for r in rows if r[1] not in anchors][:limit]


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def _render(text: str, user: User, ctx: dict) -> str:
    values = {"name": user.username or "", "expires_at": ctx["expires_at"].strftime("%d.%m.%Y") if ctx.get("expires_at") else "",
              "amount": str(ctx.get("amount") or ""), "promo": str(ctx.get("promo") or "")}
    for key, value in values.items():
        text = text.replace("{" + key + "}", value)
    return text


async def _telegram(chat_id: int, text: str) -> bool:
    """One Telegram message, honoring 429 retry_after (Bot API flood control)."""
    if not settings.bot_token or not chat_id:
        return False
    import httpx
    url = f"https://api.telegram.org/bot{settings.bot_token}/sendMessage"
    async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
        for _ in range(3):
            response = await client.post(url, json={"chat_id": chat_id, "text": text[:4096]})
            if response.status_code != 429:
                return response.is_success
            try:
                wait = float(response.json().get("parameters", {}).get("retry_after", 1))
            except Exception:
                wait = 1.0
            await asyncio.sleep(min(max(wait, 0.5), 30))
    return False


async def execute(db: AsyncSession, rule: AutomationRule, user_id: int, anchor: str, ctx: dict) -> str | None:
    """Run the rule's actions for one anchor exactly once. Returns a Telegram text to send after commit."""
    from . import main
    try:
        async with db.begin_nested():
            db.add(AutomationExecution(rule_id=rule.id, user_id=user_id, anchor=anchor, created_at=datetime.utcnow()))
            await db.flush()
    except IntegrityError:
        return None
    user = await db.scalar(select(User).where(User.id == user_id).with_for_update())
    if not user or user.deleted_at is not None:
        return None
    actions = rule.actions or {}
    telegram_text = None
    if actions.get("wallet_bonus"):
        amount = Decimal(actions["wallet_bonus"]["amount"])
        user.wallet_balance = (Decimal(user.wallet_balance or 0) + amount).quantize(Decimal(".01"))
        await main.record_financial_event(db, operation_key=f"automation:{rule.id}:{anchor}", user_id=user.id, payment_id=None,
                                          kind="automation_bonus", direction="credit", amount=amount, currency=settings.default_currency,
                                          metadata={"rule_id": rule.id, "anchor": anchor})
    if actions.get("promo_code"):
        # A single-use personal code that expires: shareable, but only one purchase can use it.
        import secrets as _secrets
        from .models import PromoCode
        spec = actions["promo_code"]
        code = "BACK" + _secrets.token_hex(4).upper()
        db.add(PromoCode(code=code, kind="percent", value=Decimal(spec["percent"]), usage_limit=1, max_uses_per_user=1,
                         starts_at=datetime.utcnow(), ends_at=datetime.utcnow() + timedelta(days=int(spec["days"]))))
        await db.flush()
        ctx = {**ctx, "promo": code}
    if actions.get("notify"):
        title = _render(actions["notify"]["title"], user, ctx)
        body = _render(actions["notify"]["body"], user, ctx)
        await main.enqueue_notification(db, user_id=user.id, channel="in_app", kind="automation", title=title, body=body,
                                        dedupe_key=f"automation:{rule.id}:{anchor}")
        if actions["notify"].get("telegram") and user.telegram_id:
            telegram_text = f"{title}\n\n{body}"
    return telegram_text


async def run_rule(session_factory, rule_id: int, now: datetime | None = None, send=_telegram) -> int:
    now = now or datetime.utcnow()
    async with session_factory() as db:
        rule = await db.get(AutomationRule, rule_id)
        if not rule or not rule.enabled:
            return 0
        daily = int((rule.conditions or {}).get("daily_limit", DEFAULT_DAILY_LIMIT))
        today = await db.scalar(select(func.count()).select_from(AutomationExecution).where(
            AutomationExecution.rule_id == rule.id, AutomationExecution.created_at >= now - timedelta(days=1))) or 0
        room = max(0, min(MAX_PER_TICK, daily - today))
        if not room:
            return 0
        pending = await candidates(db, rule, now, room)
        outbox: list[tuple[int, str]] = []
        done = 0
        for user_id, anchor, ctx in pending:
            text = await execute(db, rule, user_id, anchor, ctx)
            done += 1
            if text:
                chat = await db.scalar(select(User.telegram_id).where(User.id == user_id))
                outbox.append((chat, text))
        if done:
            rule.run_count = int(rule.run_count or 0) + done
            rule.last_run_at = now
            from . import main
            await main.audit(db, "automation.rule.executed", "system", str(rule.id), {"executions": done})
        await db.commit()
    for chat, text in outbox:
        try:
            await send(chat, text)
        except Exception as exc:
            logger.warning("Automation Telegram message failed: %s", type(exc).__name__)
        await asyncio.sleep(0.05)  # stay well under Telegram's ~30 messages per second
    return done


async def run_campaigns(session_factory, now: datetime | None = None) -> int:
    """Start due campaigns through the broadcast queue and mirror their counters."""
    now = now or datetime.utcnow()
    started = 0
    async with session_factory() as db:
        due = (await db.execute(select(Campaign).where(Campaign.status == "scheduled",
                                                       (Campaign.starts_at.is_(None)) | (Campaign.starts_at <= now)).with_for_update(skip_locked=True))).scalars().all()
        for c in due:
            content = dict(c.content or {})
            if c.ends_at and c.ends_at <= now:
                c.status = "completed"; content["error"] = "Срок кампании прошёл до запуска"
            elif not str(content.get("text") or "").strip():
                c.status = "paused"; content["error"] = "Нет текста сообщения"
            elif not settings.bot_token:
                c.status = "paused"; content["error"] = "BOT_TOKEN не настроен"
            else:
                segment = (c.audience or {}).get("segment") or (c.audience or {}).get("type") or "all"
                b = Broadcast(text=str(content["text"])[:4096], target=segment if segment in SEGMENTS else "all",
                              button_text=content.get("button_text") or None, button_url=content.get("button_url") or None,
                              image_url=content.get("image_url") or None, status="queued")
                db.add(b); await db.flush()
                content["broadcast_id"] = b.id; content.pop("error", None)
                c.status = "running"; started += 1
            c.content = content; c.updated_at = now
        running = (await db.execute(select(Campaign).where(Campaign.status == "running"))).scalars().all()
        for c in running:
            b = await db.get(Broadcast, (c.content or {}).get("broadcast_id") or 0)
            if not b:
                continue
            c.sent_count, c.failed_count = int(b.sent_count or 0), int(b.failed_count or 0)
            if b.status in {"completed", "failed"}:
                c.status = "completed" if b.status == "completed" else "paused"
                c.updated_at = now
        await db.commit()
    return started


async def automation_scheduler():
    from . import main
    from sqlalchemy.ext.asyncio import AsyncSession as Session
    factory = lambda: Session(main.engine, expire_on_commit=False)
    while True:
        try:
            if not await _paused(factory):
                async with factory() as db:
                    ids = list((await db.execute(select(AutomationRule.id).where(AutomationRule.enabled.is_(True))
                                                 .order_by(AutomationRule.priority, AutomationRule.id))).scalars())
                for rule_id in ids:
                    await run_rule(factory, rule_id)
                await run_campaigns(factory)
        except Exception:
            logger.exception("automation scheduler failure")
        await asyncio.sleep(TICK_SECONDS)


async def _paused(factory) -> bool:
    from . import main
    async with factory() as db:
        return await main.maintenance_enabled(db)


# ---------------------------------------------------------------------------
# Admin API
# ---------------------------------------------------------------------------

@router.get("/api/admin/automation/catalog")
async def catalog(admin=Depends(require_permission("read"))):
    return {"events": [{"id": k, "label": v["label"], "hint": v["hint"], "days": v["days"], "unit": v.get("unit", "дн.")} for k, v in EVENTS.items()],
            "segments": [{"id": k, "label": v} for k, v in SEGMENTS.items()], "max_bonus": str(MAX_BONUS),
            "placeholders": ["{name}", "{expires_at}", "{amount}", "{promo}"], "tick_seconds": TICK_SECONDS,
            "max_promo_percent": MAX_PROMO_PERCENT,
            "presets": [{"id": k, "name": v["name"], "event": v["event"], "body": v["actions"]["notify"]["body"]} for k, v in PRESETS.items()]}


@router.post("/api/admin/automation/presets/{preset_id}")
async def create_preset(preset_id: str, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("feature_flags.manage"))):
    from . import main
    preset = PRESETS.get(preset_id)
    if not preset:
        raise HTTPException(404, "Сценарий не найден")
    cond, act = validate_rule(preset["event"], preset["conditions"], preset["actions"])
    rule = AutomationRule(name=preset["name"], event=preset["event"], conditions=cond, actions=act, enabled=False, priority=100)
    db.add(rule)
    await db.flush()
    await main.audit(db, "automation.preset.created", admin.email, str(rule.id), {"preset": preset_id})
    await db.commit()
    return {"id": rule.id, "name": rule.name, "enabled": False}


@router.get("/api/admin/automation/rules/{rule_id}/preview")
async def preview(rule_id: int, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("read"))):
    rule = await db.get(AutomationRule, rule_id)
    if not rule:
        raise HTTPException(404, "Правило не найдено")
    rows = await candidates(db, rule, datetime.utcnow(), 1000)
    return {"pending": len(rows), "sample_user_ids": [u for u, _, _ in rows[:20]]}


@router.delete("/api/admin/automation/rules/{rule_id}")
async def delete_rule(rule_id: int, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("feature_flags.manage"))):
    rule = await db.get(AutomationRule, rule_id)
    if not rule:
        raise HTTPException(404, "Правило не найдено")
    from . import main
    await db.delete(rule)
    await main.audit(db, "automation.rule.deleted", admin.email, str(rule_id))
    await db.commit()
    return {"ok": True}


@router.delete("/api/admin/automation/campaigns/{campaign_id}")
async def delete_campaign(campaign_id: int, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("manage_marketing"))):
    c = await db.get(Campaign, campaign_id)
    if not c:
        raise HTTPException(404, "Кампания не найдена")
    if c.status == "running":
        raise HTTPException(409, "Кампания уже отправляется")
    from . import main
    await db.delete(c)
    await main.audit(db, "campaign.deleted", admin.email, str(campaign_id))
    await db.commit()
    return {"ok": True}


def validate_campaign(payload: dict) -> None:
    content = payload.get("content") or {}
    if payload.get("status") in {"scheduled", "running"} and not str(content.get("text") or "").strip():
        raise HTTPException(400, "Добавьте текст сообщения перед запуском")
    if len(str(content.get("text") or "")) > 4096:
        raise HTTPException(400, "Текст длиннее 4096 символов")
    if bool(content.get("button_text")) != bool(content.get("button_url")):
        raise HTTPException(400, "Текст и адрес кнопки задаются вместе")
    segment = (payload.get("audience") or {}).get("segment") or (payload.get("audience") or {}).get("type") or "all"
    if segment not in SEGMENTS:
        raise HTTPException(400, "Неизвестная аудитория")
