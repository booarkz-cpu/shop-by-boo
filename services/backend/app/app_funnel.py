"""Product funnel of the apps: installation → sign-in → plan → payment → connection.

Counted per installation that was installed inside the period (a cohort), and in order: an
installation reaches a step only after it reached the previous one, so «drop-off» is exactly the
share that stopped there. The payment step reads the shop's own payments (paid or fulfilled) of the
account that signed in on that installation; the app cannot fake it. Times are medians from the
installation, so the administrator sees not only where customers leave but how long each step takes.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from statistics import median

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import AppEvent, Payment

STEPS = (
    ("install", "Установка"),
    ("sign_in", "Вход"),
    ("plan", "Выбрали тариф"),
    ("paid", "Оплатили"),
    ("connected", "Подключились"),
)
PLAN_EVENTS = ("plan_select", "checkout_start")
PAID = ("paid", "fulfilled")
COHORT_LIMIT = 200_000


async def funnel(db: AsyncSession, days: int, platform: str = "", now: datetime | None = None) -> dict:
    now = now or datetime.utcnow()
    since = now - timedelta(days=days)
    cohort_q = select(AppEvent.install_hash, AppEvent.created_at).where(AppEvent.event == "install", AppEvent.created_at >= since)
    if platform:
        cohort_q = cohort_q.where(AppEvent.platform == platform)
    installed = dict((await db.execute(cohort_q.limit(COHORT_LIMIT))).all())
    reached: dict[str, list[float]] = {key: [] for key, _ in STEPS}
    if installed:
        events: dict[str, list[tuple[datetime, str, int | None]]] = {h: [] for h in installed}
        hashes = list(installed)
        for start in range(0, len(hashes), 1000):
            chunk = hashes[start:start + 1000]
            rows = (await db.execute(select(AppEvent.install_hash, AppEvent.created_at, AppEvent.event, AppEvent.user_id)
                                     .where(AppEvent.install_hash.in_(chunk), AppEvent.created_at >= since,
                                            AppEvent.event.in_(("sign_in", "connected", *PLAN_EVENTS)))
                                     .order_by(AppEvent.created_at))).all()
            for h, at, event, user_id in rows:
                events[h].append((at, event, user_id))
        users = {u for rows in events.values() for _, _, u in rows if u}
        first_paid: dict[int, list[datetime]] = {}
        user_list = sorted(users)
        for start in range(0, len(user_list), 1000):
            for user_id, at in (await db.execute(select(Payment.user_id, Payment.paid_at).where(
                    Payment.user_id.in_(user_list[start:start + 1000]), Payment.status.in_(PAID),
                    Payment.paid_at.is_not(None), Payment.paid_at >= since))).all():
                first_paid.setdefault(user_id, []).append(at)
        for h, t0 in installed.items():
            reached["install"].append(0.0)
            rows = events[h]
            t1 = next((at for at, e, _ in rows if e == "sign_in" and at >= t0), None)
            if t1 is None:
                continue
            reached["sign_in"].append((t1 - t0).total_seconds())
            t2 = next((at for at, e, _ in rows if e in PLAN_EVENTS and at >= t1), None)
            if t2 is None:
                continue
            reached["plan"].append((t2 - t0).total_seconds())
            accounts = {u for at, _, u in rows if u and at >= t1}
            t3 = min((at for u in accounts for at in first_paid.get(u, []) if at >= t2), default=None)
            if t3 is None:
                continue
            reached["paid"].append((t3 - t0).total_seconds())
            t4 = next((at for at, e, _ in rows if e == "connected" and at >= t3), None)
            if t4 is not None:
                reached["connected"].append((t4 - t0).total_seconds())
    total = len(reached["install"])
    steps, previous = [], None
    for key, title in STEPS:
        count = len(reached[key])
        step = {"step": key, "title": title, "count": count,
                "of_installs": round(count * 100 / total, 1) if total else 0.0,
                "from_previous": round(count * 100 / previous, 1) if previous else (100.0 if count else 0.0),
                "median_minutes": round(median(reached[key]) / 60, 1) if count and key != "install" else None}
        step["drop_off"] = round(100 - step["from_previous"], 1) if previous else 0.0
        steps.append(step)
        previous = count
    worst = max(steps[1:], key=lambda s: s["drop_off"]) if total else None  # ties: the earliest step
    return {"cohort": total, "steps": steps, "biggest_drop": worst["step"] if worst and worst["drop_off"] > 0 else None,
            "truncated": total >= COHORT_LIMIT}
