"""Public status page with outage news (v28.47).

* ``GET /status`` — a self-contained page (brand name, no outside assets) that reads ``GET /api/public/status-page``.
* The page shows regions built from the Remnawave nodes (by country: all servers up — «работает», some — «частично»,
  none — «недоступен»; no addresses), payments (at least one gateway is enabled, configured and not cooling down), the
  operator's components (``status_components``) and the «service» incidents of «Инциденты» of the last
  ``history_days`` days (the same incidents the cabinet's «Состояние сервиса» shows).
* A region whose servers are all down for ``outage_minutes`` opens a «service» incident by itself; when a server is
  back the incident is resolved. Subscribers (``status_subscribers``) get the news in Telegram and in the notification
  center (which the apps mirror as push) — for these automatic incidents and for «service» incidents the operator opens
  or resolves in «Инциденты».
* Customers subscribe in the cabinet / Mini App (``/api/me/status/subscription``) or with the bot command ``/status``.
"""
from __future__ import annotations

import asyncio
import html
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import get_db
from .security import require_permission

logger = logging.getLogger("vpnshop.status_page")
router = APIRouter()
CONFIG_KEY = "status.page"
STATE_KEY = "status.regions_state"
DEFAULT = {"enabled": True, "title": "", "outage_minutes": 5, "history_days": 30, "notify": True}
LABELS = {"operational": "работает", "degraded": "частично", "outage": "недоступен", "unknown": "нет данных"}
FLAGS_OFF = {"disabled"}


class ConfigIn(BaseModel):
    enabled: bool = True
    title: str = Field("", max_length=80)
    outage_minutes: int = Field(5, ge=1, le=120)
    history_days: int = Field(30, ge=1, le=180)
    notify: bool = True


async def _load(db, key, default):
    from .node_health import _load as load
    return await load(db, key, default)


async def _save(db, key, value):
    from .node_health import _save as save
    await save(db, key, value)


def regions_from(nodes: list[dict]) -> list[dict]:
    """Countries of the active (not disabled) servers with their state; no names or addresses."""
    by: dict[str, dict] = {}
    for n in nodes:
        if str(n.get("status") or "") in FLAGS_OFF:
            continue
        cc = str(n.get("country") or "").upper()[:2] or "—"
        item = by.setdefault(cc, {"country": cc, "total": 0, "online": 0})
        item["total"] += 1
        item["online"] += 1 if str(n.get("status") or "") == "online" else 0
    out = []
    for item in by.values():
        state = "operational" if item["online"] == item["total"] else "outage" if item["online"] == 0 else "degraded"
        out.append({**item, "status": state, "label": LABELS[state]})
    return sorted(out, key=lambda x: x["country"])


async def payments_ok(db: AsyncSession) -> bool:
    """At least one gateway is enabled, has its keys and is not cooling down (read-only: no queue locks)."""
    from .models import PaymentProviderHealth
    from .payment_policy import PAYMENT_AGENTS
    from .payments_api import provider_configured
    configured = provider_configured()
    now = datetime.utcnow()
    rows = {r.provider: r for r in (await db.execute(select(PaymentProviderHealth))).scalars().all()}
    for name in PAYMENT_AGENTS:
        if not configured.get(name):
            continue
        row = rows.get(name)
        if row is None or (row.enabled and (not row.circuit_open_until or row.circuit_open_until <= now)):
            return True
    return False


