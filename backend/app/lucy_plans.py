"""Тарифы Lucy (v28.63.0, этап 8): Lucy Mini — пробный, Lucy Max и Lucy Ultra — платные.

| Тариф | Срок | Устройств | Трафик |
| --- | --- | --- | --- |
| Lucy Mini | пробный период (3 дня) | 1 | лимит задаёт владелец, по умолчанию без лимита |
| Lucy Max | срок владельца (30 дней) | 2 | без лимита |
| Lucy Ultra | тот же срок | 4 | без лимита; цена за устройство ниже, чем у Lucy Max |

Тарифы — обычные строки ``plans``. Ограничения выполняет Remnawave: при выдаче доступа ``device_limit`` уходит в
``hwidDeviceLimit`` пользователя, ``traffic_limit_gb = None`` — в ``trafficLimitBytes = 0`` (без лимита).
Lucy Mini не продаётся (``enabled = False``): он назначается тарифом пробного периода (``app_settings.trial_plan_id``),
и ``POST /api/me/trial`` принимает только его. Пока пробный тариф не назначен, пробный период работает как раньше —
на любом включённом тарифе.

Цены задаёт владелец: магазин их не придумывает. Мастер в «Тарифы» создаёт недостающие тарифы и обновляет
существующие с тем же названием; изменение тарифа не трогает уже выданные подписки (у них свои снимки лимитов)."""
from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .models import AppSetting, Plan
from .security import require_permission

router = APIRouter()
TRIAL_KEY = "trial_plan_id"
MINI, MAX, ULTRA = "Lucy Mini", "Lucy Max", "Lucy Ultra"
DEVICES = {MINI: 1, MAX: 2, ULTRA: 4}


class LucyIn(BaseModel):
    max_price: Decimal = Field(gt=0, le=1000000, decimal_places=2, max_digits=12)
    ultra_price: Decimal = Field(gt=0, le=1000000, decimal_places=2, max_digits=12)
    duration_days: int = Field(default=30, gt=0, le=3650)
    trial_days: int = Field(default=3, ge=1, le=30)
    trial_traffic_gb: int | None = Field(default=None, ge=1, le=100000)
    remnawave_profile_id: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def ultra_is_the_better_deal(self):
        if self.ultra_price / DEVICES[ULTRA] >= self.max_price / DEVICES[MAX]:
            raise ValueError("Lucy Ultra должен быть выгоднее Lucy Max: цена за устройство у Ultra должна быть ниже "
                             f"({self.max_price / DEVICES[MAX]:.2f} за устройство у Max)")
        return self


async def _setting(db: AsyncSession, key: str) -> str:
    row = await db.get(AppSetting, key)
    return row.value if row else ""


async def configured_trial_plan_id(db: AsyncSession) -> int | None:
    value = (await _setting(db, TRIAL_KEY)).strip()
    return int(value) if value.isdigit() else None


async def trial_plan(db: AsyncSession, plan_id: int) -> Plan:
    """The plan a trial may be claimed on. With a trial plan configured only that plan, even though it is not on sale."""
    configured = await configured_trial_plan_id(db)
    plan = await db.get(Plan, plan_id)
    if configured:
        if plan_id != configured or not plan:
            raise HTTPException(400, "Пробный период доступен только на пробном тарифе")
        return plan
    if not plan or not plan.enabled:
        raise HTTPException(404, "Тариф не найден")
    return plan


def trial_days(plan: Plan, requested: int, max_days: int) -> int:
    """Days of a trial: what was asked, within the shop's maximum and, for a trial-only plan, its own length."""
    days = min(requested, max_days)
    return min(days, plan.duration_days) if not plan.enabled else days


def _plan_view(p: Plan | None) -> dict | None:
    if not p:
        return None
    return {"id": p.id, "name": p.name, "price": str(p.price), "duration_days": p.duration_days, "device_limit": p.device_limit,
            "traffic_limit_gb": p.traffic_limit_gb, "enabled": p.enabled, "remnawave_profile_id": p.remnawave_profile_id}


async def _by_name(db: AsyncSession, name: str) -> Plan | None:
    return await db.scalar(select(Plan).where(Plan.name == name).order_by(Plan.id).limit(1))


@router.get("/api/public/trial")
async def public_trial(db: AsyncSession = Depends(get_db)):
    """What the cabinet offers as a free trial: the configured trial plan, or null (then any plan on sale)."""
    plan_id = await configured_trial_plan_id(db)
    plan = await db.get(Plan, plan_id) if plan_id else None
    if not plan:
        return {"plan": None}
    return {"plan": {"id": plan.id, "name": plan.name, "days": plan.duration_days, "device_limit": plan.device_limit,
                     "traffic_limit_gb": plan.traffic_limit_gb}}


@router.get("/api/admin/lucy-plans")
async def lucy_state(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("read"))):
    plans = {name: await _by_name(db, name) for name in (MINI, MAX, ULTRA)}
    trial_id = await configured_trial_plan_id(db)
    return {"plans": {name: _plan_view(p) for name, p in plans.items()}, "trial_plan_id": trial_id,
            "trial_is_mini": bool(plans[MINI] and trial_id == plans[MINI].id)}


@router.post("/api/admin/lucy-plans")
async def lucy_apply(payload: LucyIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("manage_plans"))):
    from .main import audit
    wanted = {
        MINI: dict(price=Decimal("0.00"), duration_days=payload.trial_days, device_limit=1, traffic_limit_gb=payload.trial_traffic_gb, enabled=False),
        MAX: dict(price=payload.max_price, duration_days=payload.duration_days, device_limit=DEVICES[MAX], traffic_limit_gb=None, enabled=True),
        ULTRA: dict(price=payload.ultra_price, duration_days=payload.duration_days, device_limit=DEVICES[ULTRA], traffic_limit_gb=None, enabled=True),
    }
    result = {}
    for name, values in wanted.items():
        plan = await _by_name(db, name)
        result[name] = "updated" if plan else "created"
        if not plan:
            plan = Plan(name=name, family_seats=0, **values)
            db.add(plan)
        else:
            for key, value in values.items():
                setattr(plan, key, value)
        plan.remnawave_profile_id = payload.remnawave_profile_id or plan.remnawave_profile_id
    await db.flush()
    mini = await _by_name(db, MINI)
    row = await db.get(AppSetting, TRIAL_KEY)
    if row:
        row.value = str(mini.id)
    else:
        db.add(AppSetting(key=TRIAL_KEY, value=str(mini.id)))
    await audit(db, "plans.lucy.applied", admin.email, None,
                {"result": result, "max_price": str(payload.max_price), "ultra_price": str(payload.ultra_price),
                 "duration_days": payload.duration_days, "trial_days": payload.trial_days})
    await db.commit()
    return {"result": result, **await lucy_state(db, admin)}


@router.delete("/api/admin/lucy-plans/trial")
async def lucy_trial_off(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("manage_plans"))):
    """Stop restricting the trial to Lucy Mini: the trial works on any plan on sale again."""
    from .main import audit
    row = await db.get(AppSetting, TRIAL_KEY)
    if row:
        await db.delete(row)
        await audit(db, "plans.lucy.trial_off", admin.email, row.value)
        await db.commit()
    return {"ok": True}
