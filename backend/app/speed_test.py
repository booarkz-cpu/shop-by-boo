"""v28.53 «Проверка скорости»: the apps measure the speed through the current VPN connection and report it.

The app downloads ``mb`` megabytes from ``GET /api/me/speedtest/blob`` (random bytes, at most ``max_mb``, a few runs
per hour per customer) and times three small requests for the response time, then sends ``POST /api/me/speedtest``:
the server (location) it is connected through, whether the VPN was on, the download speed and the ping. No IP
addresses are kept.

The admin gets a quality map of the nodes from real customers (last 7 days): runs, median and slowest quarter of the
speed, median ping; a server whose median is below ``slow_mbps`` (at least ``min_runs`` runs) is flagged and the
owner is told once a day. «Ноды → Скорость у клиентов» and the mobile card. Rows: ``speed_tests`` (kept 30 days).
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta
from statistics import median

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import require_permission

logger = logging.getLogger("vpnshop.speed_test")
router = APIRouter()
CONFIG_KEY = "speedtest.config"
DEFAULT = {"enabled": True, "max_mb": 10, "runs_per_hour": 6, "slow_mbps": 10, "min_runs": 5, "alert": True, "alerted_day": None}
WINDOW = timedelta(days=7)
RETENTION = timedelta(days=30)
CHUNK = 64 * 1024


class SpeedConfigIn(BaseModel):
    enabled: bool = True
    max_mb: int = Field(10, ge=1, le=50)
    runs_per_hour: int = Field(6, ge=1, le=60)
    slow_mbps: float = Field(10, ge=0.5, le=1000)
    min_runs: int = Field(5, ge=1, le=100)
    alert: bool = True


class SpeedIn(BaseModel):
    server: str = Field("auto", min_length=1, max_length=120)
    vpn: bool = True
    download_mbps: float = Field(..., ge=0, le=10000)
    ping_ms: int | None = Field(None, ge=0, le=60000)
    network: str = Field("", max_length=16)
    platform: str = Field("", max_length=16)


async def load(db: AsyncSession) -> dict:
    from .node_health import _load
    return {**DEFAULT, **(await _load(db, CONFIG_KEY, DEFAULT) or {})}


async def _allow(user_id: int, per_hour: int) -> bool:
    from .main import redis_client
    if redis_client is None:
        return True
    key = f"speedtest:{user_id}:{datetime.utcnow():%Y%m%d%H}"
    try:
        count = await redis_client.incr(key)
        await redis_client.expire(key, 3700)
        return int(count) <= per_hour
    except Exception:  # noqa: BLE001 — no limiter without Redis
        return True


def blob(size: int):
    """``size`` random bytes in chunks (not compressible: a proxy cannot make the test look faster)."""
    left = size
    while left > 0:
        n = min(CHUNK, left)
        left -= n
        yield os.urandom(n)


def server_name(value: str) -> str:
    """A location name as the apps show it; anything that looks like an address becomes «node»."""
    value = value.strip()[:120]
    if "://" in value or (value.count(".") >= 3 and any(c.isdigit() for c in value)) or ":" in value:
        return "node"
    return value or "auto"


def quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * q))]


async def quality(db: AsyncSession, now: datetime | None = None, cfg: dict | None = None) -> list[dict]:
    from .models import SpeedTest
    cfg = cfg or await load(db)
    now = now or datetime.utcnow()
    rows = (await db.execute(select(SpeedTest).where(SpeedTest.created_at >= now - WINDOW, SpeedTest.vpn.is_(True)))).scalars().all()
    by: dict[str, list] = {}
    for r in rows:
        by.setdefault(r.server, []).append(r)
    out = []
    for server, items in by.items():
        speeds = [float(r.download_mbps) for r in items]
        pings = [r.ping_ms for r in items if r.ping_ms is not None]
        med = round(median(speeds), 1)
        out.append({"server": server, "runs": len(items), "median_mbps": med, "slow_quarter_mbps": round(quantile(speeds, 0.25), 1),
                    "median_ping_ms": int(median(pings)) if pings else None,
                    "slow": len(items) >= int(cfg["min_runs"]) and med < float(cfg["slow_mbps"]),
                    "platforms": sorted({r.platform for r in items if r.platform})})
    return sorted(out, key=lambda x: (not x["slow"], -x["runs"], x["server"]))


async def alert_pass(db: AsyncSession, now: datetime | None = None, send=None) -> list[str]:
    """Tell the owner about slow servers once a Moscow day; also drop rows older than 30 days."""
    from .models import SpeedTest
    from .node_health import _save
    now = now or datetime.utcnow()
    await db.execute(delete(SpeedTest).where(SpeedTest.created_at < now - RETENTION))
    await db.commit()
    cfg = await load(db)
    day = (now + timedelta(hours=3)).date().isoformat()  # the Moscow day of a naive UTC moment
    if not cfg["alert"] or cfg.get("alerted_day") == day:
        return []
    slow = [q for q in await quality(db, now, cfg) if q["slow"]]
    if not slow:
        return []
    if send is None:
        from .ops_alerts import send
    lines = ["Медленные серверы по замерам клиентов (7 дней)"] + [f"{q['server']}: {q['median_mbps']} Мбит/с, замеров {q['runs']}" for q in slow[:8]]
    lines.append("Раздел: Ноды → Скорость у клиентов")
    await send("\n".join(lines))
    await _save(db, CONFIG_KEY, {**cfg, "alerted_day": day})
    await db.commit()
    return [q["server"] for q in slow]


async def _loop():
    from .db import SessionLocal
    from .main import redis_client
    while True:
        await asyncio.sleep(3600)
        try:
            if redis_client is not None and not await redis_client.set("lock:speedtest", "1", nx=True, ex=3500):
                continue
            async with SessionLocal() as db:
                await alert_pass(db)
        except Exception as exc:  # noqa: BLE001
            logger.warning("speed test pass failed: %s", exc)


def _start():
    from .main import _track_task
    _track_task(_loop())


router.add_event_handler("startup", _start)


@router.get("/api/me/speedtest/blob")
async def speed_blob(request: Request, mb: int = 10, db: AsyncSession = Depends(get_db)):
    from .main import user_from_token
    user = await user_from_token(request, db)
    cfg = await load(db)
    if not cfg["enabled"]:
        raise HTTPException(409, "Проверка скорости выключена")
    if not await _allow(user.id, int(cfg["runs_per_hour"])):
        raise HTTPException(429, "Слишком много проверок — попробуйте через час")
    size = max(1, min(int(mb), int(cfg["max_mb"]))) * 1024 * 1024
    return StreamingResponse(blob(size), media_type="application/octet-stream",
                             headers={"Content-Length": str(size), "Cache-Control": "no-store", "Content-Encoding": "identity"})


@router.get("/api/me/speedtest/ping")
async def speed_ping():
    return {"ok": True}


@router.post("/api/me/speedtest")
async def speed_report(payload: SpeedIn, request: Request, db: AsyncSession = Depends(get_db)):
    from .main import user_from_token
    from .models import SpeedTest
    user = await user_from_token(request, db)
    if not (await load(db))["enabled"]:
        raise HTTPException(409, "Проверка скорости выключена")
    platform = payload.platform or (request.headers.get("X-Shop-Client") or "")[:16]
    db.add(SpeedTest(user_id=user.id, server=server_name(payload.server), vpn=payload.vpn, download_mbps=round(payload.download_mbps, 2),
                     ping_ms=payload.ping_ms, network=payload.network[:16] or None, platform=platform[:16] or None))
    await db.commit()
    return {"ok": True}


@router.get("/api/admin/speedtest")
async def admin_speed(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("ops.diagnostics"))):
    cfg = await load(db)
    return {"config": cfg, "servers": await quality(db, cfg=cfg)}


@router.put("/api/admin/speedtest")
async def admin_speed_config(payload: SpeedConfigIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("ops.diagnostics"))):
    from .main import audit
    from .node_health import _save
    cfg = await load(db)
    await _save(db, CONFIG_KEY, {**cfg, **payload.model_dump()})
    await audit(db, "speedtest.config", admin.email, None, payload.model_dump())
    await db.commit()
    return await load(db)
