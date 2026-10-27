"""One account state for every client: bot, Mini App, web cabinet, Android and iOS.

``GET /api/me/sync`` returns the customer's subscriptions, wallet, pending payments and the
public server list together with ``version``, a hash of exactly that state. Clients keep the
last version and ask again with ``?since=<version>``:

* the answer is ``304`` (no body) when nothing changed, so polling costs one cheap query;
* with ``wait=1..25`` the request is held until the state changes or the wait runs out, so
  an open cabinet or app sees a just-paid subscription within seconds, without push.

The version is derived from the data itself rather than bumped by writers, so no code path
(payment, auto-renew, admin edit, bonus days, revoke) can forget to "notify" the clients.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db

router = APIRouter()

MAX_WAIT = 25
POLL_SECONDS = 3.0
PENDING = ("pending", "waiting_for_capture", "created")


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


async def account_state(db: AsyncSession, user_id: int) -> dict:
    from .models import Payment, Subscription, User

    user = await db.scalar(select(User).where(User.id == user_id).execution_options(populate_existing=True))
    subs = (await db.execute(select(Subscription).where(Subscription.user_id == user.id).order_by(Subscription.is_primary.desc(), Subscription.id)
                             .execution_options(populate_existing=True))).scalars().all()
    pending = await db.scalar(select(func.count()).select_from(Payment).where(Payment.user_id == user.id, Payment.status.in_(PENDING))) or 0
    now = datetime.utcnow()
    subscriptions = []
    for sub in subs:
        status = sub.lifecycle_status or "active"
        if status == "active" and sub.expires_at and sub.expires_at <= now:
            status = "expired"
        url = (sub.subscription_url or "").strip()
        subscriptions.append({
            "id": sub.id, "name": sub.name, "primary": bool(sub.is_primary), "plan_id": sub.plan_id, "status": status,
            "expires_at": _iso(sub.expires_at), "device_limit": sub.device_limit_snapshot, "traffic_limit_gb": sub.traffic_limit_gb_snapshot,
            "auto_renew": bool(sub.auto_renew_enabled), "subscription_url": url if url and not any(c in url for c in "\r\n\x00") else None,
        })
    return {
        "subscriptions": subscriptions,
        "active": any(s["status"] in {"active", "cancel_scheduled", "grace"} for s in subscriptions),
        "wallet": {"balance": str(user.wallet_balance or 0), "referral_balance": str(user.referral_balance or 0)},
        "pending_payments": int(pending),
        "servers": await _servers(),
    }


async def _servers() -> list[dict]:
    from .node_health import node_snapshot

    snap = await node_snapshot()
    # users_online changes every minute and would make every poll a "change": it is not synced.
    return [{"name": n.get("name"), "country": n.get("country"), "status": n.get("status")}
            for n in snap.get("nodes", []) if n.get("status") != "disabled"]


def state_version(state: dict) -> str:
    return hashlib.sha256(json.dumps(state, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:20]


@router.get("/api/me/sync")
async def my_sync(request: Request, since: str = "", wait: int = 0, db: AsyncSession = Depends(get_db)):
    from .main import user_from_token

    # Plain id: the loop rolls back between polls, which expires loaded objects.
    user_id = (await user_from_token(request, db)).id
    since = since or (request.headers.get("If-None-Match") or "").strip('"')
    deadline = asyncio.get_running_loop().time() + max(0, min(MAX_WAIT, wait))
    while True:
        state = await account_state(db, user_id)
        version = state_version(state)
        # The connection goes back to the pool while the client waits.
        await db.rollback()
        if version != since or asyncio.get_running_loop().time() >= deadline:
            break
        await asyncio.sleep(POLL_SECONDS)
    headers = {"ETag": f'"{version}"', "Cache-Control": "private, no-store"}
    if version == since:
        return Response(status_code=304, headers=headers)
    return Response(content=json.dumps({"version": version, **state}, ensure_ascii=False), media_type="application/json", headers=headers)
