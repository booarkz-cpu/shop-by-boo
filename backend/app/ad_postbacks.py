"""Advertising conversions: S2S postbacks to ad networks / trackers and Yandex Metrika offline conversions.

The click comes with the customer: bot ``/start …__cid_<click id>``, cabinet and Mini App ``?click_id=`` (or ``?cid=``),
and the Metrika visitor id ``_ym_uid`` that the cabinet sends once. They are stored with the customer
(``user_activity`` «ad.click»). On **registration**, **trial** and **purchase** the shop calls:

* every postback URL configured for the event, with ``{click_id} {user_id} {event} {amount} {currency} {order_id}``
  substituted (URL-encoded), GET, 3 tries;
* Yandex Metrika Measurement Protocol (``mc.yandex.ru/collect``: ``tid``, ``cid``, ``ms``, ``t=event``, ``ea``; for a
  purchase ``ev`` and ``cu``) when a counter and its measurement secret are set.

Sending happens in a background task and never slows the customer down. «Аналитика → Рекламные конверсии».
"""
from __future__ import annotations

import asyncio
import logging
import re
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import require_permission

logger = logging.getLogger("vpnshop.postbacks")
router = APIRouter()
CONFIG_KEY = "ads.postbacks"
EVENTS = ("registration", "trial", "purchase")
DEFAULT = {"enabled": False, "urls": {e: "" for e in EVENTS}, "metrika_counter": "", "metrika_secret": "",
           "metrika_goals": {"registration": "registration", "trial": "trial", "purchase": "purchase"}}
CLICK_RE = re.compile(r"^[A-Za-z0-9._:-]{4,128}$")
YM_RE = re.compile(r"^\d{8,25}$")
LOG: list[dict] = []  # last 50 sends of this process, shown in the admin


class PostbacksIn(BaseModel):
    enabled: bool
    urls: dict[str, str] = Field(default_factory=dict)
    metrika_counter: str = Field("", max_length=20, pattern=r"^\d*$")
    metrika_secret: str = Field("", max_length=200)
    metrika_goals: dict[str, str] = Field(default_factory=dict)


async def _load(db):
    from .node_health import _load as load
    return await load(db, CONFIG_KEY, DEFAULT)


async def remember_click(db: AsyncSession, user_id: int, click_id: str | None = None, ym_uid: str | None = None) -> bool:
    from .activity_log import record
    detail = {}
    if click_id and CLICK_RE.match(click_id):
        detail["click_id"] = click_id
    if ym_uid and YM_RE.match(ym_uid):
        detail["ym_uid"] = ym_uid
    if detail:
        record(db, user_id, "system", "ad.click", detail)
    return bool(detail)


async def clicks(db: AsyncSession, user_id: int) -> dict:
    from .models import UserActivity
    out: dict = {}
    for row in (await db.execute(select(UserActivity).where(UserActivity.user_id == user_id, UserActivity.action == "ad.click")
                                 .order_by(UserActivity.id.desc()).limit(10))).scalars():
        for k, v in (row.detail or {}).items():
            out.setdefault(k, v)
    return out


def click_from_start(arg: str) -> str | None:
    for part in (arg or "").split("__"):
        if part.startswith("cid_"):
            return part[4:]
    return None


async def send_event(user_id: int, event: str, amount: str = "", currency: str = "RUB", order_id: str = "", client=None) -> list[str]:
    """Postbacks and Metrika for one event; returns what was sent (for tests and the admin log)."""
    from .db import SessionLocal
    async with SessionLocal() as db:
        config = await _load(db)
        if not config.get("enabled"):
            return []
        found = await clicks(db, user_id)
    sent = []
    own = client is None
    client = client or httpx.AsyncClient(timeout=10)
    try:
        template = (config.get("urls") or {}).get(event) or ""
        if template.startswith("https://") and found.get("click_id"):
            values = {"click_id": found["click_id"], "user_id": str(user_id), "event": event, "amount": amount,
                      "currency": currency, "order_id": order_id}
            url = re.sub(r"\{(\w+)\}", lambda m: quote(values.get(m.group(1), ""), safe=""), template)
            sent.append(await _try(client, "GET", url, None, f"postback {event}"))
        if config.get("metrika_counter") and config.get("metrika_secret") and found.get("ym_uid"):
            goal = (config.get("metrika_goals") or {}).get(event) or event
            form = {"tid": config["metrika_counter"], "cid": found["ym_uid"], "ms": config["metrika_secret"], "t": "event", "ea": goal}
            if event == "purchase" and amount:
                form.update(ev=amount, cu=currency)
            sent.append(await _try(client, "POST", "https://mc.yandex.ru/collect", form, f"metrika {event}"))
    finally:
        if own:
            await client.aclose()
    return [s for s in sent if s]


async def _try(client, method, url, form, label) -> str:
    for attempt in range(3):
        try:
            response = await (client.get(url) if method == "GET" else client.post(url, data=form))
            ok = response.status_code < 400
            LOG.insert(0, {"label": label, "status": response.status_code})
            del LOG[50:]
            if ok:
                return label
        except Exception as exc:  # noqa: BLE001
            logger.info("%s attempt %s: %s", label, attempt + 1, exc)
        await asyncio.sleep(1 + attempt * 2)
    return ""


def fire(user_id: int, event: str, **kwargs) -> None:
    """Fire and forget from request handlers and fulfillment."""
    try:
        from .main import _track_task
        _track_task(send_event(user_id, event, **kwargs))
    except Exception as exc:  # noqa: BLE001 — conversions never break a purchase
        logger.info("postback not queued: %s", exc)


@router.get("/api/admin/ads/postbacks")
async def get_postbacks(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("analytics.read"))):
    config = await _load(db)
    return {**config, "metrika_secret": "***" if config.get("metrika_secret") else "", "events": list(EVENTS), "log": LOG[:20]}


@router.put("/api/admin/ads/postbacks")
async def put_postbacks(payload: PostbacksIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("settings.runtime.write"))):
    from fastapi import HTTPException

    from .main import audit
    from .node_health import _save
    config = await _load(db)
    for event, url in payload.urls.items():
        if event not in EVENTS or (url and not url.startswith("https://")):
            raise HTTPException(400, f"Адрес для «{event}» должен начинаться с https://")
    value = payload.model_dump()
    if value["metrika_secret"] in ("", "***"):
        value["metrika_secret"] = config.get("metrika_secret", "") if value["metrika_secret"] == "***" else ""
    await _save(db, CONFIG_KEY, value)
    await audit(db, "ads.postbacks", admin.email, None, {"enabled": payload.enabled, "events": [e for e, u in payload.urls.items() if u]})
    await db.commit()
    return {"ok": True}
