"""Traffic of a customer by day and by server, from the panel's statistics (nothing is stored in the shop).

``GET /api/bandwidth-stats/users/{id}?start=YYYY-MM-DD&end=YYYY-MM-DD&topNodesLimit=100`` (Remnawave 3.4, checked
live in CI) answers the days (``categories``), the daily total (``sparklineData``), per-node series and the top
nodes. The customer card in the admin («Трафик» — 7, 30 or 90 days) and «Моя статистика» in the cabinet, Mini App
and apps (``GET /api/me/traffic``) show the bars by day, the total, the average per day, the peak and the share of
each server.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import require_permission

router = APIRouter()


def _num(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def shape(raw: dict) -> dict:
    days = list(raw.get("categories") or [])
    totals = [_num(x) for x in raw.get("sparklineData") or []]
    if len(totals) < len(days):
        totals += [0.0] * (len(days) - len(totals))
    nodes = []
    for n in raw.get("topNodes") or []:
        if isinstance(n, dict):
            nodes.append({"name": str(n.get("name") or n.get("nodeName") or n.get("uuid") or "—")[:80],
                          "country": str(n.get("countryCode") or "")[:2], "bytes": _num(n.get("total") or n.get("totalBytes") or n.get("value"))})
    total = sum(totals)
    if not nodes:
        for s in raw.get("series") or []:
            if isinstance(s, dict):
                nodes.append({"name": str(s.get("name") or "—")[:80], "country": str(s.get("countryCode") or "")[:2],
                              "bytes": sum(_num(x) for x in s.get("data") or [])})
    whole = sum(n["bytes"] for n in nodes) or total or 1
    for n in nodes:
        n["share"] = round(n["bytes"] * 100 / whole, 1)
    peak = max(range(len(totals)), key=lambda i: totals[i]) if totals else None
    return {"days": [{"day": d, "bytes": totals[i] if i < len(totals) else 0} for i, d in enumerate(days)],
            "total_bytes": total, "per_day_bytes": round(total / len(days)) if days else 0,
            "peak": {"day": days[peak], "bytes": totals[peak]} if peak is not None and days else None,
            "nodes": sorted(nodes, key=lambda n: -n["bytes"])}


async def usage(panel_user: str, days: int, panel=None) -> dict:
    if panel is None:
        from .remnawave import RemnawaveClient
        panel = RemnawaveClient()
    days = 7 if days not in (7, 30, 90) else days
    end = datetime.utcnow().date()
    start = end - timedelta(days=days - 1)
    raw = await panel._request("GET", f"/api/bandwidth-stats/users/{panel_user}",
                               params={"start": start.isoformat(), "end": end.isoformat(), "topNodesLimit": 100})
    return {"range_days": days, **shape(raw if isinstance(raw, dict) else {})}


async def _panel_user(db: AsyncSession, user_id: int) -> str:
    from .models import Subscription
    sub = await db.scalar(select(Subscription).where(Subscription.user_id == user_id, Subscription.remnawave_uuid.is_not(None))
                          .order_by(Subscription.is_primary.desc(), Subscription.id.desc()).limit(1))
    if not sub:
        raise HTTPException(404, "Нет подписки в панели")
    return str(sub.remnawave_uuid)


@router.get("/api/admin/users/{user_id}/traffic")
async def admin_traffic(user_id: int, days: int = 30, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("users.read"))):
    return await usage(await _panel_user(db, user_id), days)


@router.get("/api/me/traffic")
async def my_traffic(request: Request, days: int = 30, db: AsyncSession = Depends(get_db)):
    from .main import user_from_token
    user = await user_from_token(request, db)
    data = await usage(await _panel_user(db, user.id), days)
    for n in data["nodes"]:
        n.pop("country", None)
    return data
