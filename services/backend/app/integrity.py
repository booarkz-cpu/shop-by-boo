"""Data integrity report: rows that point at a customer, subscription, payment or plan that is gone (v28.59.0).

Most relations of the shop are kept by the code, not by foreign keys of the database (134 ``*_id``
columns had none at the stage 3 audit). Before such keys can be added, an operator has to know whether
the existing data would pass them. This report counts the orphans of the relations money and access
depend on and shows a few ids of each; it changes nothing.

``GET /api/admin/integrity`` (permission ``ops.diagnostics``), shown in «Аналитика → Запуск и оповещения».
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import require_permission

router = APIRouter()

# (child table, column, parent table, what it means). Identifiers are constants, never input.
RELATIONS: tuple[tuple[str, str, str, str], ...] = (
    ("subscriptions", "user_id", "users", "подписка без клиента"),
    ("subscriptions", "plan_id", "plans", "подписка без тарифа"),
    ("payments", "user_id", "users", "платёж без клиента"),
    ("payments", "subscription_id", "subscriptions", "платёж ссылается на удалённую подписку"),
    ("payments", "plan_id", "plans", "платёж без тарифа"),
    ("financial_ledger", "user_id", "users", "запись журнала денег без клиента"),
    ("financial_ledger", "payment_id", "payments", "запись журнала денег без платежа"),
    ("refund_requests", "payment_id", "payments", "возврат без платежа"),
    ("user_devices", "user_id", "users", "устройство без клиента"),
    ("user_devices", "subscription_id", "subscriptions", "устройство без подписки"),
    ("user_sessions", "user_id", "users", "сессия без клиента"),
    ("trial_grants", "user_id", "users", "пробный период без клиента"),
    ("trial_grants", "subscription_id", "subscriptions", "пробный период без подписки"),
    ("gift_redemptions", "user_id", "users", "погашение подарка без клиента"),
    ("support_tickets", "user_id", "users", "обращение без клиента"),
    ("referral_rewards", "payment_id", "payments", "реферальная награда без платежа"),
)
SAMPLE = 5


async def report(db: AsyncSession) -> dict:
    checks = []
    for child, column, parent, meaning in RELATIONS:
        orphan = (f"FROM {child} c WHERE c.{column} IS NOT NULL "
                  f"AND NOT EXISTS (SELECT 1 FROM {parent} p WHERE p.id = c.{column})")
        count = int(await db.scalar(text(f"SELECT count(*) {orphan}")) or 0)
        sample = [r[0] for r in (await db.execute(text(f"SELECT c.id {orphan} ORDER BY c.id LIMIT {SAMPLE}"))).all()] if count else []
        checks.append({"table": child, "column": column, "references": parent, "meaning": meaning,
                       "orphans": count, "sample_ids": sample})
    return {"ok": all(c["orphans"] == 0 for c in checks), "orphans": sum(c["orphans"] for c in checks), "checks": checks}


@router.get("/api/admin/integrity")
async def integrity(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("ops.diagnostics"))):
    return await report(db)
