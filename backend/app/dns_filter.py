"""v28.54 «Фильтр рекламы и детский режим»: a customer switches ad blocking or a family-safe filter on their subscription.

The filtering itself happens on the nodes: in Remnawave the owner adds an Internal Squad whose config profile routes
``geosite:category-ads-all`` (and, for the children's filter, adult sites too) to a blackhole outbound — the ready
routing rules are in docs/modules/dns_filter_geoip_ripe.md. The shop keeps which filter each subscription has
(``subscriptions.dns_filter``) and puts the panel user into the matching squad instead of the plan's squad; switching
off brings the plan's squad back.

``squads`` maps a plan squad to its filtered twins: ``{"<plan squad uuid or *>": {"ads": "<uuid>", "kids": "<uuid>"}}``.
A reconcile pass every 15 minutes puts the squad back if a renewal or a plan change reset it. A family owner sets the
filter of a member's subscription (children's mode for the kids).

Off until squads are set (``dns_filter.config``). Customers: cabinet, bot (/filter), apps. Admin: «Ноды → Фильтр
рекламы» and the mobile card.
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import require_permission

logger = logging.getLogger("vpnshop.dns_filter")
router = APIRouter()
CONFIG_KEY = "dns_filter.config"
DEFAULT = {"enabled": False, "squads": {}}
MODES = {"ads": "Без рекламы", "kids": "Детский режим"}
LIVE = ("active", "cancel_scheduled")


class FilterConfigIn(BaseModel):
    enabled: bool = False
    squads: dict[str, dict[str, str]] = Field(default_factory=dict)


class FilterIn(BaseModel):
    mode: str = Field("", pattern=r"^(|ads|kids)$")
    subscription_id: int | None = None


async def load(db: AsyncSession) -> dict:
    from .node_health import _load
    return {**DEFAULT, **(await _load(db, CONFIG_KEY, DEFAULT) or {})}


def filter_squad(cfg: dict, plan_squad: str | None, mode: str | None) -> str | None:
    """The squad for ``mode`` next to the plan's squad (``*`` is the default for every plan)."""
    if not mode:
        return None
    squads = cfg.get("squads") or {}
    for key in (plan_squad or "", "*"):
        uuid = (squads.get(key) or {}).get(mode)
        if uuid:
            return uuid
    return None


def modes(cfg: dict, plan_squad: str | None) -> list[str]:
    return [m for m in MODES if filter_squad(cfg, plan_squad, m)] if cfg.get("enabled") else []


def wanted(cfg: dict, sub) -> list[str]:
    squad = filter_squad(cfg, sub.remnawave_profile_id_snapshot, sub.dns_filter) if cfg.get("enabled") else None
    if squad:
        return [squad]
    return [sub.remnawave_profile_id_snapshot] if sub.remnawave_profile_id_snapshot else []


def _panel():
    from .remnawave import RemnawaveClient
    return RemnawaveClient()


async def apply(db: AsyncSession, sub, panel=None, cfg: dict | None = None) -> bool:
    """Put the panel user into the squad the subscription should have now; True when the panel was changed."""
    cfg = cfg or await load(db)
    if not sub.remnawave_uuid or sub.lifecycle_status not in LIVE:
        return False
    panel = panel or _panel()
    target = wanted(cfg, sub)
    remote = await panel.get_user(sub.remnawave_uuid)
    remote = (remote or {}).get("response", remote) if isinstance(remote, dict) else {}
    current = sorted(str(s.get("uuid") if isinstance(s, dict) else s) for s in (remote.get("activeInternalSquads") or []))
    if current == sorted(target):
        return False
    await panel.patch_user(sub.remnawave_uuid, {"activeInternalSquads": target})
    return True


async def set_filter(db: AsyncSession, sub, mode: str, actor: str, panel=None) -> dict:
    from .activity_log import record
    cfg = await load(db)
    if mode and mode not in modes(cfg, sub.remnawave_profile_id_snapshot):
        raise HTTPException(409, "Этот фильтр сейчас недоступен")
    if sub.lifecycle_status not in LIVE:
        raise HTTPException(409, "Фильтр можно включить только на действующей подписке")
    previous = sub.dns_filter
    sub.dns_filter = mode or None
    try:
        await apply(db, sub, panel, cfg)
    except Exception as exc:  # noqa: BLE001 — keep the old choice when the panel did not take the new one
        sub.dns_filter = previous
        logger.warning("filter of subscription %s not applied: %s", sub.id, exc)
        raise HTTPException(502, "Панель не ответила — попробуйте ещё раз") from exc
    record(db, sub.user_id, actor, "subscription.dns_filter", {"subscription_id": sub.id, "mode": mode or "off"})
    await db.commit()
    return {"ok": True, "mode": sub.dns_filter}


