"""v28.54 «Регионы на карте» (GeoLite2): the region inside the country for the customers map.

The country of an address comes from the registry (RIPEstat, vpn_sessions.py); a region needs a GeoIP database. With
a free MaxMind account the owner enters the account ID and the licence key (``geoip.config``, the key is stored
encrypted); the shop downloads GeoLite2-City once a week into ``GEOIP_DIR`` (``/data/geoip``) and reads it with
``maxminddb``. Without a key everything works as before: no regions.

New sessions get ``vpn_sessions.region``; «География клиентов» shows the regions of each country. Admin: «Аналитика →
География → Регионы» (key, «Обновить базу») and the mobile card. Licence: GeoLite2 data by MaxMind, CC BY-SA 4.0 —
the admin page shows the attribution.
"""
from __future__ import annotations

import asyncio
import io
import logging
import os
import tarfile
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import require_permission

logger = logging.getLogger("vpnshop.geoip")
router = APIRouter()
CONFIG_KEY = "geoip.config"
DEFAULT = {"account_id": "", "license_key": "", "updated_at": None, "error": None}
URL = "https://download.maxmind.com/geoip/databases/GeoLite2-City/download?suffix=tar.gz"
NAME = "GeoLite2-City.mmdb"
MAX_SIZE = 200 * 1024 * 1024
_reader = {"path": None, "mtime": None, "db": None}


class GeoIpIn(BaseModel):
    account_id: str = Field("", max_length=20, pattern=r"^[0-9]*$")
    license_key: str = Field("", max_length=64)


def folder() -> Path:
    return Path(os.environ.get("GEOIP_DIR", "/data/geoip"))


def database_path() -> Path:
    return folder() / NAME


async def load(db: AsyncSession) -> dict:
    from .node_health import _load
    return {**DEFAULT, **(await _load(db, CONFIG_KEY, DEFAULT) or {})}


def _open():
    path = database_path()
    if not path.exists():
        return None
    mtime = path.stat().st_mtime
    if _reader["db"] is not None and _reader["mtime"] == mtime:
        return _reader["db"]
    try:
        import maxminddb
        _reader.update(path=str(path), mtime=mtime, db=maxminddb.open_database(str(path)))
    except Exception as exc:  # noqa: BLE001 — no package or a broken file: no regions
        logger.warning("GeoLite2 database unavailable: %s", exc)
        _reader.update(path=None, mtime=None, db=None)
    return _reader["db"]


def region(ip: str, lang: str = "ru") -> str:
    """The region (first subdivision) of an address, or an empty string."""
    reader = _open()
    if reader is None or not ip:
        return ""
    try:
        data = reader.get(ip) or {}
    except Exception:  # noqa: BLE001 — not an address the database knows
        return ""
    subs = data.get("subdivisions") or []
    if not subs:
        return ""
    names = subs[0].get("names") or {}
    return str(names.get(lang) or names.get("en") or "")[:64]


def extract(archive: bytes) -> bytes:
    """The .mmdb file from MaxMind's tar.gz."""
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        for member in tar.getmembers():
            if member.isfile() and member.name.endswith(NAME) and member.size <= MAX_SIZE:
                handle = tar.extractfile(member)
                if handle:
                    return handle.read()
    raise ValueError("В архиве нет GeoLite2-City.mmdb")


async def update(db: AsyncSession, fetch=None) -> dict:
    """Download the database now (needs the account ID and the key)."""
    from .node_health import _save
    from .security import decrypt_secret
    cfg = await load(db)
    if not cfg["account_id"] or not cfg["license_key"]:
        raise HTTPException(409, "Укажите ID аккаунта MaxMind и лицензионный ключ")
    key = decrypt_secret(cfg["license_key"])
    try:
        if fetch is None:
            import httpx
            async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
                r = await client.get(URL, auth=(cfg["account_id"], key))
                if r.status_code in (401, 403):
                    raise ValueError("MaxMind не принял ID аккаунта или ключ")
                r.raise_for_status()
                archive = r.content
        else:
            archive = await fetch(cfg["account_id"], key)
        data = extract(archive)
        folder().mkdir(parents=True, exist_ok=True)
        tmp = database_path().with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(database_path())
        cfg.update(updated_at=datetime.utcnow().isoformat(), error=None)
    except Exception as exc:  # noqa: BLE001 — keep the previous database
        cfg["error"] = str(exc)[:200]
        await _save(db, CONFIG_KEY, cfg)
        await db.commit()
        raise HTTPException(502, f"Не удалось обновить базу: {cfg['error']}") from exc
    await _save(db, CONFIG_KEY, cfg)
    await db.commit()
    return status(cfg)


def status(cfg: dict) -> dict:
    path = database_path()
    return {"account_id": cfg.get("account_id") or "", "key_set": bool(cfg.get("license_key")), "updated_at": cfg.get("updated_at"),
            "error": cfg.get("error"), "database": path.exists(), "size_mb": round(path.stat().st_size / 1024 / 1024, 1) if path.exists() else 0,
            "attribution": "Данные GeoLite2 от MaxMind (CC BY-SA 4.0), https://www.maxmind.com"}


async def _loop():
    from .db import SessionLocal
    from .main import redis_client
    while True:
        await asyncio.sleep(6 * 3600)
        try:
            if redis_client is not None and not await redis_client.set("lock:geoip", "1", nx=True, ex=6 * 3600 - 60):
                continue
            async with SessionLocal() as db:
                cfg = await load(db)
                stamp = cfg.get("updated_at")
                if cfg["license_key"] and (not stamp or datetime.fromisoformat(stamp) < datetime.utcnow() - timedelta(days=7)):
                    await update(db)
        except Exception as exc:  # noqa: BLE001
            logger.warning("GeoLite2 update failed: %s", exc)


def _start():
    from .main import _track_task
    _track_task(_loop())


router.add_event_handler("startup", _start)


@router.get("/api/admin/geoip")
async def get_geoip(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("analytics.read"))):
    return status(await load(db))


@router.put("/api/admin/geoip")
async def put_geoip(payload: GeoIpIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("settings.runtime.write"))):
    from .main import audit
    from .node_health import _save
    from .security import encrypt_secret
    cfg = await load(db)
    cfg["account_id"] = payload.account_id
    if payload.license_key:
        cfg["license_key"] = encrypt_secret(payload.license_key)
    elif not payload.account_id:
        cfg["license_key"] = ""
    await _save(db, CONFIG_KEY, cfg)
    await audit(db, "geoip.config", admin.email, None, {"account_id": payload.account_id, "key_changed": bool(payload.license_key)})
    await db.commit()
    return status(cfg)


@router.post("/api/admin/geoip/update")
async def update_geoip(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("settings.runtime.write"))):
    return await update(db)
