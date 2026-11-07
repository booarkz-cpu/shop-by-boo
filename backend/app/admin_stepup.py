"""Повторное подтверждение опасных действий и свои сессии администратора (v28.75.0, этап 16).

* ``GET  /api/admin/security/step-up`` — действует ли подтверждение этой сессии и чем подтверждать;
* ``POST /api/admin/security/step-up`` — подтвердить: код двухфакторной защиты (если она включена) или пароль.
  Пять неверных попыток за 10 минут — пауза; каждая попытка в журнале действий;
* ``GET  /api/admin/sessions/mine`` и ``DELETE /api/admin/sessions/mine/{id}`` — свои сессии (право ``sessions.self``).

Какие действия требуют подтверждения — ``STEP_UP_ACTIONS`` (их маршруты объявлены через ``require_stepup``)."""
from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .models import AdminSession
from .security import STEPUP_TTL, mark_stepup, require_permission, stepup_fresh, verify_password, verify_totp

logger = logging.getLogger(__name__)
router = APIRouter()
MAX_FAILS = 5
_fails_local: dict[str, list[float]] = {}

# What the panel shows next to the confirmation dialog; tests/test_admin_stepup.py checks the routes.
STEP_UP_ACTIONS = (
    ("POST", "/api/admin/admins", "Новый администратор"),
    ("PUT", "/api/admin/admins/{admin_id}", "Изменение роли или пароля администратора"),
    ("DELETE", "/api/admin/admins/{admin_id}", "Удаление администратора"),
    ("POST", "/api/admin/backups/{backup_id}/restore/approve", "Одобрение восстановления из копии"),
    ("POST", "/api/admin/backups/{backup_id}/restore", "Восстановление из копии"),
    ("DELETE", "/api/admin/backups/{backup_id}", "Удаление резервной копии"),
    ("POST", "/api/admin/refunds/{refund_id}/execute", "Возврат денег"),
    ("POST", "/api/admin/terminal/sessions", "Терминал на ноде"),
    ("POST", "/api/admin/plugins/catalog/install", "Установка плагина"),
    ("POST", "/api/admin/runtime-settings/changes/{change_id}/apply", "Применение настроек и ключей"),
    ("POST", "/api/admin/rw/installations/{installation_id}/approve", "Запуск плана на серверах"),
    ("POST", "/api/admin/rw/installations/{installation_id}/credentials", "Пароль администратора панели Remnawave"),
    ("DELETE", "/api/admin/rw/servers/{server_id}", "Удаление сервера из реестра"),
    ("POST", "/api/admin/rw/servers/{server_id}/rotate-key", "Смена SSH-ключа сервера"),
    ("GET", "/api/admin/remnawave/auto-update/panel-copies/{name}", "Скачивание копии базы панели"),
    ("GET", "/api/admin/install/snapshots/{name}", "Скачивание снимка файлов или базы панели"),
)


class StepUpIn(BaseModel):
    code: str | None = Field(default=None, max_length=12)
    password: str | None = Field(default=None, max_length=256)


def _sid(request: Request) -> int:
    sid = getattr(request.state, "admin_session_id", None)
    if sid is None:
        raise HTTPException(401, "Admin session is not registered")
    return sid


async def _failed(sid: int) -> int:
    from . import main
    key = f"admin:stepup:fail:{sid}"
    client = getattr(main, "redis_client", None)
    if client is not None:
        try:
            n = await client.incr(key)
            if n == 1:
                await client.expire(key, STEPUP_TTL)
            return int(n)
        except Exception as exc:  # noqa: BLE001 — fall back to the process
            logger.warning("step-up failures counted in the process: %s", type(exc).__name__)
    now = datetime.utcnow().timestamp()
    recent = [t for t in _fails_local.get(key, []) if now - t < STEPUP_TTL] + [now]
    _fails_local[key] = recent
    return len(recent)


async def _fails(sid: int) -> int:
    from . import main
    key = f"admin:stepup:fail:{sid}"
    client = getattr(main, "redis_client", None)
    if client is not None:
        try:
            return int(await client.get(key) or 0)
        except Exception as exc:  # noqa: BLE001
            logger.warning("step-up failures read from the process: %s", type(exc).__name__)
    now = datetime.utcnow().timestamp()
    return len([t for t in _fails_local.get(key, []) if now - t < STEPUP_TTL])


@router.get("/api/admin/security/step-up")
async def step_up_state(request: Request, admin=Depends(require_permission("security.stepup"))):
    left = await stepup_fresh(_sid(request))
    return {"fresh": bool(left), "expires_in": left, "ttl": STEPUP_TTL, "method": "totp" if admin.mfa_enabled else "password",
            "actions": [{"method": m, "path": p, "title": t} for m, p, t in STEP_UP_ACTIONS]}


@router.post("/api/admin/security/step-up")
async def step_up(payload: StepUpIn, request: Request, db: AsyncSession = Depends(get_db),
                  admin=Depends(require_permission("security.stepup"))):
    from .main import audit
    sid = _sid(request)
    if await _fails(sid) >= MAX_FAILS:
        raise HTTPException(429, "Слишком много неверных попыток: подождите 10 минут")
    if admin.mfa_enabled:
        ok = bool(payload.code) and verify_totp(admin, payload.code.strip())
    else:
        ok = bool(payload.password) and verify_password(payload.password, admin.password_hash)
    if not ok:
        n = await _failed(sid)
        await audit(db, "security.stepup.failed", admin.email, str(sid), {"attempt": n})
        await db.commit()
        raise HTTPException(401, "Неверный код" if admin.mfa_enabled else "Неверный пароль")
    await mark_stepup(sid)
    await audit(db, "security.stepup.confirmed", admin.email, str(sid), {"ttl": STEPUP_TTL})
    await db.commit()
    return {"fresh": True, "expires_in": STEPUP_TTL}


