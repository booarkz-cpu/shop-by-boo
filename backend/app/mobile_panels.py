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

NAMES = {"yookassa": "ЮKassa", "rollypay": "RollyPay", "platega": "Platega", "cryptobot": "CryptoBot", "freekassa": "Freekassa", "cloudpayments": "CloudPayments", "lava": "Lava", "pal24": "Pal24", "mulenpay": "Mulen Pay", "wata": "WATA", "antilopay": "Antilopay"}


def row(label: str, value, tone: str = "") -> dict:
    return {"label": label, "value": str(value), "tone": tone}


def action(label: str, method: str, path: str, body: dict | None = None, confirm: str = "") -> dict:  # noqa: D401
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
    if beat.get("drill"):
        d = beat["drill"]
        rows.append(row("Учебное повышение", f"прошло {str(d.get('at'))[:10]}" if d.get("ok") else f"не прошло: {str(d.get('error'))[:120]}",
                        "ok" if d.get("ok") else "bad"))
    if beat.get("files"):
        rows.append(row("Файлы на резерве", f"скопированы {str(beat['files'].get('at'))[:16]}" if beat["files"].get("ok") else "ошибка копирования",
                        "ok" if beat["files"].get("ok") else "warn"))
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


def toggle(label_on: str, label_off: str, on: bool, method: str, path: str, body_on: dict, body_off: dict, confirm: str = "") -> dict:
    return action(label_off if on else label_on, method, path, body_off if on else body_on, "" if on else confirm)


async def moderation_panel(db: AsyncSession) -> dict:
    from .moderation import get_moderation
    data = await get_moderation(db, None)
    cfg, scan = data["config"], data["scan"]
    rows = [row("Регистрация по приглашениям", "да" if cfg.get("invite_only") else "нет"),
            row("Временные почтовые ящики", "запрещены" if cfg.get("block_disposable", True) else "разрешены"),
            row("Чёрный список", f"Telegram ID {data['blacklist'].get('telegram_ids', 0)}, email {data['blacklist'].get('emails', 0)}, "
                                 f"доменов {data['blacklist'].get('domains', 0)}"),
            row("Заблокировали бота", f"{scan.get('blocked', 0)} (проверено {scan.get('checked', 0)} из {scan.get('total', 0)})"
                if scan else "проверка не запускалась"),
            row("Можно удалить неактивных", data["cleanup_candidates"])]
    base = {"block_disposable": cfg.get("block_disposable", True), "disposable_extra": cfg.get("disposable_extra", []),
            "invite_only": cfg.get("invite_only", False)}
    return {"id": "moderation", "title": "Модерация", "rows": rows, "actions": [
        toggle("Включить регистрацию по приглашениям", "Выключить регистрацию по приглашениям", cfg.get("invite_only", False),
               "PUT", "/api/admin/moderation", {**base, "invite_only": True}, {**base, "invite_only": False},
               "Новые клиенты смогут зарегистрироваться только по приглашению. Включить?"),
        action("Проверить, кто заблокировал бота", "POST", "/api/admin/moderation/blocked-scan"),
        action("Удалить неактивных, заблокировавших бота", "POST", "/api/admin/moderation/blocked-cleanup", None,
               f"Будут закрыты аккаунты: {data['cleanup_candidates']}. Это необратимо. Продолжить?")]}


async def guard_panel(db: AsyncSession) -> dict:
    from .grace_access import get_grace
    from .panel_guard import get_guard
    guard = await get_guard(db, None)
    grace = await get_grace(db, None)
    g, c = guard["config"], grace["config"]
    rows = [row("Техработы при падении панели", "включено" if g["enabled"] else "выключено"),
            row("Сейчас", "техработы включены защитой" if guard["state"].get("active") else "панель отвечает", "bad" if guard["state"].get("active") else "ok"),
            row("Льготный доступ после окончания", f"{c['hours']} ч" if c["enabled"] else "выключен"),
            row("Сейчас в льготном доступе", grace["in_grace"]),
            row("Сброс трафика при оплате", "да" if c.get("reset_traffic_on_payment") else "нет")]
    grace_body = {k: c.get(k) for k in ("enabled", "hours", "cooldown_days", "reset_traffic_on_payment", "mode", "squad")}
    return {"id": "access_guard", "title": "Доступ и защита", "rows": rows, "actions": [
        toggle("Включить техработы при падении панели", "Выключить техработы при падении панели", g["enabled"], "PUT", "/api/admin/panel-guard",
               {**g, "enabled": True}, {**g, "enabled": False}),
        toggle("Включить льготный доступ", "Выключить льготный доступ", c["enabled"], "PUT", "/api/admin/grace",
               {**grace_body, "enabled": True}, {**grace_body, "enabled": False}),
        toggle("Сбрасывать трафик при оплате", "Не сбрасывать трафик при оплате", bool(c.get("reset_traffic_on_payment")), "PUT", "/api/admin/grace",
               {**grace_body, "reset_traffic_on_payment": True}, {**grace_body, "reset_traffic_on_payment": False})]}