async def build(db: AsyncSession, nodes: list[dict] | None = None, now: datetime | None = None) -> dict:
    from .models import SecurityIncidentEvent, StatusComponent
    now = now or datetime.utcnow()
    cfg = {**DEFAULT, **(await _load(db, CONFIG_KEY, DEFAULT))}
    if nodes is None:
        from .node_health import node_snapshot
        nodes = (await node_snapshot()).get("nodes") or []
    regions = regions_from(nodes)
    pay = await payments_ok(db)
    manual = (await db.execute(select(StatusComponent).where(StatusComponent.enabled.is_(True))
                               .order_by(StatusComponent.sort_order, StatusComponent.id))).scalars().all()
    since = now - timedelta(days=int(cfg["history_days"]))
    incidents = (await db.execute(select(SecurityIncidentEvent).where(SecurityIncidentEvent.category == "service",
                                                                      SecurityIncidentEvent.created_at >= since)
                                  .order_by(SecurityIncidentEvent.created_at.desc()).limit(50))).scalars().all()
    components = [{"name": "Приём оплаты", "status": "operational" if pay else "outage"}]
    components += [{"name": c.name, "status": c.status if c.status in LABELS else "degraded", "message": c.message} for c in manual]
    for c in components:
        c["label"] = LABELS.get(c["status"], c["status"])
    states = [r["status"] for r in regions] + [c["status"] for c in components]
    if any(i.status != "resolved" for i in incidents):
        states.append("degraded")
    overall = "outage" if regions and all(r["status"] == "outage" for r in regions) else \
        "operational" if all(x == "operational" for x in states) else "degraded"
    return {"title": cfg["title"] or f"{await brand(db)} — статус", "overall": overall, "overall_label": LABELS.get(overall, overall),
            "regions": regions, "components": components, "updated_at": now.isoformat(),
            "incidents": [{"id": i.id, "title": i.title, "message": i.details or "", "severity": i.severity,
                           "status": "open" if i.status != "resolved" else "resolved", "started_at": i.created_at.isoformat(),
                           "resolved_at": i.resolved_at.isoformat() if i.resolved_at else None} for i in incidents]}


async def brand(db: AsyncSession) -> str:
    try:
        from . import main as shop
        return str((await shop.public_config(db)).get("app_name") or "Корги Люси")
    except Exception:  # noqa: BLE001 — the page works without branding
        return "Корги Люси"


# ------------------------------------------------------------------ notifications
async def notify(db: AsyncSession, incident, opened: bool, sender=None) -> int:
    """Tell every subscriber about a «service» incident; Telegram directly, the notification center (and push) queued."""
    from .models import StatusSubscriber, User
    cfg = {**DEFAULT, **(await _load(db, CONFIG_KEY, DEFAULT))}
    if not cfg["notify"] or getattr(incident, "category", "service") != "service":
        return 0
    if sender is None:
        from .schedulers import notify_user_telegram as sender
    from . import main as shop
    title = ("⚠️ " if opened else "✅ ") + (incident.title if opened else f"Восстановлено: {incident.title}")
    body = (incident.details if opened else "") or ("Мы уже разбираемся. Сообщим, когда всё заработает." if opened else "Сервис снова работает.")
    users = (await db.execute(select(User).join(StatusSubscriber, StatusSubscriber.user_id == User.id).where(User.deleted_at.is_(None)))).scalars().all()
    for u in users:
        await shop.enqueue_notification(db, user_id=u.id, channel="in_app", kind="status", title=title[:200], body=body[:1000],
                                        dedupe_key=f"status:{incident.id}:{'open' if opened else 'closed'}")
    await db.commit()
    for u in users:
        if u.telegram_id:
            await sender(u.telegram_id, f"<b>{html.escape(title)}</b>\n{html.escape(body)}")
    return len(users)


