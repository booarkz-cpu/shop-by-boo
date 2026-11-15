"""«Обновления → Автообновление»: управление агентом автообновления из админ-панели.

Backend не выполняет команды на сервере. Он только пишет запрос в каталог, общий с агентом
(`$APP_DIR/.control` на сервере, `/data/control` в контейнере), и читает состояние, которое пишет агент
(scripts/auto_update.py, systemd-таймер раз в минуту):

* `auto-update.request.json` — `{"enabled": bool, "time": "HH:MM", "check_now": "<метка>"}`;
* `auto-update.status.json` — версии, расписание, итог и время последнего запуска, хвост журнала.

Агент принимает только эти три поля и проверяет их формат.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import require_permission

router = APIRouter()
AGENT_FRESH = timedelta(minutes=5)
SETUP_HINT = "На сервере выполните: sudo bash /opt/vpn-shop/scripts/auto-update.sh install"

__all__ = ["router", "control_dir", "read_state", "write_request"]


def control_dir() -> Path:
    return Path(os.environ.get("AUTO_UPDATE_CONTROL_DIR", "/data/control"))


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _parse_time(value) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def read_state(now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    folder = control_dir()
    status = _read(folder / "auto-update.status.json")
    request = _read(folder / "auto-update.request.json")
    seen = _parse_time(status.get("agent_seen_at"))
    agent_alive = bool(seen and now - seen <= AGENT_FRESH)
    writable = folder.is_dir() and os.access(folder, os.W_OK)
    pending = bool(request.get("check_now")) and request.get("check_now") != status.get("handled_check_now")
    return {"available": writable, "agent_alive": agent_alive, "setup_hint": None if (writable and agent_alive) else SETUP_HINT,
            "status": {k: status.get(k) for k in ("enabled", "time", "installed", "latest", "running", "started_at", "last_run_at",
                                                    "last_result", "last_message", "next_run", "trigger", "recovery_mode",
                                                    "failed_release", "log_tail", "agent_seen_at")},
            "request": {k: request.get(k) for k in ("enabled", "time", "check_now", "updated_by", "updated_at")},
            "pending_run": pending}


def write_request(changes: dict, actor: str, now: datetime | None = None) -> dict:
    folder = control_dir()
    if not (folder.is_dir() and os.access(folder, os.W_OK)):
        raise HTTPException(503, "Агент автообновления не установлен. " + SETUP_HINT)
    path = folder / "auto-update.request.json"
    current = _read(path)
    current.update(changes)
    current.update({"updated_by": actor[:320], "updated_at": (now or datetime.now(timezone.utc)).replace(microsecond=0).isoformat()})
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n")
    os.replace(tmp, path)
    return current


class AutoUpdateIn(BaseModel):
    enabled: bool
    time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


@router.get("/api/admin/auto-update")
async def get_auto_update(admin=Depends(require_permission("ops.releases"))):
    return read_state()


@router.put("/api/admin/auto-update")
async def put_auto_update(payload: AutoUpdateIn, db: AsyncSession = Depends(get_db),
                          admin=Depends(require_permission("settings.runtime.write"))):
    from .main import audit

    write_request({"enabled": payload.enabled, "time": payload.time}, admin.email)
    await audit(db, "auto_update.settings", admin.email, None, {"enabled": payload.enabled, "time": payload.time})
    await db.commit()
    return read_state()


@router.post("/api/admin/auto-update/run")
async def run_auto_update(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("settings.runtime.write"))):
    from .main import audit

    state = read_state()
    if state["status"].get("running"):
        raise HTTPException(409, "Обновление уже идёт")
    if state["pending_run"]:
        raise HTTPException(409, "Проверка уже запрошена: агент выполнит её в течение минуты")
    mark = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    if not re.fullmatch(r"[A-Za-z0-9:._-]{1,64}", mark):  # the agent accepts only this format
        raise HTTPException(500, "Bad request mark")
    write_request({"check_now": mark}, admin.email)
    await audit(db, "auto_update.run_requested", admin.email, None, {"mark": mark})
    await db.commit()
    return {**read_state(), "requested": mark}