async def errors_panel(db: AsyncSession) -> dict:
    from .error_log import list_errors
    data = await list_errors(False, db, None)
    rows = [row("Открытых ошибок", data["open"], "bad" if data["open"] else "ok")]
    for e in data["items"][:5]:
        rows.append(row(f"{e['logger']} ×{e['count']}", e["message"][:160], "warn"))
    return {"id": "errors", "title": "Журнал ошибок", "rows": rows,
            "actions": [action("Отметить все решёнными", "POST", "/api/admin/errors/resolve-all")] if data["open"] else []}


async def growth_panel(db: AsyncSession) -> dict:
    from .daily_billing import enabled as daily_on
    from .guest_checkout import enabled as guest_on
    from .pinned_message import get_pinned
    from .referral_contests import current
    from .support_autoreply import get_autoreply
    contest = await current(db)
    pinned = (await get_pinned(db, None))["message"]
    auto = await get_autoreply(db, None)
    daily, guest = await daily_on(db), await guest_on(db)
    rows = [row("Конкурс рефералов", contest.title if contest else "нет активного"),
            row("Закреплённое сообщение", (pinned.get("progress") or {}).get("sent", 0) if pinned.get("active") else "нет"),
            row("Автоответы поддержки", f"включены, отправлено {auto.get('sent', 0)}" if auto["enabled"] else "выключены"),
            row("Суточные тарифы", "включены" if daily else "выключены"),
            row("Покупка по email без Telegram", "включена" if guest else "выключена")]
    auto_body = {k: auto[k] for k in ("min_score", "use_llm")}
    return {"id": "growth", "title": "Продажи и поддержка", "rows": rows, "actions": [
        toggle("Включить автоответы", "Выключить автоответы", auto["enabled"], "PUT", "/api/admin/support/autoreply",
               {**auto_body, "enabled": True}, {**auto_body, "enabled": False}),
        toggle("Включить суточные тарифы", "Выключить суточные тарифы", daily, "PUT", "/api/admin/daily-billing", {"enabled": True}, {"enabled": False}),
        toggle("Включить покупку по email", "Выключить покупку по email", guest, "PUT", "/api/admin/guest-checkout", {"enabled": True}, {"enabled": False})]
        + ([action("Снять закреплённое сообщение", "DELETE", "/api/admin/pinned-message", None, "Сообщение открепится у всех клиентов. Продолжить?")]
           if pinned.get("active") else [])}


async def quality_panel(db: AsyncSession) -> dict:
    from .connection_quality import admin_quality
    data = await admin_quality(db, None)
    rows = [row("Операторов в отчётах", len(data["carriers"])), row("Проблемных пар", len(data["flagged"]), "bad" if data["flagged"] else "ok")]
    for c in data["flagged"][:6]:
        rows.append(row(f"{c['carrier']} → {c['server']}", f"успешно {int(c['success'] * 100)} % из {c['attempts']}", "bad"))
    return {"id": "connection_quality", "title": "Качество связи", "rows": rows, "actions": []}


async def churn_panel(db: AsyncSession) -> dict:
    from .churn import churn
    data = await churn(db, None)
    rows = [row("Под угрозой ухода", len(data["at_risk"]), "warn" if data["at_risk"] else "ok"),
            row("Автопредложение", f"{data['config']['percent']} %, порог {data['config']['threshold']}" if data["config"]["auto"] else "выключено")]
    actions = []
    for r in data["at_risk"][:5]:
        rows.append(row(f"{r['name']} — {r['score']}", "; ".join(r["reasons"])[:160], "warn"))
        actions.append(action(f"Скидка: {r['name']}", "POST", f"/api/admin/churn/{r['user_id']}/offer", None,
                              f"Отправить персональную скидку {data['config']['percent']} %?"))
    return {"id": "churn", "title": "Риск оттока", "rows": rows, "actions": actions}


