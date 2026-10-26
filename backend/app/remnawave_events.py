"""Remnawave webhooks: customer notifications, automation triggers and the trial guard.

Remnawave signs every webhook with HMAC-SHA256 of the raw body (key: the panel's
``WEBHOOK_SECRET_HEADER``, here ``REMNAWAVE_WEBHOOK_SECRET``) in ``X-Remnawave-Signature``.
The shop accepts only signed requests, stores each event once (``remnawave_events``),
maps it to the customer by the Remnawave user id/uuid or ``user_<id>`` username and:

* sends the customer a message (in the app and in Telegram, with a button into the Mini
  App) for the events switched on in «Конфигурация Mini App → Уведомления Remnawave»;
* makes the event available to automation rules (``remnawave.*`` events);
* on ``user_hwid_devices.added`` ends a free trial early when the same device already
  used a trial on another account (trial guard).

Panel side: WEBHOOK_ENABLED=true, WEBHOOK_URL=https://api.<domain>/api/webhooks/remnawave,
WEBHOOK_SECRET_HEADER=<the same secret>.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import get_db
from .models import ConnectionObservation, RemnawaveEvent, Subscription, TrialGrant, User

logger = logging.getLogger(__name__)
router = APIRouter()

# webhook event → (notification switch, automation event, title, body, button text, Mini App section)
NOTIFY = {
    "user.bandwidth_usage_threshold_reached": ("traffic_threshold", "remnawave.traffic_threshold", "Трафик заканчивается",
                                               "Использовано {percent} трафика подписки. Докупите трафик, чтобы VPN не остановился.", "Докупить трафик", "subscription"),
    "user.limited": ("limited", "remnawave.limited", "Трафик закончился",
                     "Трафик подписки закончился, VPN приостановлен. Докупите трафик или смените тариф.", "Докупить трафик", "subscription"),
    "user.expired": ("expired", "remnawave.expired", "Подписка закончилась",
                     "Срок подписки закончился. Продлите её, чтобы VPN снова работал.", "Продлить", "plans"),
    "user.first_connected": ("first_connected", "remnawave.first_connected", "VPN подключён",
                             "Первое подключение прошло успешно — VPN работает. Приятного свободного интернета!", "", ""),
    "user.not_connected": ("not_connected", "remnawave.not_connected", "Не получилось подключиться?",
                           "Похоже, VPN ещё ни разу не подключался. Откройте инструкцию — это займёт минуту.", "Инструкция", "connection"),
    "user.expiration": ("expiration", "remnawave.expiration", "Подписка скоро закончится",
                        "Срок подписки подходит к концу. Продлите её заранее.", "Продлить", "plans"),
}
AUTOMATION_EVENTS = {item[1]: item[2] for item in NOTIFY.values()}


def verify(raw: bytes, signature: str) -> bool:
    secret = settings.remnawave_webhook_secret
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.strip().lower())


def _remote_ids(data: dict) -> list[str]:
    user = data.get("user") if isinstance(data.get("user"), dict) else data
    return [str(v) for v in (user.get("id"), user.get("uuid"), user.get("shortUuid")) if v not in (None, "")]


async def _match(db: AsyncSession, data: dict) -> tuple[int | None, Subscription | None, str | None]:
    ids = _remote_ids(data)
    sub = None
    if ids:
        sub = await db.scalar(select(Subscription).where(Subscription.remnawave_uuid.in_(ids)).order_by(Subscription.id.desc()).limit(1))
    if sub:
        return sub.user_id, sub, ids[0]
    user = data.get("user") if isinstance(data.get("user"), dict) else data
    m = re.fullmatch(r"user_(\d+)(?:_sub_(\d+))?", str(user.get("username") or ""))
    if m:
        sub = await db.get(Subscription, int(m.group(2))) if m.group(2) else None
        if sub and sub.user_id != int(m.group(1)):
            sub = None
        return int(m.group(1)), sub, ids[0] if ids else None
    return None, None, ids[0] if ids else None


def _percent(data: dict) -> str:
    user = data.get("user") if isinstance(data.get("user"), dict) else data
    traffic = user.get("userTraffic") if isinstance(user.get("userTraffic"), dict) else user
    try:
        used = float(traffic.get("usedTrafficBytes") or user.get("usedTrafficBytes") or 0)
        limit = float(user.get("trafficLimitBytes") or 0)
        if limit > 0:
            return f"{min(100, round(used * 100 / limit))}%"
    except (TypeError, ValueError):
        logger.debug("Remnawave event has non-numeric traffic fields")
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    return f"{meta.get('thresholdPercent') or meta.get('threshold') or 80}%"


async def send_telegram(chat_id: int, text: str, button: str = "", section: str = "") -> bool:
    """One message with an optional Mini App button; honours 429 retry_after."""
    import asyncio
    import httpx
    if not settings.bot_token or not chat_id:
        return False
    body: dict = {"chat_id": chat_id, "text": text[:4096]}
    base = settings.mini_app_url or ""
    if button and base.startswith("https://"):
        body["reply_markup"] = {"inline_keyboard": [[{"text": button, "web_app": {"url": base.split("#")[0] + (f"#{section}" if section else "")}}]]}
    async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
        for _ in range(3):
            r = await client.post(f"https://api.telegram.org/bot{settings.bot_token}/sendMessage", json=body)
            if r.status_code != 429:
                return r.is_success
            try:
                wait = float(r.json().get("parameters", {}).get("retry_after", 1))
            except Exception:
                wait = 1.0
            await asyncio.sleep(min(max(wait, 0.5), 30))
    return False


async def notify(db: AsyncSession, row: RemnawaveEvent, sender=send_telegram) -> bool:
    from .app_config import load_overrides
    from .main import enqueue_notification
    spec = NOTIFY.get(row.event)
    if not spec or not row.user_id:
        return False
    switch, _, title, body, button, section = spec
    if not getattr((await load_overrides(db)).remnawave_notify, switch):
        return False
    user = await db.get(User, row.user_id)
    if not user or user.deleted_at is not None:
        return False
    text = body.replace("{percent}", _percent(row.data or {}))
    await enqueue_notification(db, user_id=user.id, channel="in_app", kind=f"remnawave_{switch}", title=title, body=text,
                               dedupe_key=f"remnawave:{row.id}")
    row.notified = True
    await db.commit()
    if user.telegram_id:
        try:
            await sender(int(user.telegram_id), f"{title}\n\n{text}", button, section)
        except Exception as exc:  # the in-app notice is already stored
            logger.warning("Remnawave notification %s was not sent to Telegram: %s", row.id, exc)
    return True


# ---------------------------------------------------------------- trial guard

def _hwid(data: dict) -> str:
    for key in ("hwidUserDevice", "device", "hwidDevice"):
        if isinstance(data.get(key), dict) and data[key].get("hwid"):
            return str(data[key]["hwid"])[:128]
    return str(data.get("hwid") or "")[:128]


async def trial_device_check(db: AsyncSession, user_id: int, hwid: str) -> bool:
    """End a running trial if the device already took a trial on another account."""
    from .app_config import load_overrides
    if not hwid or not (await load_overrides(db)).trial.revoke_on_shared_device:
        return False
    db.add(ConnectionObservation(user_id=user_id, ip="0.0.0.0", prefix="webhook", hwid=hwid, seen_at=datetime.utcnow()))
    await db.flush()
    grant = await db.scalar(select(TrialGrant).where(TrialGrant.user_id == user_id, TrialGrant.status.in_(("active", "completed")),
                                                     TrialGrant.expires_at > datetime.utcnow()))
    if not grant:
        await db.commit()
        return False
    others = select(ConnectionObservation.user_id).where(ConnectionObservation.hwid == hwid, ConnectionObservation.user_id != user_id)
    # Only a trial granted BEFORE this one counts: the account that took the first trial on the
    # device keeps it when it connects again after a second account took a trial there.
    earlier = await db.scalar(select(TrialGrant.id).where(TrialGrant.user_id.in_(others), TrialGrant.id < grant.id).limit(1))
    if not earlier:
        await db.commit()
        return False
    await revoke_trial(db, grant, "Пробный период уже использовался на этом устройстве с другого аккаунта")
    return True


async def revoke_trial(db: AsyncSession, grant: TrialGrant, reason: str) -> None:
    from .main import audit, enqueue_notification
    now = datetime.utcnow()
    grant.status = "revoked"
    grant.expires_at = now
    sub = await db.get(Subscription, grant.subscription_id) if grant.subscription_id else None
    # Only a subscription that never had a paid order is ended: payments always win.
    from .models import Payment
    paid = await db.scalar(select(Payment.id).where(Payment.subscription_id == sub.id, Payment.status.in_(("paid", "fulfilled"))).limit(1)) if sub else None
    if sub and not paid and sub.expires_at and sub.expires_at > now:
        sub.expires_at = now
        sub.lifecycle_status = "expired"
        if sub.remnawave_uuid:
            try:
                from .remnawave import RemnawaveClient
                await RemnawaveClient().disable_user(sub.remnawave_uuid)
            except Exception as exc:
                logger.warning("Trial %s: Remnawave disable failed: %s", grant.id, exc)
    await audit(db, "trial.revoked.shared_device", "system", str(grant.id), {"user_id": grant.user_id})
    await enqueue_notification(db, user_id=grant.user_id, channel="in_app", kind="trial_revoked", title="Пробный период завершён",
                               body=reason + ". Выберите тариф, чтобы продолжить.", dedupe_key=f"trial:{grant.id}:revoked")
    await db.commit()


def trial_ip_hash(ip: str) -> str:
    return hmac.new((settings.app_secret or "shop").encode(), f"trial-ip:{ip}".encode(), hashlib.sha256).hexdigest()


async def trial_guard(db: AsyncSession, user: User, ip: str) -> str:
    """Checks before granting a trial; returns the keyed IP hash to store on the grant."""
    from .app_config import load_overrides
    guard = (await load_overrides(db)).trial
    if guard.require_telegram and not user.telegram_id:
        raise HTTPException(409, "Пробный период доступен после входа через Telegram")
    ip_hash = trial_ip_hash(ip or "unknown")
    if guard.max_per_ip_per_day:
        from sqlalchemy import func
        recent = await db.scalar(select(func.count()).select_from(TrialGrant).where(
            TrialGrant.ip_hash == ip_hash, TrialGrant.granted_at >= datetime.utcnow() - timedelta(days=1)))
        if int(recent or 0) >= guard.max_per_ip_per_day:
            raise HTTPException(429, "С этой сети уже взяли пробные периоды сегодня. Попробуйте позже или выберите тариф")
    return ip_hash


# ---------------------------------------------------------------- webhook

@router.post("/api/webhooks/remnawave")
async def remnawave_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    raw = await request.body()
    if len(raw) > 256 * 1024:
        raise HTTPException(413, "Payload too large")
    if not verify(raw, request.headers.get("X-Remnawave-Signature", "")):
        raise HTTPException(403, "Invalid Remnawave signature")
    try:
        body = json.loads(raw)
    except ValueError:
        raise HTTPException(400, "Invalid JSON")
    if not isinstance(body, dict):
        raise HTTPException(400, "Invalid event")
    event, scope = str(body.get("event") or "")[:64], str(body.get("scope") or "")[:32]
    data = body.get("data") if isinstance(body.get("data"), dict) else {}
    if scope not in {"user", "user_hwid_devices"} and not event.startswith(("user.", "user_hwid_devices.")):
        return {"ok": True, "ignored": True}
    user_id, sub, remote_id = await _match(db, data)
    row = RemnawaveEvent(event_key=hashlib.sha256(raw).hexdigest(), scope=scope or event.split(".")[0], event=event, user_id=user_id,
                         subscription_id=sub.id if sub else None, remote_id=remote_id, data=data)
    db.add(row)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return {"ok": True, "duplicate": True}
    if event == "user_hwid_devices.added" and user_id:
        return {"ok": True, "trial_revoked": await trial_device_check(db, user_id, _hwid(data))}
    return {"ok": True, "notified": await notify(db, row)}
