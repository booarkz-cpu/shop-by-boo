"""Connection quality from the apps: which server works on which mobile carrier / network.

The Android and iOS apps check the servers of the subscription (TCP connect, the same check as diagnostics) when they
start and every 6 hours while open, and send the results anonymously: platform, carrier name, network type (wifi,
cellular), country, server, success and time — no IP addresses, no traffic. ``POST /api/me/connection-reports``.

The shop builds a carrier × server table for the last 7 days: success rate and median time. A pair that fails for
most attempts (≥ 10 attempts, < 70 % success) while the server is up is flagged — usually the carrier blocks it —
and alerts the owner; ``GET /api/me/recommended-server`` gives the apps the best server for their carrier, used by
the «Авто» choice. «Серверы → Качество связи» (web) and the mobile admin card.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from statistics import median

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import require_permission

router = APIRouter()
WINDOW = timedelta(days=7)
RETENTION = timedelta(days=30)
MIN_ATTEMPTS = 10
BAD_RATE = 0.7


class ResultIn(BaseModel):
    server: str = Field(min_length=3, max_length=255)
    ok: bool
    ms: int | None = Field(None, ge=0, le=60000)


class ReportIn(BaseModel):
    platform: str = Field(pattern="^(android|ios)$")
    carrier: str = Field("", max_length=64)
    network: str = Field("", pattern="^(wifi|cellular|ethernet|other|)$")
    country: str = Field("", max_length=2, pattern="^[A-Za-z]{0,2}$")
    results: list[ResultIn] = Field(min_length=1, max_length=12)


def carrier_name(value: str) -> str:
    return " ".join((value or "").split())[:64] or "неизвестно"


async def matrix(db: AsyncSession, now: datetime | None = None) -> list[dict]:
    from .models import ConnectionReport
    now = now or datetime.utcnow()
    rows = (await db.execute(select(ConnectionReport.carrier, ConnectionReport.network, ConnectionReport.server, ConnectionReport.ok,
                                    ConnectionReport.ms).where(ConnectionReport.created_at >= now - WINDOW))).all()
    cells: dict[tuple[str, str], dict] = {}
    for carrier, network, server, ok, ms in rows:
        key = (carrier if network != "wifi" else f"Wi-Fi ({carrier})" if carrier else "Wi-Fi", server)
        cell = cells.setdefault(key, {"carrier": key[0], "server": server, "attempts": 0, "ok": 0, "times": []})
        cell["attempts"] += 1
        cell["ok"] += 1 if ok else 0
        if ok and ms is not None:
            cell["times"].append(ms)
    out = []
    for cell in cells.values():
        rate = cell["ok"] / cell["attempts"]
        out.append({"carrier": cell["carrier"], "server": cell["server"], "attempts": cell["attempts"], "success": round(rate, 3),
                    "median_ms": int(median(cell["times"])) if cell["times"] else None,
                    "flagged": cell["attempts"] >= MIN_ATTEMPTS and rate < BAD_RATE})
    return sorted(out, key=lambda c: (c["carrier"], -c["success"]))


async def problems(db: AsyncSession) -> list[tuple[str, str, str]]:
    return [(f"quality:{c['carrier']}:{c['server']}", f"Сервер {c['server']} плохо работает у «{c['carrier']}»",
             f"Успешных подключений {int(c['success'] * 100)} % из {c['attempts']} за неделю — похоже на блокировку у оператора. "
             "Включите резервный профиль или посоветуйте клиентам другой сервер.") for c in await matrix(db) if c["flagged"]]


@router.post("/api/me/connection-reports")
async def report(payload: ReportIn, request: Request, db: AsyncSession = Depends(get_db)):
    from .main import user_from_token
    from .models import ConnectionReport
    user = await user_from_token(request, db)
    now = datetime.utcnow()
    for r in payload.results:
        db.add(ConnectionReport(user_id=user.id, platform=payload.platform, carrier=carrier_name(payload.carrier),
                                network=payload.network, country=payload.country.upper(), server=r.server, ok=r.ok, ms=r.ms, created_at=now))
    await db.execute(delete(ConnectionReport).where(ConnectionReport.created_at < now - RETENTION))
    await db.commit()
    return {"ok": True}


@router.get("/api/me/recommended-server")
async def recommended(carrier: str = "", network: str = "", db: AsyncSession = Depends(get_db)):
    name = carrier_name(carrier)
    key = name if network != "wifi" else (f"Wi-Fi ({name})" if carrier else "Wi-Fi")
    cells = [c for c in await matrix(db) if c["carrier"] == key and c["attempts"] >= 3]
    if not cells:
        return {"server": None}
    best = max(cells, key=lambda c: (c["success"], -(c["median_ms"] or 99999)))
    return {"server": best["server"], "success": best["success"], "median_ms": best["median_ms"]}


@router.get("/api/admin/connection-quality")
async def admin_quality(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("ops.diagnostics"))):
    cells = await matrix(db)
    carriers = sorted({c["carrier"] for c in cells})
    return {"cells": cells, "carriers": carriers, "flagged": [c for c in cells if c["flagged"]], "window_days": WINDOW.days}
