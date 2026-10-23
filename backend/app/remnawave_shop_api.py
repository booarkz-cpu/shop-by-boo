from __future__ import annotations

from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import get_db
from .models import Plan, Subscription, User
from .remnawave import RemnawaveClient
from .security import require_permission

router = APIRouter(prefix="/api", tags=["corgi-remnawave-shop"])


def _remote_id(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        raise HTTPException(409, "Remnawave user id must be numeric for Panel 3.x")


async def _user_from_token(request: Request, db: AsyncSession) -> User:
    # Reuse the existing cabinet auth implementation without duplicating token logic.
    from .main import user_from_token
    return await user_from_token(request, db)


def _subscription_out(sub: Subscription | None, remote: dict | None = None) -> dict:
    remote = remote or {}
    return {
        "active": bool(sub and sub.lifecycle_status == "active" and (sub.expires_at is None or sub.expires_at > datetime.utcnow())),
        "remnawave_user_id": str(sub.remnawave_uuid) if sub and sub.remnawave_uuid else None,
        "subscription_url": (remote.get("subscriptionUrl") or remote.get("subscription_url") or (sub.subscription_url if sub else None)),
        "expires_at": remote.get("expireAt") or remote.get("expiresAt") or (sub.expires_at.isoformat() if sub and sub.expires_at else None),
        "traffic_limit_gb": sub.traffic_limit_gb_snapshot if sub else None,
        "device_limit": sub.device_limit_snapshot if sub else None,
        "profile_id": sub.remnawave_profile_id_snapshot if sub else None,
        "remote": {
            "id": remote.get("id"),
            "username": remote.get("username"),
            "status": remote.get("status") or remote.get("state"),
        } if remote else None,
    }


@router.get("/me/remnawave/subscription")
async def my_remnawave_subscription(request: Request, db: AsyncSession = Depends(get_db)):
    user = await _user_from_token(request, db)
    sub = (await db.execute(select(Subscription).where(Subscription.user_id == user.id,Subscription.is_primary.is_(True)))).scalar_one_or_none()
    remote = None
    if sub and sub.remnawave_uuid:
        try:
            remote = await RemnawaveClient().get_user(_remote_id(sub.remnawave_uuid))
        except Exception:
            # The local entitlement remains available during a temporary Panel outage.
            remote = None
    return _subscription_out(sub, remote)


@router.post("/me/remnawave/subscription/refresh")
async def refresh_my_remnawave_subscription(request: Request, db: AsyncSession = Depends(get_db)):
    user = await _user_from_token(request, db)
    sub = (await db.execute(select(Subscription).where(Subscription.user_id == user.id,Subscription.is_primary.is_(True)).with_for_update())).scalar_one_or_none()
    if not sub or not sub.remnawave_uuid:
        raise HTTPException(404, "Remnawave subscription is not provisioned yet")
    rw = RemnawaveClient()
    remote_id = _remote_id(sub.remnawave_uuid)
    remote = await rw.get_user(remote_id)
    subscription = await rw.get_subscription(remote_id)
    # The shop ledger is the paid expiry. Copying expireAt from the panel would
    # let a longer remote date postpone revocation of a subscription that was not paid for.
    sub.subscription_url = subscription.get("subscriptionUrl") or subscription.get("subscription_url") or sub.subscription_url
    await db.commit()
    return _subscription_out(sub, {**remote, **subscription})


@router.get("/admin/remnawave/shop")
async def remnawave_shop_overview(admin=Depends(require_permission("read")), db: AsyncSession = Depends(get_db)):
    plans = (await db.execute(select(Plan).where(Plan.enabled.is_(True)).order_by(Plan.id))).scalars().all()
    configured = bool(settings.remnawave_url and settings.remnawave_token)
    return {
        "configured": configured,
        "panel_url": settings.remnawave_url,
        "integration": "server_side_billing_and_subscription_fulfillment",
        "api_generation": "remnawave-3.x-numeric-user-id",
        "plans": [
            {
                "id": p.id,
                "name": p.name,
                "price": str(p.price),
                "duration_days": p.duration_days,
                "traffic_limit_gb": p.traffic_limit_gb,
                "device_limit": p.device_limit,
                "remnawave_profile_id": p.remnawave_profile_id,
                "mapped": bool(p.remnawave_profile_id),
            }
            for p in plans
        ],
    }


@router.post("/admin/remnawave/shop/test")
async def remnawave_shop_test(admin=Depends(require_permission("read"))):
    if not settings.remnawave_url or not settings.remnawave_token:
        raise HTTPException(503, "REMNAWAVE_URL and REMNAWAVE_TOKEN are not configured")
    rw = RemnawaveClient()
    try:
        users = await rw.list_users(start=0, size=1)
        nodes = await rw.list_nodes(start=0, size=1)
        sample = users.get("users", users.get("response", {}).get("users", [])) if isinstance(users, dict) else []
        sample_id = sample[0].get("id") if sample and isinstance(sample[0], dict) else None
        return {
            "ok": True,
            "api_generation": "3.x" if sample_id is None or isinstance(sample_id, int) else "legacy-or-custom",
            "users_endpoint": "ok",
            "nodes_endpoint": "ok",
            "sample_user_id_type": type(sample_id).__name__ if sample_id is not None else None,
        }
    except Exception as exc:
        raise HTTPException(502, f"Remnawave connection failed: {str(exc)[:500]}")


def parse_squads(data) -> list[dict]:
    """Internal Squads from the panel answer: tolerant to the wrapper and field names."""
    body = data.get("response", data) if isinstance(data, dict) else data
    items = body.get("internalSquads", body.get("squads", [])) if isinstance(body, dict) else body
    out = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        uuid = item.get("uuid") or item.get("id")
        if not uuid:
            continue
        info = item.get("info") if isinstance(item.get("info"), dict) else {}
        out.append({
            "uuid": str(uuid),
            "name": str(item.get("name") or uuid)[:120],
            "members": info.get("membersCount", item.get("membersCount")),
            "inbounds": info.get("inboundsCount", item.get("inboundsCount")),
        })
    return out


@router.get("/admin/remnawave/internal-squads")
async def remnawave_internal_squads(admin=Depends(require_permission("read"))):
    """Squads a plan can grant; the plans editor falls back to a typed UUID when this fails."""
    if not settings.remnawave_url or not settings.remnawave_token:
        return {"configured": False, "squads": [], "error": "REMNAWAVE_URL и REMNAWAVE_TOKEN не заданы"}
    try:
        data = await RemnawaveClient().list_internal_squads()
    except Exception as exc:
        return {"configured": True, "squads": [], "error": f"Remnawave не ответил: {type(exc).__name__}"}
    return {"configured": True, "squads": parse_squads(data), "error": None}


@router.post("/admin/remnawave/shop/plan-mapping/validate")
async def validate_plan_mapping(admin=Depends(require_permission("read")), db: AsyncSession = Depends(get_db)):
    plans = (await db.execute(select(Plan).where(Plan.enabled.is_(True)).order_by(Plan.id))).scalars().all()
    missing = [p.id for p in plans if not p.remnawave_profile_id]
    return {
        "ok": not missing,
        "total_plans": len(plans),
        "mapped": len(plans) - len(missing),
        "missing_profile_mapping": missing,
        "note": "Corgi uses Remnawave Internal Squads/Profile IDs as the entitlement mapping. Configure them per plan before enabling paid sales.",
    }
