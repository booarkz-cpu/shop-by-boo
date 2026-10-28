"""BitTorrent detection on VPN nodes from the Xray access log.

Xray's sniffing recognises BitTorrent and a routing rule (``"protocol": ["bittorrent"]``)
sends such connections to an outbound with a known tag. The node agent reads the
access log, counts those lines per Xray client (the ``email`` field, which Remnawave
sets to the shop's ``user_<id>`` username) and posts only the counts. The shop:

* keeps hourly counts per client and node for 30 days — no destination addresses,
  ports or log lines are sent or stored;
* raises the abuse score of the client (the ``torrent`` analyzer) for 24 hours after a
  detection; decisions stay with the operator and the existing abuse policy;
* tells the client once a day (in-app and push), when notifications are enabled;
* erases the counts with the account and moves them with an account merge.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Header, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .models import AppSetting, NodeAgent, Subscription, TorrentDetection, User
from .security import require_permission

logger = logging.getLogger("vpnshop.torrent_detection")

RETENTION_DAYS = 30
ABUSE_WINDOW = timedelta(hours=24)
NOTIFY_KEY = "torrent_notify"
# «Событий в час, чтобы считать нарушением» (v28.38, idea from Remnawave Admin): games and an occasional DHT poll give a
# few events; below the threshold a client is counted but never marked in the abuse score nor notified. 1 = as before.
THRESHOLD_KEY = "torrent_min_events"
# Detection kinds: "xray" (Xray routing), the built-in classifier's confirmed signatures,
# "ndpi" (nDPI), and "encrypted" — a heuristic for MSE/PE that is shown as "likely" only:
# it never marks the abuse score and never notifies the customer.
KINDS = ("xray", "bittorrent", "dht", "utp", "tracker", "ndpi", "encrypted")
CONFIRMED = ("xray", "bittorrent", "dht", "utp", "tracker", "ndpi")
UNATTRIBUTED = "-"
CLIENT_NAME = re.compile(r"^user_(\d{1,12})(?:_sub_\d{1,12})?$")


def private(response: Response):
    response.headers["Cache-Control"] = "private, no-store"


router = APIRouter(dependencies=[Depends(private)])


def utcnow() -> datetime:
    return datetime.utcnow()


def hour_of(moment: datetime) -> datetime:
    return moment.replace(minute=0, second=0, microsecond=0)


async def notify_enabled(db: AsyncSession) -> bool:
    row = await db.get(AppSetting, NOTIFY_KEY)
    return row is None or row.value != "0"


async def resolve_user(db: AsyncSession, client: str) -> int | None:
    """Maps an Xray client name to a shop user: ``user_<id>`` usernames first, then a
    subscription's Remnawave UUID (some panels put the UUID in the email field)."""
    match = CLIENT_NAME.match(client)
    if match:
        user_id = int(match.group(1))
        return user_id if await db.get(User, user_id) else None
    sub = await db.scalar(select(Subscription).where(Subscription.remnawave_uuid == client).limit(1))
    return sub.user_id if sub else None


async def min_events(db: AsyncSession) -> int:
    row = await db.get(AppSetting, THRESHOLD_KEY)
    try:
        return max(1, int(row.value)) if row and row.value else 1
    except ValueError:
        return 1


async def recent_users(db: AsyncSession, user_ids: set[int], now: datetime | None = None) -> set[int]:
    """Users with a detection in the abuse window (used by the abuse scoring): at least the threshold in one hour."""
    if not user_ids:
        return set()
    since = hour_of((now or utcnow()) - ABUSE_WINDOW)
    threshold = await min_events(db)
    rows = await db.execute(select(TorrentDetection.user_id, TorrentDetection.hour).where(
        TorrentDetection.user_id.in_(user_ids), TorrentDetection.hour >= since, TorrentDetection.kind.in_(CONFIRMED))
        .group_by(TorrentDetection.user_id, TorrentDetection.hour).having(func.sum(TorrentDetection.events) >= threshold))
    return {r[0] for r in rows.all() if r[0] is not None}


