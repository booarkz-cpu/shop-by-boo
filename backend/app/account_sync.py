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
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .sub_proxy import client_url
from .db import get_db

router = APIRouter()
logger = logging.getLogger("vpnshop.account_sync")

MAX_WAIT = 25
POLL_SECONDS = 3.0      # without Redis: how often a waiting request re-reads the database
RECHECK_SECONDS = 15.0  # with Redis: safety re-read even if no change notice arrived
CHANNEL = "sync:user:"

# ---------------------------------------------------------------- change notices
# Every committed change of a customer's User, Subscription or Payment row publishes «sync:user:<id>» in Redis
# (SQLAlchemy session events, so no code path can forget it). One listener per process wakes the requests that
# wait for that customer; a waiting request therefore reads the database once per real change, not every 3 s.

_waiters: dict[int, set[asyncio.Event]] = {}
_listener: asyncio.Task | None = None


def _touched_users(session) -> set[int]:
    from .models import Payment, Subscription, User
    ids: set[int] = set()
    for obj in list(session.new) + list(session.dirty) + list(session.deleted):
        if isinstance(obj, User) and obj.id:
            ids.add(obj.id)
        elif isinstance(obj, (Subscription, Payment)) and getattr(obj, "user_id", None):
            ids.add(obj.user_id)
    return ids


def _install_session_hooks() -> None:
    from sqlalchemy import event
    from sqlalchemy.orm import Session

    @event.listens_for(Session, "before_flush")
    def _collect(session, flush_context, instances):  # noqa: ANN001
        session.info.setdefault("sync_users", set()).update(_touched_users(session))

    @event.listens_for(Session, "after_commit")
    def _publish(session):  # noqa: ANN001
        users = session.info.pop("sync_users", set())
        if users:
            notify(users)

    @event.listens_for(Session, "after_rollback")
    def _forget(session):  # noqa: ANN001
        session.info.pop("sync_users", None)


def notify(user_ids) -> None:
    """Wake local waiters now and tell the other processes through Redis (best effort)."""
    from . import main
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    for uid in user_ids:
        for waiter in list(_waiters.get(uid, ())):
            # On the next loop turn: the committing session finishes its commit before anyone reads again.
            loop.call_soon(waiter.set)
    redis = main.redis_client
    if redis is None or not hasattr(redis, "publish"):
        return
    for uid in user_ids:
        loop.create_task(_publish_safely(redis, uid))


async def _publish_safely(redis, uid: int) -> None:
    try:
        await redis.publish(f"{CHANNEL}{uid}", "1")
    except Exception as exc:  # noqa: BLE001 — a lost notice only delays the update to the next re-read
        logger.debug("Sync notice not published: %s", exc)


async def _listen() -> None:
    from . import main
    while True:
        try:
            pubsub = main.redis_client.pubsub()
            await pubsub.psubscribe(f"{CHANNEL}*")
            async for message in pubsub.listen():
                if message.get("type") != "pmessage":
                    continue
                try:
                    uid = int(str(message.get("channel")).rsplit(":", 1)[1])
                except (ValueError, IndexError):
                    continue
                for waiter in list(_waiters.get(uid, ())):
                    waiter.set()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — Redis restarts: listen again
            await asyncio.sleep(2)


def _redis_ready() -> bool:
    from . import main
    global _listener
    redis = main.redis_client
    if redis is None or not hasattr(redis, "pubsub"):
        return False
    if _listener is None or _listener.done():
        _listener = asyncio.get_running_loop().create_task(_listen())
    return True


def _subscribe(user_id: int) -> asyncio.Event:
    """Register a waiter before the state is read, so a commit between the read and the wait still wakes it."""
    event = asyncio.Event()
    _waiters.setdefault(user_id, set()).add(event)
    return event


def _unsubscribe(user_id: int, event: asyncio.Event) -> None:
    _waiters.get(user_id, set()).discard(event)
    if not _waiters.get(user_id):
        _waiters.pop(user_id, None)


async def _wait_for_change(user_id: int, timeout: float, event: asyncio.Event | None = None) -> None:
    own = event is None
    event = event or _subscribe(user_id)
    try:
        await asyncio.wait_for(event.wait(), timeout)
    except asyncio.TimeoutError:
        logger.debug("No change for user %s within %.0f s", user_id, timeout)
    finally:
        if own:
            _unsubscribe(user_id, event)


_install_session_hooks()
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
        url = (client_url(sub.subscription_url) or "").strip()
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
        # Subscribed before reading: a change committed while the state is read wakes the wait below at once.
        event = _subscribe(user_id)
        try:
            state = await account_state(db, user_id)
            version = state_version(state)
            # The connection goes back to the pool while the client waits.
            await db.rollback()
            left = deadline - asyncio.get_running_loop().time()
            if version != since or left <= 0:
                break
            if _redis_ready():
                await _wait_for_change(user_id, min(left, RECHECK_SECONDS), event)
            else:
                await _wait_for_change(user_id, min(left, POLL_SECONDS), event)
        finally:
            _unsubscribe(user_id, event)
    headers = {"ETag": f'"{version}"', "Cache-Control": "private, no-store"}
    if version == since:
        return Response(status_code=304, headers=headers)
    return Response(content=json.dumps({"version": version, **state}, ensure_ascii=False), media_type="application/json", headers=headers)