async def watch(db: AsyncSession, nodes: list[dict] | None = None, now: datetime | None = None, sender=None) -> dict:
    """Open a «service» incident for a region down past ``outage_minutes``; resolve it when a server is back."""
    from .models import SecurityIncidentEvent
    now = now or datetime.utcnow()
    cfg = {**DEFAULT, **(await _load(db, CONFIG_KEY, DEFAULT))}
    if nodes is None:
        from .node_health import node_snapshot
        snap = await node_snapshot()
        if snap.get("error"):
            return {"skipped": snap["error"]}  # the panel did not answer: say nothing rather than a false outage
        nodes = snap.get("nodes") or []
    state = await _load(db, STATE_KEY, {})
    opened, closed = [], []
    for r in regions_from(nodes):
        cc = r["country"]
        item = state.get(cc) or {}
        if r["status"] == "outage":
            item.setdefault("down_since", now.isoformat())
            down_for = now - datetime.fromisoformat(item["down_since"])
            if not item.get("incident") and down_for >= timedelta(minutes=int(cfg["outage_minutes"])):
                inc = SecurityIncidentEvent(category="service", severity="high", title=f"Серверы {cc} недоступны",
                                            details="Подключение через этот регион сейчас не работает. Можно выбрать другой сервер.",
                                            status="open", created_at=now)
                db.add(inc)
                await db.flush()
                item["incident"] = inc.id
                opened.append(inc)
        else:
            item.pop("down_since", None)
            if item.get("incident"):
                inc = await db.get(SecurityIncidentEvent, item.pop("incident"))
                if inc and inc.status != "resolved":
                    inc.status, inc.resolved_at = "resolved", now
                    closed.append(inc)
        state[cc] = item
    await _save(db, STATE_KEY, state)
    await db.commit()
    for inc in opened:
        await notify(db, inc, True, sender)
    for inc in closed:
        await notify(db, inc, False, sender)
    return {"opened": [i.id for i in opened], "closed": [i.id for i in closed]}


# ------------------------------------------------------------------ public
PAGE = """<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title><style>
body{margin:0;font:16px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:#0f1115;color:#e8e8ea}
main{max-width:720px;margin:0 auto;padding:24px 16px}h1{font-size:22px;margin:0 0 4px}.muted{color:#9aa0a6;font-size:14px}
.banner{border-radius:12px;padding:16px;margin:16px 0;font-weight:600}.operational{background:#123d2a}.degraded{background:#4a3a10}
.outage{background:#4a1616}.unknown{background:#2a2d33}ul{list-style:none;padding:0;margin:0}li{display:flex;justify-content:space-between;
padding:10px 0;border-bottom:1px solid #23262d}.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:8px}
.dot.operational{background:#2ecc71}.dot.degraded{background:#f1c40f}.dot.outage{background:#e74c3c}.dot.unknown{background:#7f8c8d}
h2{font-size:17px;margin:24px 0 8px}.inc{padding:10px 0;border-bottom:1px solid #23262d}</style></head><body><main>
<h1>__TITLE__</h1><div class="muted" id="upd">Загрузка…</div><div id="banner" class="banner unknown">…</div>
<h2>Регионы</h2><ul id="regions"></ul><h2>Сервисы</h2><ul id="components"></ul><h2>События</h2><div id="incidents"></div>
<p class="muted">Подписаться на новости о сбоях можно в личном кабинете, Mini App или командой /status в боте.</p></main>
<script>
const flag=c=>c&&c.length===2?String.fromCodePoint(...[...c].map(x=>127397+x.charCodeAt(0))):"🌐";
const esc=s=>String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const row=(name,s,label)=>`<li><span><span class="dot ${s}"></span>${name}</span><span class="muted">${esc(label)}</span></li>`;
async function load(){try{const d=await (await fetch("/api/public/status-page",{cache:"no-store"})).json();
document.getElementById("banner").className="banner "+d.overall;
document.getElementById("banner").textContent=d.overall==="operational"?"Все системы работают":d.overall==="outage"?"Серьёзный сбой":d.overall==="degraded"?"Часть сервиса работает с перебоями":"Нет данных";
document.getElementById("regions").innerHTML=d.regions.map(r=>row(flag(r.country)+" "+esc(r.country),r.status,r.label+" · "+r.online+"/"+r.total)).join("")||'<li class="muted">Нет данных</li>';
document.getElementById("components").innerHTML=d.components.map(c=>row(esc(c.name),c.status,c.label)).join("");
document.getElementById("incidents").innerHTML=d.incidents.map(i=>`<div class="inc"><b>${esc(i.title)}</b> <span class="muted">${i.status==="open"?"идёт":"решено"} · ${esc(i.started_at.slice(0,16).replace("T"," "))} UTC</span><div class="muted">${esc(i.message)}</div></div>`).join("")||'<p class="muted">За последнее время сбоев не было.</p>';
document.getElementById("upd").textContent="Обновлено "+new Date(d.updated_at+"Z").toLocaleString();}catch(e){document.getElementById("upd").textContent="Не удалось загрузить статус";}}
load();setInterval(load,60000);</script></body></html>"""


