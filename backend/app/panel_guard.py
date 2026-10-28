"""Panel guard: when Remnawave stops answering, the shop goes into maintenance by itself and comes back by itself.

Checked every minute with the node monitor. After ``fail_after`` failed checks in a row the guard turns maintenance
on (customers see the maintenance screen with the corgi instead of payment errors; payments already made are
delivered by the retry queue later) and alerts the owner; after ``recover_after`` good checks it turns maintenance
off again — but only if the guard turned it on: maintenance switched on by hand or by a restore is never lifted.
Off by default; «Запуск и оповещения → Защита при падении панели» and the mobile admin card.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import require_permission

router = APIRouter()
CONFIG_KEY = "panel_guard.config"
STATE_KEY = "panel_guard.state"
DEFAULT = {"enabled": False, "fail_after": 3, "recover_after": 2}


class GuardIn(BaseModel):
    enabled: bool
    fail_after: int = Field(3, ge=1, le=60)
    recover_after: int = Field(2, ge=1, le=60)


async def _load(db, key, default):
    from .node_health import _load as load
    return await load(db, key, default)


async def _save(db, key, value):
    from .node_health import _save as save
    await save(db, key, value)


async def tick(db: AsyncSession, panel_ok: bool, now: datetime | None = None, sender=None) -> dict:
    from .backups_api import set_setting, setting_value
    config = await _load(db, CONFIG_KEY, DEFAULT)
    state = await _load(db, STATE_KEY, {"fails": 0, "oks": 0, "active": False})
    if not config["enabled"] and not state.get("active"):
        return state
    if sender is None:
        from .ops_alerts import send as sender
    now = now or datetime.utcnow()
    state["fails"], state["oks"] = (0, state.get("oks", 0) + 1) if panel_ok else (state.get("fails", 0) + 1, 0)
    if not state.get("active") and config["enabled"] and state["fails"] >= config["fail_after"]:
        if await setting_value(db, "maintenance_mode", "0") != "1":
            await set_setting(db, "maintenance_mode", "1")
            state.update(active=True, since=now.isoformat())
            await sender(f"🚨 Remnawave не отвечает {state['fails']} мин — магазин сам включил техработы. "
                         "Оплаченные заказы выдадутся, когда панель вернётся.")
    elif state.get("active") and state["oks"] >= config["recover_after"]:
        await set_setting(db, "maintenance_mode", "0")
        await sender("✅ Remnawave снова отвечает — техработы сняты автоматически.")
        state.update(active=False, since=None)
    await _save(db, STATE_KEY, state)
    await db.commit()
    return state


@router.get("/api/admin/panel-guard")
async def get_guard(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("ops.diagnostics"))):
    return {"config": await _load(db, CONFIG_KEY, DEFAULT), "state": await _load(db, STATE_KEY, {"fails": 0, "oks": 0, "active": False})}


@router.put("/api/admin/panel-guard")
async def put_guard(payload: GuardIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("settings.runtime.write"))):
    from .main import audit
    await _save(db, CONFIG_KEY, payload.model_dump())
    await audit(db, "panel_guard.config", admin.email, None, payload.model_dump())
    await db.commit()
    return {"ok": True}
