"""Automation Center (v28.74.0, этап 15): всё, что магазин делает сам, на одном экране.

``GET /api/admin/automation-center`` — только чтение. Для каждого автоматического процесса: включён ли он,
когда сработает, чем кончился последний запуск и где он настраивается (``tab``). Сводка «Состояния системы»
(``system_status.collect``) — там же, чтобы по одному экрану было видно и автоматику, и здоровье частей.

Статусы: ``ok`` — работает; ``warn`` — работает, но требует внимания; ``error`` — не работает;
``off`` — выключено или не настроено (ничего не сломано, функция не используется)."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .models import BackupJob, WorkerState
from .security import require_permission

router = APIRouter()
WORKER_FRESH = timedelta(minutes=2)
BACKUP_TITLES = {"off": "выключены", "6h": "каждые 6 часов", "12h": "каждые 12 часов", "24h": "каждые 24 часа"}

__all__ = ["router", "processes", "item"]


def item(key: str, name: str, status: str, detail: str, tab: str, *, schedule: str | None = None,
         last_run: str | None = None) -> dict:
    return {"key": key, "name": name, "status": status, "detail": detail, "tab": tab, "schedule": schedule, "last_run": last_run}


def _iso(moment) -> str | None:
    return moment.isoformat() if moment else None


def shop_update() -> dict:
    from .auto_update_api import read_state
    st = read_state()
    s = st["status"]
    if not st["available"]:
        return item("shop_update", "Автообновление магазина", "off", "Агент на сервере не установлен: " + (st["setup_hint"] or ""),
                    "releases")
    if not st["agent_alive"]:
        return item("shop_update", "Автообновление магазина", "error", "Агент не отвечает больше 5 минут", "releases")
    if not s.get("enabled"):
        return item("shop_update", "Автообновление магазина", "off", f"Выключено. Установлена {s.get('installed') or '—'}", "releases")
    status = "warn" if s.get("last_result") == "failed" or s.get("recovery_mode") else "ok"
    detail = f"Установлена {s.get('installed') or '—'}, на GitHub {s.get('latest') or '—'}"
    if s.get("last_result") == "failed":
        detail += f". Последний запуск не удался, выполнен откат ({s.get('failed_release') or '—'})"
    return item("shop_update", "Автообновление магазина", status, detail, "releases",
                schedule=f"каждую ночь в {s.get('time') or '—'} МСК", last_run=s.get("last_run_at"))


def rw_update(ov: dict) -> list[dict]:
    cfg = ov["settings"]
    stale = [i for i in ov["installations"] if i["outdated"]]
    last = ov["history"][0] if ov["history"] else None
    if not ov["installations"]:
        main = item("rw_update", "Автообновление Remnawave", "off", "Нет установок мастера: обновлять нечего", "releases")
    elif not cfg["enabled"]:
        main = item("rw_update", "Автообновление Remnawave", "off" if not stale else "warn",
                    f"Выключено. Требуют обновления: {len(stale)} из {len(ov['installations'])}", "releases")
    else:
        status = "warn" if last and last["status"] == "failed" else "ok"
        detail = f"Требуют обновления: {len(stale)} из {len(ov['installations'])}"
        if last:
            detail += f". Последнее обновление #{last['id']}: {last['status']}" + (" (откат)" if last.get("rolled_back") else "")
        main = item("rw_update", "Автообновление Remnawave", status, detail, "releases",
                    schedule=f"каждую ночь в {cfg['time']} МСК", last_run=last["finished_at"] if last else None)
    comps = ov["upstream"]["components"]
    ahead = [f"{c['repo']} {c['latest']}" for c in comps.values() if c["newer"]]
    errors = [c["error"] for c in comps.values() if c["error"]]
    if errors and not ov["upstream"]["checked_at"]:
        rel = item("rw_releases", "Релизы Remnawave на GitHub", "off", "Ещё не проверялись", "releases", schedule="каждые 6 часов")
    elif errors:
        rel = item("rw_releases", "Релизы Remnawave на GitHub", "warn", f"GitHub не ответил: {errors[0]}", "releases",
                   schedule="каждые 6 часов", last_run=ov["upstream"]["checked_at"])
    else:
        rel = item("rw_releases", "Релизы Remnawave на GitHub", "warn" if ahead else "ok",
                   ("Новее проверенных: " + ", ".join(ahead) + ". Встанут после выпуска магазина, который их проверит")
                   if ahead else "Проверенные магазином версии — последние", "releases",
                   schedule="каждые 6 часов", last_run=ov["upstream"]["checked_at"])
    return [main, rel]


def panel_item(p: dict) -> dict:
    texts = {"verified": ("ok", f"Подключённая панель {p['version']} — проверена в CI магазина"),
             "newer": ("warn", f"Панель {p['version']} новее проверенной {p['verified']}: проверьте работу после её обновления"),
             "older": ("warn", f"Панель {p['version']} старше проверенной {p['verified']}: обновите её"),
             "unknown": ("warn", "Панель не сообщила версию"),
             "unreachable": ("error", "Панель не отвечает"),
             "not_connected": ("off", "Магазин не подключён к панели")}
    status, detail = texts[p["status"]]
    return item("rw_panel", "Версия Remnawave", status, detail, "remnawave")


async def backups(db: AsyncSession) -> dict:
    from . import main as shop
    from .backups_api import DEFAULT_SCHEDULE
    schedule = await shop.setting_value(db, "backup_schedule", DEFAULT_SCHEDULE)
    last = (await db.execute(select(BackupJob).order_by(BackupJob.created_at.desc()).limit(1))).scalar_one_or_none()
    ok = (await db.execute(select(BackupJob).where(BackupJob.status == "completed").order_by(BackupJob.created_at.desc())
                           .limit(1))).scalar_one_or_none()
    interval = shop.BACKUP_INTERVALS.get(schedule, 0)
    if not interval:
        return item("backups", "Резервные копии", "off", "Расписание выключено", "backups", schedule=BACKUP_TITLES.get(schedule, schedule),
                    last_run=_iso(ok.created_at) if ok else None)
    late = not ok or (datetime.utcnow() - ok.created_at).total_seconds() > interval * 1.5
    failed = bool(last and last.status == "failed")
    status = "error" if late and failed else "warn" if late or failed else "ok"
    detail = f"Последняя успешная: {ok.created_at:%Y-%m-%d %H:%M} UTC" if ok else "Успешных копий ещё нет"
    if failed:
        detail += f". Последний запуск не удался: {(last.error or '')[:160]}"
    return item("backups", "Резервные копии", status, detail, "backups", schedule=BACKUP_TITLES.get(schedule, schedule),
                last_run=_iso(last.created_at) if last else None)


async def workers(db: AsyncSession) -> dict:
    fresh = datetime.utcnow() - WORKER_FRESH
    alive = int(await db.scalar(select(func.count()).select_from(WorkerState).where(WorkerState.last_seen_at >= fresh)) or 0)
    seen = await db.scalar(select(func.max(WorkerState.last_seen_at)))
    if not alive:
        return item("workers", "Фоновый обработчик (worker)", "error",
                    "Ни один worker не отвечает: расписания, автообновления и копии не выполняются", "workers", last_run=_iso(seen))
    return item("workers", "Фоновый обработчик (worker)", "ok", f"На связи: {alive}", "workers", schedule="постоянно",
                last_run=_iso(seen))


def alerts() -> dict:
    from .config import settings
    channels = [x for x, on in (("Telegram", settings.alert_telegram_chat_id and settings.bot_token),
                               ("почта", settings.smtp_host and settings.alert_email)) if on]
    if not channels:
        return item("alerts", "Оповещения о сбоях", "off", "Не настроены: укажите чат Telegram или почту для оповещений", "opsReadiness")
    return item("alerts", "Оповещения о сбоях", "ok", "Куда: " + ", ".join(channels), "opsReadiness", schedule="при событии")


async def processes(db: AsyncSession) -> list[dict]:
    from . import rw_autoupdate
    out = [shop_update()]
    ov = await rw_autoupdate.overview(db, with_panel=False)
    out += rw_update(ov)
    out.append(panel_item(await rw_autoupdate.panel_version()))
    out += [await backups(db), await workers(db), alerts()]
    return out


async def health(db: AsyncSession) -> dict:
    from . import main as shop
    from . import system_status
    from .release_identity import DISTRIBUTION_TAG
    paused = not await shop.production_payments_allowed(db)
    checks = await asyncio.wait_for(system_status.collect(db, version=shop.APP_VERSION, distribution=DISTRIBUTION_TAG,
                                                          redis_client=shop.redis_client, remnawave_factory=shop.RemnawaveClient,
                                                          payments_paused=paused), 30)
    counts: dict[str, int] = {}
    for c in checks:
        counts[c["status"]] = counts.get(c["status"], 0) + 1
    return {"status": system_status.overall(checks), "counts": counts,
            "attention": [{k: c.get(k) for k in ("key", "name", "status", "detail", "tab")} for c in checks if c["status"] in ("warn", "error")]}


@router.get("/api/admin/automation-center")
async def automation_center(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("ops.diagnostics"))):
    items = await processes(db)
    try:
        summary = await health(db)
    except Exception as exc:  # noqa: BLE001 — one slow part never hides the automation list
        summary = {"status": "error", "counts": {}, "attention": [], "error": type(exc).__name__}
    worst = "error" if any(i["status"] == "error" for i in items) else "warn" if any(i["status"] == "warn" for i in items) else "ok"
    return {"status": worst, "processes": items, "health": summary, "checked_at": datetime.utcnow().isoformat()}
