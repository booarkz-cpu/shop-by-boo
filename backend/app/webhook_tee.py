"""Remnawave webhooks: forwarding to more receivers and the journal of user changes «магазин / извне».

**Forwarding («тройник»).** The panel sends webhooks to one address — the shop. Other systems (a second bot, an
accounting script, a monitoring service) can get every event too: «Интеграции → Пересылка вебхуков» lists receivers,
each with its own secret; the shop re-signs the original body for each (HMAC-SHA256 hex in
``X-Remnawave-Signature``, as the panel does) and sends it in the background with three tries. Only HTTPS receivers.

**Change journal («Кто менял пользователя»).** Every user event carries the whole user. The shop keeps a snapshot
of the fields that matter (status, expiry, traffic limit and strategy, device limit, squads, external squad, tag,
description, Telegram ID, e-mail) and writes what changed since the previous event of the same user. The change is
marked **магазин** when the shop itself changed those fields through the API in the last five minutes
(``panel_api_stats.recent_writes``) and **извне** otherwise — a bot, a script or a person in the panel. No extra API
calls. Kept 90 days; CSV export can anonymise names and ids for an outside reader.
"""
from __future__ import annotations

import asyncio
import csv
import hashlib
import hmac
import io
import logging
from datetime import datetime, timedelta

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import decrypt_secret, encrypt_secret, require_permission

logger = logging.getLogger("vpnshop.webhook_tee")
router = APIRouter()
CONFIG_KEY = "webhooks.tee"
DEFAULT = {"targets": [], "journal": True}
FIELDS = ("status", "expireAt", "trafficLimitBytes", "trafficLimitStrategy", "hwidDeviceLimit", "activeInternalSquads",
          "externalSquadUuid", "tag", "description", "telegramId", "email", "username")
_pending: set[asyncio.Task] = set()


async def _config(db: AsyncSession) -> dict:
    from .node_health import _load
    return await _load(db, CONFIG_KEY, DEFAULT)


def sign(raw: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


async def _send(url: str, raw: bytes, secret: str, headers: dict) -> bool:
    body_headers = {"Content-Type": "application/json", "X-Remnawave-Signature": sign(raw, secret), **headers}
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
                r = await client.post(url, content=raw, headers=body_headers)
            if r.status_code < 500:
                return r.status_code < 400
        except httpx.HTTPError as exc:
            logger.info("Webhook forward to %s failed: %s", url, exc)
        await asyncio.sleep(2 ** attempt)
    return False


def forward(cfg: dict, raw: bytes, headers: dict) -> int:
    """Start forwarding in the background; returns the number of receivers."""
    passthrough = {k: v for k, v in headers.items() if k.lower() in {"x-remnawave-timestamp", "x-remnawave-event"}}
    count = 0
    for target in cfg.get("targets") or []:
        if not target.get("enabled", True) or not str(target.get("url", "")).startswith("https://"):
            continue
        try:
            secret = decrypt_secret(target.get("secret") or "")
        except Exception:  # noqa: BLE001 — a secret from another APP_SECRET: skip this receiver
            logger.warning("Webhook receiver %s has an unreadable secret", target.get("name"))
            continue
        task = asyncio.create_task(_send(target["url"], raw, secret, passthrough))
        _pending.add(task)
        task.add_done_callback(_pending.discard)
        count += 1
    return count


def snapshot(data: dict) -> dict:
    user = data.get("user") if isinstance(data.get("user"), dict) else data
    out = {}
    for key in FIELDS:
        if key in user:
            value = user.get(key)
            if key == "activeInternalSquads" and isinstance(value, list):
                value = sorted(str(x.get("uuid") if isinstance(x, dict) else x) for x in value)
            out[key] = value
    return out


async def journal(db: AsyncSession, event: str, data: dict, panel_user: str, user_id: int | None) -> dict | None:
    """Store the change of this event; returns the row as a dict (None when the event carries no user)."""
    from .models import PanelUserChange
    from .panel_api_stats import recent_writes
    if not panel_user:
        return None
    snap = snapshot(data)
    if not snap:
        return None
    previous = (await db.execute(select(PanelUserChange).where(PanelUserChange.panel_user == panel_user)
                                 .order_by(PanelUserChange.id.desc()).limit(1))).scalar_one_or_none()
    if previous is None:
        changed, source = {}, "first"
    else:
        changed = {k: [previous.snapshot.get(k), v] for k, v in snap.items() if previous.snapshot.get(k) != v}
        if not changed and event not in {"user.created", "user.deleted"}:
            return None
        ours = await recent_writes(panel_user)
        source = "shop" if changed and (set(changed) <= ours | {"status"} and ours) else "external"
    row = PanelUserChange(panel_user=panel_user, user_id=user_id, event=event, source=source, changed=changed, snapshot=snap)
    db.add(row)
    await db.commit()
    return {"source": source, "changed": changed}


# ---------------------------------------------------------------- admin


class TargetIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=60)
    url: str = Field(..., max_length=300, pattern=r"^https://\S+$")
    secret: str = Field("", max_length=200)  # empty: keep the stored one
    enabled: bool = True