async def pnl_panel(db: AsyncSession) -> dict:
    from .pnl import report
    data = await report(db, 2)
    last = data["months"][-1]
    rows = [row("Месяц", last["month"]), row("Выручка", last["revenue"]), row("Комиссии касс", last["fees"]),
            row("Расходы", sum(float(v) for v in last["costs"].values())), row("Реклама", last["ads"]),
            row("Прибыль", last["profit"], "ok" if float(last["profit"]) >= 0 else "bad"),
            row("Прибыль на клиента", data["profit_per_customer"] or "—")]
    return {"id": "pnl", "title": "Прибыль и расходы", "rows": rows, "actions": []}


async def sub_proxy_panel(db: AsyncSession) -> dict:
    from .sub_proxy import get_proxy
    data = await get_proxy(db, None)
    cfg = data["config"]
    day = data["last_24h"]
    rows = [row("Прослойка подписки", "включена" if cfg["enabled"] else "выключена", "ok" if cfg["enabled"] else ""),
            row("Адрес зеркала", cfg.get("public_base") or "не задан"),
            row("Запросов за сутки", sum(day.values())), row("Заглушек устройствам", day.get("blocked", 0)),
            row("Ошибок панели", day.get("error", 0), "bad" if day.get("error") else "ok"),
            row("Заблокировано устройств", len(cfg.get("blocked_hwids") or []))]
    body = {k: v for k, v in cfg.items() if k != "blocked_hwids"}
    actions = [] if not cfg.get("public_base") else [toggle("Включить прослойку", "Выключить прослойку", cfg["enabled"], "PUT", "/api/admin/sub-proxy",
                                                            {**body, "enabled": True}, {**body, "enabled": False},
                                                            "Клиенты начнут получать ссылку подписки на домене зеркала. Включить?")]
    return {"id": "sub_proxy", "title": "Прослойка подписки", "rows": rows, "actions": actions}


async def sessions_panel(db: AsyncSession) -> dict:
    from .vpn_sessions import CONFIG_KEY, DEFAULT, _load, get_anomalies
    cfg = await _load(db, CONFIG_KEY, DEFAULT)
    items = (await get_anomalies(db, None))["anomalies"]
    rows = [row("Сбор сессий", f"каждые {cfg['interval_min']} мин" if cfg["enabled"] else "выключен"),
            row("Аномалий сейчас", len(items), "bad" if any(a["level"] == "red" for a in items) else ("warn" if items else "ok"))]
    for a in items[:6]:
        rows.append(row(f"#{a.get('user_id') or a.get('panel_user')}", "; ".join(f"{h['name']}: {h['value']}" for h in a["hits"]), "bad" if a["level"] == "red" else "warn"))
    actions = [toggle("Включить сбор сессий", "Выключить сбор сессий", cfg["enabled"], "PUT", "/api/admin/sessions/config",
                      {**cfg, "enabled": True}, {**cfg, "enabled": False})]
    actions += [action(f"Сбросить соединения #{a['user_id']}", "POST", f"/api/admin/users/{a['user_id']}/drop-connections", None,
                       "Все соединения клиента будут разорваны. Продолжить?") for a in items[:3] if a.get("user_id")]
    return {"id": "sessions", "title": "Сессии и аномалии", "rows": rows, "actions": actions}


async def panel_api_panel(db: AsyncSession) -> dict:
    from .panel_api_stats import flush, report
    await flush(db)
    data = await report(db, 24)
    rows = [row("Запросов к панели за сутки", data["total"]),
            row("Ошибок", data["errors"], "bad" if data["total"] and data["errors"] * 20 > data["total"] else "ok"),
            row("Пиковый час", f"{data['peak_hour'][11:16] or '—'} — {data['peak_calls']}")]
    rows += [row(s["source"], f"{s['calls']} · {s['avg_ms']} мс") for s in data["sources"][:5]]
    return {"id": "panel_api", "title": "Запросы к панели", "rows": rows, "actions": []}


BUILDERS = [payment_methods_panel, hot_standby_panel, autoscale_panel, block_monitor_panel, moderation_panel, guard_panel,
            errors_panel, growth_panel, quality_panel, churn_panel, pnl_panel, sub_proxy_panel, sessions_panel, panel_api_panel]


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
