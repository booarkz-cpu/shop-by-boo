"""Личный кабинет: сессии входа и устройства под лимитом подписки (v28.63.0, этап 8).

* ``GET /api/me/sessions`` — входы в кабинет и приложения, отмечен текущий; ``POST /api/me/sessions/{id}/revoke``
  завершает один вход (свой текущий тоже — тогда кабинет попросит войти снова).
* ``GET /api/me/hwid-devices`` — устройства, которые панель Remnawave засчитала в лимит подписки (HWID), и сам лимит;
  ``POST /api/me/hwid-devices/{device_id}/delete`` освобождает место одного устройства,
  ``POST /api/me/hwid-devices/reset`` — всех. ``device_id`` — первые 16 символов SHA-256 от HWID: сам HWID наружу
  не отдаётся и в запросе не принимается, поэтому удалить можно только устройство своей подписки.

Лимит устройств обеспечивает панель Remnawave (``hwidDeviceLimit`` у пользователя, включённый HWID-лимит в панели).
Кабинет только показывает его и управляет списком через API панели 3.x (``/api/hwid/devices``)."""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .models import UserSession

logger = logging.getLogger(__name__)
router = APIRouter()


def device_id(hwid: str) -> str:
    return hashlib.sha256(str(hwid).encode()).hexdigest()[:16]


def _current_jti_hash(request: Request) -> str | None:
    from .main import decode_token
    auth = request.headers.get("Authorization", "")
    token = auth[7:] if auth.startswith("Bearer ") else request.cookies.get("rw_user")
    if not token:
        return None
    try:
        jti = decode_token(token).get("jti")
    except HTTPException:
        return None
    return hashlib.sha256(str(jti).encode()).hexdigest() if jti else None


@router.get("/api/me/sessions")
async def my_sessions(request: Request, db: AsyncSession = Depends(get_db)):
    from .main import user_from_token
    user = await user_from_token(request, db)
    current = _current_jti_hash(request)
    now = datetime.utcnow()
    rows = (await db.execute(select(UserSession).where(UserSession.user_id == user.id)
                             .order_by(UserSession.last_seen_at.desc()).limit(50))).scalars().all()
    return [{"id": x.id, "ip": x.ip, "user_agent": x.user_agent, "created_at": x.created_at, "last_seen_at": x.last_seen_at,
             "expires_at": x.expires_at, "revoked_at": x.revoked_at, "current": x.jti_hash == current,
             "active": x.revoked_at is None and x.expires_at > now} for x in rows]


@router.post("/api/me/sessions/{session_id}/revoke")
async def revoke_session(session_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    from .main import audit, user_from_token
    user = await user_from_token(request, db)
    row = await db.get(UserSession, session_id)
    if not row or row.user_id != user.id:
        raise HTTPException(404, "Сессия не найдена")
    current = row.jti_hash == _current_jti_hash(request)
    if row.revoked_at is None:
        row.revoked_at = datetime.utcnow()
        await audit(db, "auth.user.session.revoked", f"user:{user.id}", str(row.id), {"current": current})
        await db.commit()
    return {"ok": True, "current": current}


async def _remote(db: AsyncSession, user_id: int):
    """The customer's primary subscription and its numeric Remnawave user id (panel 3.x)."""
    from .subscriptions import owned
    sub = await owned(db, user_id)
    if not sub or not sub.remnawave_user_id:
        raise HTTPException(404, "У вас нет подписки с доступом к VPN")
    try:
        return sub, int(str(sub.remnawave_user_id))
    except ValueError:
        raise HTTPException(409, "Подписка ещё не перенесена в Remnawave 3.x: обратитесь в поддержку")


def _panel_error(exc: Exception):
    from .remnawave import RemnawaveNotConfigured
    if isinstance(exc, HTTPException):
        raise exc
    if isinstance(exc, RemnawaveNotConfigured):
        raise HTTPException(503, "Список устройств сейчас недоступен: сервис VPN не подключён")
    logger.warning("Cabinet HWID request failed: %s", exc)
    raise HTTPException(502, "Сервис VPN не ответил. Попробуйте позже")


def _view(device: dict) -> dict:
    return {"id": device_id(device.get("hwid", "")), "platform": device.get("platform"), "os_version": device.get("osVersion"),
            "model": device.get("deviceModel"), "created_at": device.get("createdAt"), "updated_at": device.get("updatedAt")}


@router.get("/api/me/hwid-devices")
async def my_hwid_devices(request: Request, db: AsyncSession = Depends(get_db)):
    from .main import RemnawaveClient, user_from_token
    from .subscriptions import owned
    user = await user_from_token(request, db)
    if not await owned(db, user.id):
        return {"subscription": False, "limit": None, "used": 0, "devices": []}
    sub, remote = await _remote(db, user.id)
    try:
        panel = RemnawaveClient()
        devices = await panel.hwid_devices(remote)
        limit = (await panel.get_user(remote)).get("hwidDeviceLimit")
    except Exception as exc:  # noqa: BLE001 — mapped to 503/502 without the panel's answer
        _panel_error(exc)
    if limit is None:
        limit = sub.device_limit_snapshot
    return {"subscription": True, "limit": limit, "used": len(devices), "devices": [_view(d) for d in devices]}


@router.post("/api/me/hwid-devices/{dev}/delete")
async def delete_my_hwid_device(dev: str, request: Request, db: AsyncSession = Depends(get_db)):
    from .main import RemnawaveClient, audit, user_from_token
    user = await user_from_token(request, db)
    _sub, remote = await _remote(db, user.id)
    try:
        panel = RemnawaveClient()
        match = next((d for d in await panel.hwid_devices(remote) if device_id(d.get("hwid", "")) == dev), None)
        if not match:
            raise HTTPException(404, "Устройство не найдено")
        await panel.delete_hwid_device(remote, match["hwid"])
    except Exception as exc:  # noqa: BLE001
        _panel_error(exc)
    await audit(db, "cabinet.hwid_device.deleted", f"user:{user.id}", dev, {"platform": match.get("platform")})
    await db.commit()
    return {"ok": True}


@router.post("/api/me/hwid-devices/reset")
async def reset_my_hwid_devices(request: Request, db: AsyncSession = Depends(get_db)):
    from .main import RemnawaveClient, audit, user_from_token
    user = await user_from_token(request, db)
    _sub, remote = await _remote(db, user.id)
    try:
        await RemnawaveClient().reset_hwid_devices(remote)
    except Exception as exc:  # noqa: BLE001
        _panel_error(exc)
    await audit(db, "cabinet.hwid_devices.reset", f"user:{user.id}", str(remote))
    await db.commit()
    return {"ok": True}