@router.get("/api/admin/sessions/mine")
async def my_sessions(request: Request, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("sessions.self"))):
    current = getattr(request.state, "admin_session_id", None)
    rows = (await db.execute(select(AdminSession).where(AdminSession.admin_id == admin.id, AdminSession.revoked_at.is_(None),
                                                        AdminSession.expires_at > datetime.utcnow())
                             .order_by(AdminSession.last_seen_at.desc()).limit(50))).scalars().all()
    return [{"id": s.id, "ip": s.ip, "user_agent": s.user_agent, "created_at": s.created_at, "last_seen_at": s.last_seen_at,
             "expires_at": s.expires_at, "current": s.id == current} for s in rows]


@router.delete("/api/admin/sessions/mine/{session_id}")
async def revoke_my_session(session_id: int, db: AsyncSession = Depends(get_db),
                            admin=Depends(require_permission("sessions.self"))):
    from .main import audit
    row = await db.get(AdminSession, session_id)
    if not row or row.admin_id != admin.id:
        raise HTTPException(404, "Session not found")
    row.revoked_at = datetime.utcnow()
    await audit(db, "security.session.revoked_own", admin.email, str(session_id))
    await db.commit()
    return {"ok": True}


# ---------- «История безопасности» ----------

SECURITY_ACTIONS = ("admin.login", "admin.login.failed", "admin.telegram_login", "admin.web_ticket.redeemed", "admin.created",
                    "admin.updated", "admin.deleted", "mfa.enabled", "mfa.disabled", "passkey.deleted")
SECURITY_PREFIXES = ("security.", "terminal.session.", "rw.panel_copy.", "auto_update.", "rw.autoupdate.settings", "rw.server.")
TITLES = {"admin.login": "Вход в панель", "admin.login.failed": "Неудачный вход", "admin.telegram_login": "Вход через Telegram",
          "admin.web_ticket.redeemed": "Вход по ссылке из бота", "admin.created": "Новый администратор",
          "admin.updated": "Изменён администратор", "admin.deleted": "Удалён администратор", "mfa.enabled": "Включена 2FA",
          "mfa.disabled": "Выключена 2FA", "passkey.deleted": "Удалён ключ доступа",
          "security.stepup.confirmed": "Подтверждено опасное действие", "security.stepup.failed": "Неверное подтверждение",
          "security.session.revoked": "Завершена сессия", "security.session.revoked_own": "Завершена своя сессия",
          "security.sessions.revoked_all": "Завершены все сессии", "security.incident_mode": "Режим инцидента",
          "terminal.session.request": "Открыт терминал ноды", "terminal.session.close": "Закрыт терминал ноды",
          "rw.panel_copy.downloaded": "Скачана копия базы панели", "rw.server.key_rotated": "Сменён SSH-ключ сервера",
          "rw.server.created": "Сервер добавлен в реестр", "rw.server.updated": "Изменён сервер реестра",
          "rw.server.deleted": "Сервер удалён из реестра"}
WARN = {"admin.login.failed", "security.stepup.failed", "mfa.disabled", "admin.deleted", "security.incident_mode",
        "rw.panel_copy.downloaded"}


@router.get("/api/admin/security/history")
async def security_history(days: int = 30, actor: str | None = None, db: AsyncSession = Depends(get_db),
                           admin=Depends(require_permission("sessions.manage"))):
    """Входы, неудачные попытки, подтверждения опасных действий, роли, 2FA, сессии, терминал — из журнала действий."""
    from datetime import timedelta

    from sqlalchemy import func, or_

    from .models import AuditLog
    days = max(1, min(days, 365))
    since = datetime.utcnow() - timedelta(days=days)
    cond = or_(AuditLog.action.in_(SECURITY_ACTIONS), *[AuditLog.action.like(p + "%") for p in SECURITY_PREFIXES])
    q = select(AuditLog).where(AuditLog.created_at >= since, cond)
    if actor:
        q = q.where(AuditLog.actor == actor[:320])
    rows = (await db.execute(q.order_by(AuditLog.id.desc()).limit(500))).scalars().all()
    day = datetime.utcnow() - timedelta(days=1)
    failed_24h = int(await db.scalar(select(func.count()).select_from(AuditLog).where(
        AuditLog.action == "admin.login.failed", AuditLog.created_at >= day)) or 0)
    ips = {r.target for r in rows if r.action == "admin.login.failed" and r.created_at >= day and r.target}
    return {"days": days, "summary": {"failed_logins_24h": failed_24h, "failed_login_ips_24h": len(ips),
                                      "logins": sum(r.action in ("admin.login", "admin.telegram_login", "admin.web_ticket.redeemed") for r in rows),
                                      "step_ups": sum(r.action == "security.stepup.confirmed" for r in rows)},
            "events": [{"id": r.id, "at": r.created_at, "action": r.action, "title": TITLES.get(r.action, r.action), "actor": r.actor,
                        "target": r.target, "details": r.details, "level": "warn" if r.action in WARN else "info"} for r in rows]}