class TeeIn(BaseModel):
    targets: list[TargetIn] = Field(default_factory=list, max_length=10)
    journal: bool = True


@router.get("/api/admin/webhooks/tee")
async def get_tee(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("ops.diagnostics"))):
    cfg = await _config(db)
    return {"journal": cfg.get("journal", True),
            "targets": [{"name": t.get("name"), "url": t.get("url"), "enabled": t.get("enabled", True), "has_secret": bool(t.get("secret"))}
                        for t in cfg.get("targets") or []]}


@router.put("/api/admin/webhooks/tee")
async def put_tee(payload: TeeIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("settings.runtime.write"))):
    from .node_health import _save
    old = {t.get("name"): t for t in (await _config(db)).get("targets") or []}
    targets = []
    for t in payload.targets:
        secret = encrypt_secret(t.secret) if t.secret else (old.get(t.name) or {}).get("secret", "")
        if not secret:
            raise HTTPException(422, f"«{t.name}»: задайте секрет подписи — получатель проверяет им вебхуки")
        targets.append({"name": t.name, "url": t.url, "enabled": t.enabled, "secret": secret})
    await _save(db, CONFIG_KEY, {"targets": targets, "journal": payload.journal})
    await db.commit()
    return {"ok": True, "targets": len(targets)}


@router.post("/api/admin/webhooks/tee/test")
async def test_tee(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("settings.runtime.write"))):
    import json
    raw = json.dumps({"scope": "user", "event": "shop.test", "timestamp": datetime.utcnow().isoformat() + "Z", "data": {}}).encode()
    cfg = await _config(db)
    results = []
    for target in cfg.get("targets") or []:
        ok = await _send(target["url"], raw, decrypt_secret(target.get("secret") or ""), {}) if target.get("enabled", True) else None
        results.append({"name": target.get("name"), "ok": ok})
    return {"results": results}


def _rows_json(rows) -> list[dict]:
    return [{"id": r.id, "at": r.created_at.isoformat(timespec="seconds"), "panel_user": r.panel_user, "user_id": r.user_id,
             "event": r.event, "source": r.source, "changed": r.changed} for r in rows]


@router.get("/api/admin/panel-changes")
async def changes(panel_user: str = "", user_id: int | None = None, source: str = "", limit: int = 100,
                  db: AsyncSession = Depends(get_db), admin=Depends(require_permission("users.read"))):
    from .models import PanelUserChange
    q = select(PanelUserChange).order_by(PanelUserChange.id.desc()).limit(min(max(limit, 1), 500))
    if panel_user:
        q = q.where(PanelUserChange.panel_user == panel_user)
    if user_id:
        q = q.where(PanelUserChange.user_id == user_id)
    if source in {"shop", "external", "first"}:
        q = q.where(PanelUserChange.source == source)
    return {"rows": _rows_json((await db.execute(q)).scalars().all())}


