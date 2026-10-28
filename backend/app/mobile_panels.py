"""Module panels for the Android and iOS admin apps: one generic screen instead of a native screen per module.

``GET /api/admin/mobile/panels`` returns cards built by the modules themselves::

    {"id": "payment_methods", "title": "Способы оплаты",
     "rows": [{"label": "СБП", "value": "ЮKassa → RollyPay", "tone": "ok"}],
     "actions": [{"label": "Выключить", "method": "PUT", "path": "/api/admin/payments/methods", "body": {...},
                  "confirm": "…"}]}

The apps show the rows and turn each action into a button that sends exactly that request to an ``/api/admin/``
path with the admin's own session — the server checks the permission of every action as for the web admin. A new
module adds its builder to ``BUILDERS``; the apps need no update.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import require_permission

logger = logging.getLogger("vpnshop.mobile_panels")
router = APIRouter()

NAMES = {"yookassa": "ЮKassa", "rollypay": "RollyPay", "platega": "Platega", "cryptobot": "CryptoBot", "freekassa": "Freekassa"}


def row(label: str, value, tone: str = "") -> dict:
    return {"label": label, "value": str(value), "tone": tone}


def action(label: str, method: str, path: str, body: dict | None = None, confirm: str = "") -> dict:
    assert path.startswith("/api/admin/")
    return {"label": label, "method": method, "path": path, "body": body or {}, "confirm": confirm}


async def payment_methods_panel(db: AsyncSession) -> dict:
    from .payment_methods import METHODS, load
    from .payments_api import provider_configured
    config = await load(db)
    ready = provider_configured()
    rows = [row("Выбор способа клиентом", "включён" if config["enabled"] else "выключен", "ok" if config["enabled"] else "")]
    actions = [action("Выключить выбор способа" if config["enabled"] else "Включить выбор способа", "PUT", "/api/admin/payments/methods",
                      {"enabled": not config["enabled"], "routes": config["routes"]})]
    for method, title in METHODS.items():
        order = config["routes"][method]
        working = [p for p in order if ready.get(p)]
        rows.append(row(title, " → ".join(NAMES.get(p, p) for p in order) or "нет касс", "ok" if working else "warn"))
        for index, provider in enumerate(order[1:], 1):
            moved = list(order)
            moved[index - 1], moved[index] = moved[index], moved[index - 1]
            actions.append(action(f"{title}: {NAMES.get(provider, provider)} выше", "PUT", "/api/admin/payments/methods",
                                  {"enabled": config["enabled"], "routes": {**config["routes"], method: moved}}))
    return {"id": "payment_methods", "title": "Способы оплаты", "rows": rows, "actions": actions}


async def hot_standby_panel(db: AsyncSession) -> dict:
    from .hot_standby import get_standby
    data = await get_standby(db, None)
    repl, beat = data["replication"], data["heartbeat"] or {}
    rows = [row("Резерв ожидается", "да" if data["config"].get("enabled") else "нет")]
    if repl.get("supported"):
        rows.append(row("Роль этого сервера", "резерв" if repl.get("in_recovery") else "основной"))
        for r in repl.get("replicas", []):
            rows.append(row(f"Реплика {r['address']}", f"{r['state']}, отставание {r['lag_seconds']} с", "ok" if r["state"] == "streaming" else "warn"))
    rows.append(row("Агент резерва", ("на связи" if data["heartbeat_fresh"] else "молчит") if beat.get("at") else "не установлен",
                    "ok" if data["heartbeat_fresh"] else "warn"))
    for p in data["problems"]:
        rows.append(row(p["title"], p["detail"], "bad" if p["severity"] == "critical" else "warn"))
    return {"id": "hot_standby", "title": "Горячий резерв", "rows": rows, "actions": [
        action("Выключить оповещения резерва" if data["config"].get("enabled") else "Резерв настроен — следить", "PUT", "/api/admin/standby",
               {"enabled": not data["config"].get("enabled"), "lag_alert_seconds": data["config"].get("lag_alert_seconds", 300)})]}


async def autoscale_panel(db: AsyncSession) -> dict:
    from .node_autoscale import get_autoscale
    data = await get_autoscale(db, None)
    cfg, last = data["config"], data["last"] or {}
    rows = [row("Включено", "да" if cfg["enabled"] else "нет"), row("Режим", "авто (Hetzner)" if cfg["mode"] == "auto" else "рекомендации")]
    if last:
        rows.append(row("Нагрузка", f"{last.get('load')} на ноду, нод онлайн {last.get('online')}",
                        "warn" if last.get("action") else "ok"))
        if last.get("reason"):
            rows.append(row("Решение", last["reason"]))
    for c in data["created"]:
        rows.append(row(f"Создана {c['name']}", c["ip"]))
    toggle = {k: v for k, v in cfg.items()}
    return {"id": "node_autoscale", "title": "Автомасштабирование нод", "rows": rows, "actions": [
        action("Выключить" if cfg["enabled"] else "Включить", "PUT", "/api/admin/nodes/autoscale", {**toggle, "enabled": not cfg["enabled"]}),
        action("Режим: рекомендации" if cfg["mode"] == "auto" else "Режим: авто (Hetzner)", "PUT", "/api/admin/nodes/autoscale",
               {**toggle, "mode": "recommend" if cfg["mode"] == "auto" else "auto"},
               "" if cfg["mode"] == "auto" else "Магазин будет сам создавать и удалять серверы в Hetzner. Включить?")]}


async def block_monitor_panel(db: AsyncSession) -> dict:
    from .block_monitor import get_monitor
    data = await get_monitor(db, None)
    rows = [row("Реагировать на блокировки", "да" if data["config"].get("enabled") else "нет"),
            row("Пробы", ", ".join(f"{p['name']} ({p['region']})" for p in data.get("probes", [])) or "нет")]
    for target, info in (data.get("blocked") or {}).items():
        rows.append(row(f"Заблокировано: {info.get('label', target)}", ", ".join(info.get("regions", [])), "bad"))
    return {"id": "block_monitor", "title": "Монитор блокировок", "rows": rows, "actions": []}


BUILDERS = [payment_methods_panel, hot_standby_panel, autoscale_panel, block_monitor_panel]


@router.get("/api/admin/mobile/panels")
async def mobile_panels(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("ops.diagnostics"))):
    panels = []
    for build in BUILDERS:
        try:
            panels.append(await build(db))
        except Exception as exc:  # noqa: BLE001 — one broken module must not hide the others
            logger.warning("mobile panel %s failed: %s", build.__name__, exc)
            await db.rollback()
            panels.append({"id": build.__name__, "title": build.__name__, "rows": [row("Ошибка", str(exc)[:200], "bad")], "actions": []})
    return {"panels": panels}
