"""Журналы контейнеров в браузере (v28.75.0, этап 16).

Контейнер магазина не имеет доступа к Docker на сервере (так задумано). Журнал службы читает агент автообновления
на сервере (``scripts/auto_update.py``, раз в минуту): панель пишет запрос в общий каталог ``.control``, агент
выполняет ``docker compose logs --tail N <служба>`` для службы из закрытого списка, заменяет значения секретов
из ``.env`` на ``***`` и кладёт текст в ``.control/logs/<служба>.txt``.

* ``POST /api/admin/logs/request`` — запросить свежий хвост журнала (право ``ops.diagnostics``);
* ``GET  /api/admin/logs/{service}`` — последний полученный журнал и состояние запроса."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from .auto_update_api import SETUP_HINT, control_dir, read_state
from .db import get_db
from .security import require_permission

router = APIRouter(prefix="/api/admin/logs")
SERVICES = ("backend", "worker", "bot", "caddy", "admin", "cabinet", "miniapp", "db", "redis",
            "support_pro", "support_worker", "mail_receiver")
Service = Literal["backend", "worker", "bot", "caddy", "admin", "cabinet", "miniapp", "db", "redis",
                  "support_pro", "support_worker", "mail_receiver"]
MAX_BYTES = 400_000


class LogsIn(BaseModel):
    service: Service
    lines: int = Field(default=200, ge=10, le=1000)


def _read_json(path) -> dict:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


@router.post("/request")
async def request_logs(payload: LogsIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("ops.diagnostics"))):
    from .main import audit
    folder = control_dir()
    if not (folder.is_dir() and os.access(folder, os.W_OK)):
        raise HTTPException(503, "Агент на сервере не установлен. " + SETUP_HINT)
    mark = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    path = folder / "logs.request.json"
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"service": payload.service, "lines": payload.lines, "mark": mark, "by": admin.email[:320]}) + "\n")
    os.replace(tmp, path)
    await audit(db, "ops.logs.requested", admin.email, payload.service, {"lines": payload.lines})
    await db.commit()
    return {"requested": mark, "service": payload.service, "agent_alive": read_state()["agent_alive"]}


@router.get("/{service}")
async def get_logs(service: Service, admin=Depends(require_permission("ops.diagnostics"))):
    folder = control_dir()
    request = _read_json(folder / "logs.request.json")
    status = _read_json(folder / "logs" / "status.json")
    text = None
    try:
        raw = (folder / "logs" / f"{service}.txt").read_bytes()[-MAX_BYTES:]
        text = raw.decode(errors="replace")
    except OSError:
        pass
    pending = request.get("service") == service and request.get("mark") and request.get("mark") != status.get("mark")
    ready = status.get("service") == service
    return {"service": service, "services": list(SERVICES), "text": text, "pending": bool(pending),
            "at": status.get("at") if ready else None, "lines": status.get("lines") if ready else None,
            "code": status.get("code") if ready else None, "agent_alive": read_state()["agent_alive"], "setup_hint": SETUP_HINT}