@router.get("/api/admin/panel-changes.csv")
async def changes_csv(anonymize: bool = False, days: int = 30, db: AsyncSession = Depends(get_db),
                      admin=Depends(require_permission("users.read"))):
    from .models import PanelUserChange
    since = datetime.utcnow() - timedelta(days=min(max(days, 1), 90))
    rows = (await db.execute(select(PanelUserChange).where(PanelUserChange.created_at >= since).order_by(PanelUserChange.id))).scalars().all()
    labels: dict[str, str] = {}

    def label(value) -> str:
        text = str(value)
        if not anonymize or value in (None, ""):
            return text
        return labels.setdefault(text, f"id{len(labels) + 1}")

    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["time", "user", "event", "source", "field", "before", "after"])
    for r in rows:
        for field, (before, after) in (r.changed or {}).items() or [("", ("", ""))]:
            if anonymize and field in {"username", "email", "telegramId", "description"}:
                before, after = label(before), label(after)
            if anonymize and field in {"activeInternalSquads", "externalSquadUuid"}:
                before = [label(x) for x in before] if isinstance(before, list) else label(before)
                after = [label(x) for x in after] if isinstance(after, list) else label(after)
            w.writerow([r.created_at.isoformat(timespec="seconds"), label(r.panel_user), r.event, r.source, field, before, after])
    return Response(out.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=panel-changes.csv"})


async def cleanup(db: AsyncSession) -> int:
    from .models import PanelUserChange
    result = await db.execute(delete(PanelUserChange).where(PanelUserChange.created_at < datetime.utcnow() - timedelta(days=90)))
    await db.commit()
    return int(result.rowcount or 0)


FEED_TITLES = {
    "user.created": "Новый пользователь в панели", "user.expired": "Подписка закончилась", "user.limited": "Трафик закончился",
    "user.first_connected": "Первое подключение", "user.bandwidth_usage_threshold_reached": "Трафик заканчивается",
    "user.expires_in_72_hours": "Закончится через 3 дня", "user.expires_in_24_hours": "Закончится через сутки",
    "user.disabled": "Отключён", "user.enabled": "Включён", "user.revoked": "Ссылка перевыпущена", "user.deleted": "Удалён в панели",
    "user_hwid_devices.added": "Новое устройство", "user_hwid_devices.deleted": "Устройство удалено",
}


@router.get("/api/admin/subscription-feed")
async def subscription_feed(limit: int = 40, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("read"))):
    """Dashboard feed «События подписок»: payments, panel events and changes made outside the shop, newest first."""
    from .models import Payment, PanelUserChange, RemnawaveEvent
    limit = min(max(limit, 5), 100)
    items = []
    for p in (await db.execute(select(Payment).where(Payment.status == "paid", Payment.paid_at.is_not(None))
                               .order_by(Payment.paid_at.desc()).limit(limit))).scalars():
        items.append({"at": p.paid_at, "kind": "payment", "user_id": p.user_id, "title": "Оплата",
                      "detail": f"{p.amount} {p.currency}" + (f" · {p.provider}" if getattr(p, "provider", None) else "")})
    for e in (await db.execute(select(RemnawaveEvent).order_by(RemnawaveEvent.id.desc()).limit(limit))).scalars():
        items.append({"at": e.created_at, "kind": "panel", "user_id": e.user_id, "title": FEED_TITLES.get(e.event, e.event), "detail": ""})
    for c in (await db.execute(select(PanelUserChange).where(PanelUserChange.source == "external")
                               .order_by(PanelUserChange.id.desc()).limit(limit))).scalars():
        items.append({"at": c.created_at, "kind": "external", "user_id": c.user_id, "title": "Изменено вне магазина",
                      "detail": ", ".join(sorted(c.changed or {}))[:120]})
    items.sort(key=lambda x: x["at"], reverse=True)
    return {"items": [{**x, "at": x["at"].isoformat(timespec="seconds")} for x in items[:limit]]}
