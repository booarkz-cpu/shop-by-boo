"""«Серверы → Сверка с панелью»: what the shop set on the Remnawave panel against what the panel has now.

The shop changes a few things on the panel on the administrator's behalf — the auto-selection pool (``rw_autoselect``)
and the temporary torrent ban (``rw_torrent_ban``) — and remembers what it set. The panel can be edited by hand
afterwards, a node can be re-created, a host deleted. This page reads the panel, compares it with what was set, and
lists every difference with the place where it is put right. Nothing is changed here.

The last check and the last check without differences are kept (``rw.drift``), so the page says how fresh the answer is
even when the panel is unreachable.
"""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import require_permission

router = APIRouter(prefix="/api/admin/rw/drift")
STATE_KEY = "rw.drift"
DEFAULT = {"checked_at": None, "ok_at": None, "items": [], "error": None}

__all__ = ["router", "compare", "pool_drift", "ban_drift"]


def _item(area: str, obj: str, expected: str, actual: str, tab: str) -> dict:
    return {"area": area, "object": obj, "expected": expected, "actual": actual, "tab": tab}


def pool_drift(pool: dict | None) -> list[dict]:
    """Differences of the auto-selection pool; ``pool`` is ``rw_autoselect.pool_view``."""
    if not pool or not pool.get("enabled"):
        return []
    area, tab, items = "Автовыбор", "autoselect", []
    tile = pool.get("tile") or {}
    if not tile.get("exists"):
        items.append(_item(area, "Плитка «" + str(pool.get("name")) + "»", "есть в подписке", "удалена на панели", tab))
    elif not tile.get("visible"):
        items.append(_item(area, "Плитка «" + str(tile.get("name") or pool.get("name")) + "»", "видна клиентам", "скрыта или выключена на панели", tab))
    for uuid in (pool.get("stats") or {}).get("missing") or []:
        items.append(_item(area, f"Сервер пула {uuid}", "есть на панели", "удалён на панели", tab))
    for host in pool.get("hosts") or []:
        if host.get("in_pool") and host.get("disabled"):
            items.append(_item(area, f"Сервер пула «{host.get('name')}»", "включён", "выключен на панели", tab))
    return items


def ban_drift(desired: dict | None, ban: dict | None) -> list[dict]:
    """Differences of the temporary torrent ban; ``ban`` is ``rw_torrent_ban.view``."""
    wanted = (desired or {}).get("nodes") or {}
    if not wanted or ban is None:
        return []
    area, tab, items = "Бан за торренты", "torrents", []
    rows = {row.get("uuid"): row for row in ban.get("nodes") or []}
    for uuid, want in sorted(wanted.items(), key=lambda kv: str(kv[1].get("name"))):
        name, row = f"Нода «{want.get('name') or uuid}»", rows.get(uuid)
        if row is None:
            items.append(_item(area, name, f"бан на {want.get('minutes')} мин.", "ноды нет на панели", tab))
        elif not row.get("ban"):
            items.append(_item(area, name, f"бан на {want.get('minutes')} мин.", "бан выключен на панели", tab))
        elif row.get("minutes") != want.get("minutes"):
            items.append(_item(area, name, f"бан на {want.get('minutes')} мин.", f"бан на {row.get('minutes')} мин.", tab))
    return items


def compare(pool: dict | None, ban_desired: dict | None, ban: dict | None) -> list[dict]:
    return [*pool_drift(pool), *ban_drift(ban_desired, ban)]


def remember(previous: dict, items: list[dict] | None, error: str | None, now: datetime | None = None) -> dict:
    """The stored state after a check. A failed check keeps the last known differences and says that it failed."""
    stamp = (now or datetime.now(UTC)).isoformat(timespec="seconds")
    if error is not None:
        return {**DEFAULT, **previous, "error": error, "failed_at": stamp}
    return {"checked_at": stamp, "ok_at": stamp if not items else previous.get("ok_at"), "items": items, "error": None, "failed_at": None}