@router.get("/api/public/status-page")
async def public_status_page(db: AsyncSession = Depends(get_db)):
    cfg = {**DEFAULT, **(await _load(db, CONFIG_KEY, DEFAULT))}
    if not cfg["enabled"]:
        raise HTTPException(404, "Страница статуса выключена")
    return await build(db)


@router.get("/status", response_class=HTMLResponse)
async def status_html(db: AsyncSession = Depends(get_db)):
    cfg = {**DEFAULT, **(await _load(db, CONFIG_KEY, DEFAULT))}
    if not cfg["enabled"]:
        raise HTTPException(404, "Страница статуса выключена")
    title = html.escape(cfg["title"] or f"{await brand(db)} — статус")
    return HTMLResponse(PAGE.replace("__TITLE__", title), headers={"Cache-Control": "no-store"})


# ------------------------------------------------------------------ customers
@router.get("/api/me/status/subscription")
async def my_subscription(request: Request, db: AsyncSession = Depends(get_db)):
    from . import main as shop
    from .models import StatusSubscriber
    user = await shop.user_from_token(request, db)
    on = await db.scalar(select(StatusSubscriber.id).where(StatusSubscriber.user_id == user.id))
    return {"subscribed": bool(on), "page": f"{settings.webhook_base_url.rstrip('/')}/status" if settings.webhook_base_url else "/status"}


@router.post("/api/me/status/subscription")
async def subscribe(request: Request, db: AsyncSession = Depends(get_db)):
    from . import main as shop
    from .models import StatusSubscriber
    user = await shop.user_from_token(request, db)
    if not await db.scalar(select(StatusSubscriber.id).where(StatusSubscriber.user_id == user.id)):
        db.add(StatusSubscriber(user_id=user.id))
        await db.commit()
    return {"subscribed": True}


@router.delete("/api/me/status/subscription")
async def unsubscribe(request: Request, db: AsyncSession = Depends(get_db)):
    from . import main as shop
    from .models import StatusSubscriber
    user = await shop.user_from_token(request, db)
    await db.execute(delete(StatusSubscriber).where(StatusSubscriber.user_id == user.id))
    await db.commit()
    return {"subscribed": False}


# ------------------------------------------------------------------ admin
@router.get("/api/admin/status-page")
async def admin_view(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("ops.diagnostics"))):
    from sqlalchemy import func
    from .models import StatusSubscriber
    cfg = {**DEFAULT, **(await _load(db, CONFIG_KEY, DEFAULT))}
    subscribers = int(await db.scalar(select(func.count()).select_from(StatusSubscriber)) or 0)
    return {"config": cfg, "subscribers": subscribers, "page": await build(db)}


@router.put("/api/admin/status-page/config")
async def admin_config(body: ConfigIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("ops.incidents"))):
    await _save(db, CONFIG_KEY, body.model_dump())
    from . import main as shop
    await shop.audit(db, "status_page.config", admin.email, None, body.model_dump())
    await db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ background
async def _loop() -> None:
    from .db import SessionLocal
    from .main import redis_client
    while True:
        try:
            async with SessionLocal() as db:
                cfg = {**DEFAULT, **(await _load(db, CONFIG_KEY, DEFAULT))}
                if cfg["enabled"] and (redis_client is None or await redis_client.set("lock:status_page", "1", nx=True, ex=110)):
                    await watch(db)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Status watch failed: %s", exc)
        await asyncio.sleep(120)


def _start() -> None:
    from .main import _track_task
    _track_task(_loop())


router.add_event_handler("startup", _start)