async def reconcile(db: AsyncSession, panel=None) -> int:
    """Put filtered squads back after a renewal or a plan change reset them."""
    from .models import Subscription
    cfg = await load(db)
    if not cfg["enabled"]:
        return 0
    panel = panel or _panel()
    rows = (await db.execute(select(Subscription).where(Subscription.dns_filter.is_not(None), Subscription.lifecycle_status.in_(LIVE)).limit(500))).scalars().all()
    fixed = 0
    for sub in rows:
        try:
            fixed += int(await apply(db, sub, panel, cfg))
        except Exception as exc:  # noqa: BLE001 — the next pass retries
            logger.warning("filter reconcile of subscription %s failed: %s", sub.id, exc)
    return fixed


async def view(db: AsyncSession, sub) -> dict:
    cfg = await load(db)
    available = modes(cfg, sub.remnawave_profile_id_snapshot) if sub else []
    return {"enabled": bool(available), "mode": sub.dns_filter if sub else None, "subscription_id": sub.id if sub else None,
            "modes": [{"key": m, "title": MODES[m]} for m in available]}


async def _loop():
    from .db import SessionLocal
    from .main import redis_client
    while True:
        await asyncio.sleep(900)
        try:
            if redis_client is not None and not await redis_client.set("lock:dns_filter", "1", nx=True, ex=880):
                continue
            async with SessionLocal() as db:
                await reconcile(db)
        except Exception as exc:  # noqa: BLE001
            logger.warning("filter pass failed: %s", exc)


def _start():
    from .main import _track_task
    _track_task(_loop())


router.add_event_handler("startup", _start)


@router.get("/api/me/filter")
async def my_filter(request: Request, subscription_id: int | None = None, db: AsyncSession = Depends(get_db)):
    from .main import user_from_token
    from .subscriptions import owned
    user = await user_from_token(request, db)
    return await view(db, await owned(db, user.id, subscription_id))


@router.put("/api/me/filter")
async def put_my_filter(payload: FilterIn, request: Request, db: AsyncSession = Depends(get_db)):
    from .main import user_from_token
    from .subscriptions import is_family_subscription, owned
    user = await user_from_token(request, db)
    sub = await owned(db, user.id, payload.subscription_id, lock=True)
    if not sub:
        raise HTTPException(404, "Подписка не найдена")
    if await is_family_subscription(db, sub.id):
        raise HTTPException(409, "Фильтр семейной подписки включает владелец семьи")
    return await set_filter(db, sub, payload.mode, "customer")


@router.put("/api/me/family/members/{member_id}/filter")
async def put_member_filter(member_id: int, payload: FilterIn, request: Request, db: AsyncSession = Depends(get_db)):
    """The family owner sets the filter of a member's subscription (children's mode)."""
    from .main import user_from_token
    from .models import FamilyGroup, FamilyMember, Subscription
    user = await user_from_token(request, db)
    member = await db.get(FamilyMember, member_id)
    group = await db.get(FamilyGroup, member.group_id) if member else None
    owner_sub = await db.get(Subscription, group.owner_subscription_id) if group else None
    if not member or not owner_sub or owner_sub.user_id != user.id or not member.subscription_id:
        raise HTTPException(404, "Участник не найден")
    sub = await db.get(Subscription, member.subscription_id)
    return await set_filter(db, sub, payload.mode, "family_owner")


@router.get("/api/admin/dns-filter")
async def admin_filter(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("read"))):
    from sqlalchemy import func
    from .models import Subscription
    counts = dict((await db.execute(select(Subscription.dns_filter, func.count()).where(Subscription.dns_filter.is_not(None))
                                    .group_by(Subscription.dns_filter))).all())
    squads = []
    try:
        from .panel_admin import overview
        squads = [{"uuid": s["uuid"], "name": s["name"]} for s in (await overview()).get("squads", [])]
    except Exception as exc:  # noqa: BLE001 — the form still works with typed UUIDs
        logger.info("squads for the filter form unavailable: %s", exc)
    return {"config": await load(db), "modes": MODES, "counts": {k: int(v) for k, v in counts.items()}, "panel_squads": squads}


@router.put("/api/admin/dns-filter")
async def admin_filter_config(payload: FilterConfigIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("manage_plans"))):
    from .main import audit
    from .node_health import _save
    for key, pair in payload.squads.items():
        if set(pair) - set(MODES):
            raise HTTPException(400, f"Неизвестный фильтр у «{key}»")
    await _save(db, CONFIG_KEY, payload.model_dump())
    await audit(db, "dns_filter.config", admin.email, None, payload.model_dump())
    await db.commit()
    return await load(db)