async def _add(db: AsyncSession, hour: datetime, agent_id: int, client: str, user_id: int | None, events: int, kind: str = "xray") -> None:
    for _ in range(3):
        row = await db.scalar(select(TorrentDetection).where(TorrentDetection.hour == hour, TorrentDetection.agent_id == agent_id,
                                                             TorrentDetection.client == client, TorrentDetection.kind == kind).with_for_update())
        if row is not None:
            row.events += events
            row.user_id = row.user_id or user_id
            return
        try:
            async with db.begin_nested():
                db.add(TorrentDetection(hour=hour, agent_id=agent_id, client=client, user_id=user_id, events=events, kind=kind))
            return
        except IntegrityError:
            continue  # another request created the bucket: add to it


async def _notify(db: AsyncSession, user_id: int, now: datetime) -> None:
    from .main import enqueue_notification

    await enqueue_notification(
        db, user_id=user_id, channel="in_app", kind="abuse.torrent",
        title="Замечен BitTorrent-трафик",
        body="Через вашу VPN-подписку шёл BitTorrent-трафик. Правила сервиса ограничивают торренты — пожалуйста, ознакомьтесь с ними. "
             "Если это были не вы, смените ссылку подписки в личном кабинете.",
        dedupe_key=f"torrent:{now.date().isoformat()}")


class TorrentItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client: str = Field(min_length=1, max_length=128)
    events: int = Field(ge=1, le=1_000_000)
    kind: str = Field(default="xray", pattern="^(xray|bittorrent|dht|utp|tracker|ndpi|encrypted)$")


class TorrentBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[TorrentItem] = Field(max_length=500)


@router.post("/api/agent/torrent")
async def agent_torrent(payload: TorrentBatch, db: AsyncSession = Depends(get_db), x_agent_token: str = Header(default="")):
    from .platform_api import _agent, _plugin_on, _require_plugin

    await _require_plugin(db, "agent")
    agent = await _agent(db, x_agent_token)
    if not await _plugin_on(db, "torrents"):
        await db.commit()
        return {"ok": True, "accepted": 0, "enabled": False}
    now = utcnow()
    hour = hour_of(now)
    notify = await notify_enabled(db)
    merged: dict[tuple[str, str], int] = {}
    for item in payload.items:
        key = (item.client.strip(), item.kind)
        merged[key] = min(1_000_000, merged.get(key, 0) + item.events)
    users: set[int] = set()
    confirmed: set[int] = set()
    resolved: dict[str, int | None] = {}
    for (client, kind), events in merged.items():
        if client not in resolved:
            resolved[client] = None if client == UNATTRIBUTED else await resolve_user(db, client)
        user_id = resolved[client]
        await _add(db, hour, agent.id, client, user_id, events, kind)
        if user_id:
            users.add(user_id)
            if kind in CONFIRMED:
                confirmed.add(user_id)
    if notify:
        threshold = await min_events(db)
        for user_id in confirmed:  # a heuristic ("encrypted") alone never notifies; nor a count under the threshold
            hour_total = await db.scalar(select(func.sum(TorrentDetection.events)).where(
                TorrentDetection.user_id == user_id, TorrentDetection.hour == hour, TorrentDetection.kind.in_(CONFIRMED))) or 0
            if hour_total >= threshold:
                await _notify(db, user_id, now)
    await db.commit()
    return {"ok": True, "accepted": len(merged), "matched": len(users), "enabled": True}


