"""Catalogue of VPN client apps and their latest versions, for the subscription request log.

The proxy reads the app and its version from the User-Agent (``sub_proxy.client_app``); this module keeps a
catalogue — app name, where the latest version comes from (a GitHub repository with releases, or typed in by hand)
and the latest version — and marks requests from older versions as «устарел». The version in a User-Agent is what
the client said about itself, so the mark is a hint for support, not a verdict.

Latest versions are checked by a background task at most once a day per app (GitHub API, public releases only);
the owner can add apps, change the source or type a version. «Серверы → Прослойка подписки → Версии клиентов».
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime, timedelta

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import require_permission

logger = logging.getLogger("vpnshop.client_versions")
router = APIRouter()
CATALOG_KEY = "sub_proxy.clients"
DEFAULT_APPS = [
    {"app": "v2rayNG", "repo": "2dust/v2rayNG"},
    {"app": "Hiddify", "repo": "hiddify/hiddify-app"},
    {"app": "Clash Verge", "repo": "clash-verge-rev/clash-verge-rev"},
    {"app": "FlClash", "repo": "chen08209/FlClash"},
    {"app": "NekoBox", "repo": "MatsuriDayo/NekoBoxForAndroid"},
    {"app": "Karing", "repo": "KaringX/karing"},
    {"app": "sing-box", "repo": "SagerNet/sing-box"},
    {"app": "Throne", "repo": "throneproj/Throne"},
    {"app": "Happ", "repo": ""},
    {"app": "v2RayTun", "repo": ""},
    {"app": "Streisand", "repo": ""},
    {"app": "Shadowrocket", "repo": ""},
]
_cache: dict = {"rows": None, "at": 0.0}


def parse(version: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", version or "")[:4])


async def catalog(db: AsyncSession) -> list[dict]:
    if _cache["rows"] is not None and time.monotonic() - _cache["at"] < 60:
        return _cache["rows"]
    from .backups_api import setting_value
    import json
    raw = await setting_value(db, CATALOG_KEY, "")
    try:
        rows = json.loads(raw) if raw else [dict(x, latest="", checked_at="") for x in DEFAULT_APPS]
    except ValueError:
        rows = [dict(x, latest="", checked_at="") for x in DEFAULT_APPS]
    _cache.update(rows=rows, at=time.monotonic())
    return rows


async def save(db: AsyncSession, rows: list[dict]) -> None:
    import json
    from .backups_api import set_setting
    await set_setting(db, CATALOG_KEY, json.dumps(rows, ensure_ascii=False))
    _cache.update(rows=rows, at=time.monotonic())


async def is_outdated(db: AsyncSession, app: str, version: str) -> bool:
    if not app or not version:
        return False
    row = next((r for r in await catalog(db) if r.get("app", "").lower() == app.lower()), None)
    latest = parse(row.get("latest", "")) if row else ()
    current = parse(version)
    return bool(latest and current and current < latest)


async def latest_release(client: httpx.AsyncClient, repo: str) -> str:
    r = await client.get(f"https://api.github.com/repos/{repo}/releases/latest", headers={"Accept": "application/vnd.github+json"})
    if r.status_code != 200:
        return ""
    tag = str(r.json().get("tag_name") or "")
    m = re.search(r"\d+(?:\.\d+){0,3}", tag)
    return m.group(0) if m else ""


async def refresh(db: AsyncSession, force: bool = False) -> int:
    rows = [dict(r) for r in await catalog(db)]
    updated = 0
    async with httpx.AsyncClient(timeout=15) as client:
        for row in rows:
            if not row.get("repo") or row.get("manual"):
                continue
            checked = row.get("checked_at") or ""
            if not force and checked and datetime.fromisoformat(checked) > datetime.utcnow() - timedelta(days=1):
                continue
            try:
                version = await latest_release(client, row["repo"])
            except httpx.HTTPError as exc:
                logger.info("Latest release of %s is unknown: %s", row["repo"], exc)
                continue
            row["checked_at"] = datetime.utcnow().isoformat(timespec="seconds")
            if version:
                row["latest"] = version
                updated += 1
    await save(db, rows)
    await db.commit()
    return updated


class ClientIn(BaseModel):
    app: str = Field(..., min_length=1, max_length=40)
    repo: str = Field("", max_length=100, pattern=r"^$|^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    latest: str = Field("", max_length=40)
    manual: bool = False


@router.get("/api/admin/sub-proxy/clients")
async def get_clients(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("ops.diagnostics"))):
    return {"clients": await catalog(db)}


@router.put("/api/admin/sub-proxy/clients")
async def put_clients(payload: list[ClientIn], db: AsyncSession = Depends(get_db), admin=Depends(require_permission("settings.runtime.write"))):
    if len(payload) > 100:
        raise HTTPException(422, "Не больше 100 приложений")
    old = {r.get("app"): r for r in await catalog(db)}
    rows = [{**x.model_dump(), "checked_at": old.get(x.app, {}).get("checked_at", "") if not x.manual else ""} for x in payload]
    await save(db, rows)
    await db.commit()
    return {"clients": rows}


@router.post("/api/admin/sub-proxy/clients/refresh")
async def refresh_clients(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("settings.runtime.write"))):
    return {"updated": await refresh(db, force=True), "clients": await catalog(db)}


async def _loop() -> None:
    from .db import SessionLocal
    from .node_health import _load
    await asyncio.sleep(120)
    while True:
        try:
            async with SessionLocal() as db:
                from .sub_proxy import CONFIG_KEY, DEFAULT
                if (await _load(db, CONFIG_KEY, DEFAULT)).get("enabled"):
                    await refresh(db)
        except Exception as exc:  # noqa: BLE001 — tomorrow again
            logger.warning("Client version check failed: %s", exc)
        await asyncio.sleep(6 * 3600)


async def _start() -> None:
    from . import main
    main._track_task(_loop())


router.add_event_handler("startup", _start)
