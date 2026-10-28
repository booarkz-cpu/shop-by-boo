"""Traffic usage: who uses how much — top customers by used traffic, totals, share of the limit.

Read from Remnawave (the users stream, ``usedTrafficBytes``/``userTraffic``), matched to shop customers by their
subscriptions, cached for 10 minutes. «Аналитика → Расход трафика» (web) and the mobile admin card.
"""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import require_permission

router = APIRouter()
_cache: dict = {"at": 0.0, "data": None}
GB = 1024 ** 3


def used_bytes(user: dict) -> int:
    traffic = user.get("userTraffic") or {}
    return int(traffic.get("usedTrafficBytes") or user.get("usedTrafficBytes") or 0)


async def collect(panel=None, max_users: int = 50000) -> list[dict]:
    from .remnawave import RemnawaveClient
    panel = panel or RemnawaveClient()
    out, cursor = [], None
    while len(out) < max_users:
        page = await panel.stream_users(cursor=cursor, size=1000)
        users = page.get("users", []) if isinstance(page, dict) else []
        out.extend({"uuid": u.get("uuid"), "username": u.get("username"), "used": used_bytes(u),
                    "limit": int(u.get("trafficLimitBytes") or 0), "status": u.get("status")} for u in users)
        cursor = page.get("nextCursor") or page.get("cursor") if isinstance(page, dict) else None
        if not cursor or not users:
            break
    return out


async def report(db: AsyncSession, panel=None, top: int = 50) -> dict:
    from .models import Subscription
    if _cache["data"] is None or time.monotonic() - _cache["at"] > 600:
        _cache["data"], _cache["at"] = await collect(panel), time.monotonic()
    users = _cache["data"]
    owners = {s.remnawave_uuid: s.user_id for s in (await db.execute(select(Subscription).where(Subscription.remnawave_uuid.is_not(None)))).scalars()}
    ranked = sorted(users, key=lambda u: -u["used"])[:top]
    total = sum(u["used"] for u in users)
    return {"users": len(users), "total_gb": round(total / GB, 1),
            "average_gb": round(total / GB / len(users), 2) if users else 0,
            "near_limit": sum(1 for u in users if u["limit"] and u["used"] >= 0.9 * u["limit"]),
            "top": [{"customer_id": owners.get(u["uuid"]), "panel_user": u["username"], "used_gb": round(u["used"] / GB, 2),
                     "limit_gb": round(u["limit"] / GB, 1) if u["limit"] else None, "status": u["status"]} for u in ranked]}


@router.get("/api/admin/analytics/traffic")
async def traffic(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("analytics.read"))):
    try:
        return await report(db)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Remnawave: {str(exc)[:200]}") from exc