@router.get("/api/admin/platform/torrents")
async def admin_torrents(days: int = 30, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("ops.diagnostics"))):
    from .platform_api import _plugin_on

    days = max(1, min(RETENTION_DAYS, days))
    since = hour_of(utcnow() - timedelta(days=days))
    agents = {a.id: a.name for a in (await db.scalars(select(NodeAgent))).all()}
    rows = (await db.execute(select(TorrentDetection.client, TorrentDetection.user_id, func.sum(TorrentDetection.events), func.max(TorrentDetection.hour),
                                    func.count(func.distinct(TorrentDetection.agent_id)))
                             .where(TorrentDetection.hour >= since).group_by(TorrentDetection.client, TorrentDetection.user_id)
                             .order_by(func.sum(TorrentDetection.events).desc()).limit(100))).all()
    per_node = (await db.execute(select(TorrentDetection.agent_id, func.sum(TorrentDetection.events)).where(TorrentDetection.hour >= since)
                                 .group_by(TorrentDetection.agent_id))).all()
    per_day: dict[str, int] = {}
    for hour, events in (await db.execute(select(TorrentDetection.hour, TorrentDetection.events).where(TorrentDetection.hour >= since))).all():
        key = hour.date().isoformat()
        per_day[key] = per_day.get(key, 0) + events
    by_kind: dict[str, dict[str, int]] = {}
    totals: dict[str, int] = {}
    for client, kind, events in (await db.execute(select(TorrentDetection.client, TorrentDetection.kind, func.sum(TorrentDetection.events))
                                                  .where(TorrentDetection.hour >= since).group_by(TorrentDetection.client, TorrentDetection.kind))).all():
        by_kind.setdefault(client, {})[kind] = int(events)
        totals[kind] = totals.get(kind, 0) + int(events)
    usernames = {u.id: u.username or u.email or f"#{u.id}" for u in (await db.scalars(select(User).where(User.id.in_([r[1] for r in rows if r[1]])))).all()} if rows else {}
    return {
        "enabled": await _plugin_on(db, "torrents"), "notify": await notify_enabled(db), "min_events": await min_events(db), "days": days, "retention_days": RETENTION_DAYS,
        "clients": [{"client": c, "user_id": u, "user": usernames.get(u) if u else None, "events": int(e), "last_hour": h.isoformat(), "nodes": int(n),
                     "kinds": by_kind.get(c, {}), "likely_only": set(by_kind.get(c, {})) <= {"encrypted"}} for c, u, e, h, n in rows],
        "kinds": totals,
        "nodes": [{"agent_id": a, "node": agents.get(a, f"#{a}"), "events": int(e)} for a, e in sorted(per_node, key=lambda r: -int(r[1]))],
        "days_series": [{"day": d, "events": per_day[d]} for d in sorted(per_day)],
        "total": sum(per_day.values()),
    }


class NotifyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    notify: bool


class ThresholdIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    min_events: int = Field(ge=1, le=100000)


@router.post("/api/admin/platform/torrents/threshold")
async def admin_torrents_threshold(body: ThresholdIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("security.manage"))):
    row = await db.get(AppSetting, THRESHOLD_KEY)
    if row:
        row.value = str(body.min_events)
    else:
        db.add(AppSetting(key=THRESHOLD_KEY, value=str(body.min_events)))
    await db.commit()
    return {"min_events": body.min_events}


@router.post("/api/admin/platform/torrents/notify")
async def admin_torrents_notify(body: NotifyIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("security.manage"))):
    row = await db.get(AppSetting, NOTIFY_KEY)
    value = "1" if body.notify else "0"
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=NOTIFY_KEY, value=value))
    from .main import audit

    await audit(db, "abuse.torrent.notify", getattr(admin, "email", "admin"), None, {"notify": body.notify})
    await db.commit()
    return {"notify": body.notify}


async def enforce_retention(db: AsyncSession, now: datetime | None = None) -> int:
    cutoff = hour_of((now or utcnow()) - timedelta(days=RETENTION_DAYS))
    result = await db.execute(delete(TorrentDetection).where(TorrentDetection.hour < cutoff))
    await db.commit()
    return result.rowcount or 0


async def torrent_scheduler():
    from .db import SessionLocal

    while True:
        try:
            async with SessionLocal() as db:
                await enforce_retention(db)
        except Exception as exc:
            logger.warning("Torrent retention failed: %s", type(exc).__name__)
        await asyncio.sleep(3600)