async def read_panel(db: AsyncSession) -> tuple[dict | None, dict, dict | None]:
    """Seam for tests: the pool view, the remembered ban and the ban view, read from the panel now."""
    from . import rw_autoselect, rw_torrent_ban
    from .node_health import _load

    config = await rw_autoselect._config(db)
    pool = None
    if config.get("enabled"):
        hosts, nodes, json_at_base = await rw_autoselect._panel_state()
        pool = rw_autoselect.pool_view(config, hosts, nodes, json_at_base)
    desired = await _load(db, rw_torrent_ban.DESIRED_KEY, {"nodes": {}})
    ban = None
    if desired.get("nodes"):
        nodes = rw_torrent_ban._list(await rw_torrent_ban._panel("GET", "/api/nodes"), "nodes")
        plugins = rw_torrent_ban._list(await rw_torrent_ban._panel("GET", "/api/node-plugins"), "nodePlugins")
        ban = rw_torrent_ban.view(nodes, plugins, None, None)
    return pool, desired, ban


def _view(state: dict, watched: dict) -> dict:
    return {"checked_at": state.get("checked_at"), "ok_at": state.get("ok_at"), "error": state.get("error"),
            "failed_at": state.get("failed_at"), "items": state.get("items") or [], "watched": watched,
            "in_sync": state.get("checked_at") is not None and not state.get("items") and not state.get("error")}


async def _watched(db: AsyncSession) -> dict:
    from . import rw_autoselect, rw_torrent_ban
    from .node_health import _load

    config = await rw_autoselect._config(db)
    desired = await _load(db, rw_torrent_ban.DESIRED_KEY, {"nodes": {}})
    return {"autoselect": bool(config.get("enabled")), "torrent_ban_nodes": len(desired.get("nodes") or {})}


EVERY_HOURS = 6


def due(state: dict, now: datetime) -> bool:
    """The scheduled check: every six hours, counted from the last attempt, successful or not."""
    stamps = [state.get("checked_at"), state.get("failed_at")]
    last = max((datetime.fromisoformat(s) for s in stamps if s), default=None)
    return last is None or (now - last).total_seconds() >= EVERY_HOURS * 3600


def news(previous: dict, items: list[dict]) -> list[dict]:
    """Differences that were not in the previous answer: only these are worth a message."""
    seen = {(i.get("area"), i.get("object"), i.get("actual")) for i in previous.get("items") or []}
    return [i for i in items if (i.get("area"), i.get("object"), i.get("actual")) not in seen]


async def tick(db: AsyncSession, now: datetime | None = None) -> dict | None:
    """Called by the worker every minute; checks when due and tells the administrators about a new difference."""
    from .node_health import _load, _save

    now = now or datetime.now(UTC)
    previous = await _load(db, STATE_KEY, DEFAULT)
    watched = await _watched(db)
    if not (watched["autoselect"] or watched["torrent_ban_nodes"]) or not due(previous, now):
        return None
    try:
        items, error = compare(*await read_panel(db)), None
    except HTTPException as exc:
        items, error = None, str(exc.detail)[:300]
    state = remember(previous, items, error, now)
    await _save(db, STATE_KEY, state)
    await db.commit()
    fresh = news(previous, items or [])
    if fresh:
        from .rw_autoupdate import _notify
        lines = "\n".join(f"• {i['area']}: {i['object']} — {i['actual']}" for i in fresh[:10])
        await _notify(f"Панель Remnawave отличается от настроек магазина ({len(fresh)}):\n{lines}\n"
                      "Подробности: «Расширения Remnawave» → «Сверка с панелью».")
    return state


@router.get("/meta")
async def meta(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("read"))):
    """The last check, without asking the panel."""
    from .node_health import _load

    return _view(await _load(db, STATE_KEY, DEFAULT), await _watched(db))


@router.post("/check")
async def check(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("read"))):
    """Reads the panel now, compares and remembers the answer."""
    from .node_health import _load, _save

    previous = await _load(db, STATE_KEY, DEFAULT)
    try:
        items, error = compare(*await read_panel(db)), None
    except HTTPException as exc:
        items, error = None, str(exc.detail)[:300]
    state = remember(previous, items, error)
    await _save(db, STATE_KEY, state)
    await db.commit()
    return _view(state, await _watched(db))
