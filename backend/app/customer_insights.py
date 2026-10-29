"""Customer insights: «Моя статистика» and one-click upsell offers.

``GET /api/me/stats`` — with the shop since, days of VPN paid, traffic used in the current period and in total, the
limit, devices against the limit, next renewal, referral earnings and how many times the apps found a working server
when another one was blocked («переключений на рабочий сервер»).

``GET /api/me/upsell`` — offers that fit the customer right now, each with the parameters of the existing
quote/purchase API (``/api/me/subscription/quote``), so the cabinet, Mini App, bot and apps buy it in one tap:

* traffic used ≥ 80 % → the cheapest traffic package that covers the rest of the period;
* devices at the limit → the cheapest plan with more devices;
* a monthly plan renewed twice or more → the longest plan if it is cheaper per day (with the saving).
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db

router = APIRouter()
GB = 1024 ** 3


async def panel_traffic(sub, panel=None) -> tuple[int | None, int | None, int | None]:
    """(used in the period, lifetime used, limit) in bytes from Remnawave; Nones when unknown."""
    if not sub or not sub.remnawave_uuid:
        return None, None, None
    try:
        from .remnawave import RemnawaveClient
        user = await (panel or RemnawaveClient()).get_user(sub.remnawave_uuid)
    except Exception:  # noqa: BLE001 — the stats simply omit traffic
        return None, None, None
    traffic = user.get("userTraffic") or {}
    used = traffic.get("usedTrafficBytes", user.get("usedTrafficBytes"))
    lifetime = traffic.get("lifetimeUsedTrafficBytes", user.get("lifetimeUsedTrafficBytes"))
    limit = user.get("trafficLimitBytes")
    return (int(used) if used is not None else None, int(lifetime) if lifetime is not None else None, int(limit) if limit else None)


async def stats(db: AsyncSession, user, panel=None, now: datetime | None = None) -> dict:
    from .models import ConnectionReport, Payment, Subscription, UserDevice
    now = now or datetime.utcnow()
    sub = await db.scalar(select(Subscription).where(Subscription.user_id == user.id, Subscription.is_primary.is_(True)))
    paid_days = int(await db.scalar(select(func.coalesce(func.sum(Payment.duration_days_snapshot), 0)).where(
        Payment.user_id == user.id, Payment.status.in_(("paid", "fulfilled")), Payment.purpose == "subscription")) or 0)
    devices = int(await db.scalar(select(func.count()).select_from(UserDevice).where(UserDevice.user_id == user.id, UserDevice.revoked_at.is_(None))) or 0)
    switches = int(await db.scalar(select(func.count()).select_from(ConnectionReport).where(
        ConnectionReport.user_id == user.id, ConnectionReport.ok.is_(False))) or 0)
    used, lifetime, limit = await panel_traffic(sub, panel)
    return {"member_since": user.created_at.isoformat() if user.created_at else None,
            "days_with_us": (now - user.created_at).days if user.created_at else 0, "days_paid": paid_days,
            "traffic_used_gb": round(used / GB, 2) if used is not None else None,
            "traffic_lifetime_gb": round(lifetime / GB, 2) if lifetime is not None else None,
            "traffic_limit_gb": round(limit / GB, 1) if limit else None,
            "devices": devices, "device_limit": sub.device_limit_snapshot if sub else None,
            "renews_at": sub.expires_at.isoformat() if sub and sub.expires_at else None, "auto_renew": bool(user.auto_renew_enabled),
            "referral_earned": str(user.referral_balance or 0), "blocked_servers_avoided": switches}


async def upsell(db: AsyncSession, user, panel=None) -> list[dict]:
    from .models import Payment, Plan, Subscription, TrafficPackage, UserDevice
    sub = await db.scalar(select(Subscription).where(Subscription.user_id == user.id, Subscription.is_primary.is_(True)))
    if not sub or not sub.expires_at or sub.expires_at <= datetime.utcnow():
        return []
    offers = []
    used, _lifetime, limit = await panel_traffic(sub, panel)
    if used is not None and limit and used >= 0.8 * limit:
        packages = (await db.execute(select(TrafficPackage).where(TrafficPackage.enabled.is_(True)).order_by(TrafficPackage.price))).scalars().all()
        package = next((p for p in packages if p.plan_id in (None, sub.plan_id)), None)
        if package:
            offers.append({"kind": "traffic", "title": f"+{package.traffic_gb} ГБ трафика", "price": str(package.price),
                           "reason": f"израсходовано {int(used * 100 / limit)} % трафика",
                           "quote": {"kind": "traffic_addon", "package_id": package.id, "subscription_id": sub.id}})
    plans = (await db.execute(select(Plan).where(Plan.enabled.is_(True), Plan.price > 0))).scalars().all()
    current = await db.get(Plan, sub.plan_id)
    devices = int(await db.scalar(select(func.count()).select_from(UserDevice).where(UserDevice.user_id == user.id, UserDevice.revoked_at.is_(None))) or 0)
    limit_devices = sub.device_limit_snapshot or (current.device_limit if current else None)
    if limit_devices and devices >= limit_devices:
        bigger = sorted((p for p in plans if (p.device_limit or 0) > limit_devices), key=lambda p: (p.price / max(1, p.duration_days)))
        if bigger:
            p = bigger[0]
            offers.append({"kind": "devices", "title": f"{p.name}: до {p.device_limit} устройств", "price": str(p.price),
                           "reason": f"подключено {devices} из {limit_devices} устройств",
                           "quote": {"kind": "subscription_change", "plan_id": p.id, "subscription_id": sub.id}})
    renewals = int(await db.scalar(select(func.count()).select_from(Payment).where(
        Payment.user_id == user.id, Payment.status.in_(("paid", "fulfilled")), Payment.purpose == "subscription")) or 0)
    if current and current.duration_days <= 31 and renewals >= 2:
        longest = max((p for p in plans if p.duration_days > current.duration_days and p.device_limit == current.device_limit),
                      key=lambda p: p.duration_days, default=None)
        if longest:
            per_day_now = Decimal(current.price) / current.duration_days
            per_day_long = Decimal(longest.price) / longest.duration_days
            if per_day_long < per_day_now:
                saving = ((per_day_now - per_day_long) * longest.duration_days).quantize(Decimal("1"))
                offers.append({"kind": "longer", "title": f"{longest.name} — выгоднее на {saving} ₽", "price": str(longest.price),
                               "reason": "вы продлеваете каждый месяц",
                               "checkout": {"plan_id": longest.id, "subscription_id": sub.id}})
    return offers


@router.get("/api/me/stats")
async def my_stats(request: Request, db: AsyncSession = Depends(get_db)):
    from .main import user_from_token
    user = await user_from_token(request, db)
    data = await stats(db, user)
    try:  # v28.38: traffic of the last 30 days from the panel statistics (panel_usage.py); best effort
        from .panel_usage import _panel_user, usage
        month = await usage(await _panel_user(db, user.id), 30)
        data["traffic_30d_gb"] = round(month["total_bytes"] / 1024 ** 3, 2)
        data["traffic_peak_day"] = month["peak"]["day"] if month["peak"] and month["peak"]["bytes"] else None
    except Exception:  # noqa: BLE001 — older panels, no subscription yet
        data["traffic_30d_gb"] = None
    # v28.51: the apps show the loyalty level and the freeze controls inside «Моя статистика».
    from .loyalty import current
    from .subscription_freeze import status_for
    from .subscriptions import owned
    data["loyalty"] = await current(db, user.id)
    freeze = await status_for(db, user, await owned(db, user.id))
    data["freeze"] = freeze if freeze["enabled"] else None
    return data


@router.get("/api/me/upsell")
async def my_upsell(request: Request, db: AsyncSession = Depends(get_db)):
    from .main import user_from_token
    return {"offers": await upsell(db, await user_from_token(request, db))}
