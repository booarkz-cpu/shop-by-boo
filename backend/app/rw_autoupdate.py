"""Автообновление Remnawave (v28.74.0, этап 15): панель, ноды и страница подписки — из админки.

Что ставится. Только образы, закреплённые в ``rw_plan.IMAGES`` по digest: каждый выпуск магазина ставит их в CI
на настоящую панель и ноду (tests/live/test_install_live.py, test_node_modules_live.py) — это и есть проверка
совместимости перед установкой. Новый релиз Remnawave на GitHub показывается сразу, а ставится после того, как
выпуск магазина закрепит и проверит его (ночное автообновление магазина приносит новые digest сюда).

Как ставится. Обычным действием «Обновить» мастера установки (``rw_plan.build_action("update")``): копия базы
панели → файлы с SHA-256 → ``compose up`` закреплённых образов → ``/health`` панели → проверка HTTPS, связи нод
и страницы подписки. При сбое — откат: прежние файлы, контейнеры с ними и база панели из копии этого обновления
(``rw_jobs._rollback``). Ночной запуск ставит план в очередь сам: включив автообновление, администратор
заранее согласился с этим действием; план и журнал шагов видны в «Установке Remnawave», как у ручного.

Состояние — в ``app_settings``: ``rw.autoupdate`` (включено, время МСК, какие установки, уведомления) и
``rw.autoupdate.state`` (дата последнего ночного запуска, наблюдаемые запуски, известные релизы GitHub)."""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import rw_plan
from .db import get_db
from .models import RemnawaveDeploymentStep, RemnawaveInstallation, RemnawaveServer
from .security import require_permission, require_stepup

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin/remnawave/auto-update")
KEY, STATE_KEY = "rw.autoupdate", "rw.autoupdate.state"
DEFAULT = {"enabled": False, "time": "04:30", "installation_ids": [], "notify": True}
MSK = ZoneInfo("Europe/Moscow")
ACTOR = "auto-update"
WINDOW = timedelta(hours=2)  # a worker restarted at 04:40 still runs the 04:30 update
UPSTREAM_EVERY = timedelta(hours=6)
DEPLOYING = ("install", "update", "reinstall")
FINAL = ("succeeded", "failed", "cancelled")
VERSION = re.compile(r"^v?(\d{1,4})\.(\d{1,4})\.(\d{1,4})$")

__all__ = ["router", "overview", "scheduler", "tick", "outdated", "schedule_update"]


class SettingsIn(BaseModel):
    enabled: bool
    time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    installation_ids: list[int] = Field(default_factory=list, max_length=50)
    notify: bool = True


class RunIn(BaseModel):
    installation_ids: list[int] = Field(min_length=1, max_length=50)


async def _load(db: AsyncSession, key: str, default: dict) -> dict:
    from .node_health import _load as load
    return await load(db, key, default)


async def _save(db: AsyncSession, key: str, value: dict) -> None:
    from .node_health import _save as save
    await save(db, key, value)


def _version(text) -> tuple[int, ...] | None:
    m = VERSION.match(str(text or "").strip())
    return tuple(int(x) for x in m.groups()) if m else None


def newer(candidate, than) -> bool:
    a, b = _version(candidate), _version(than)
    return bool(a and b and a > b)


def relevant_images(params: dict) -> set[str]:
    """Which of ``rw_plan.IMAGES`` an installation runs, by its roles."""
    plan = rw_plan.PlanIn(**params)
    roles = {r for rs in rw_plan.roles_of(plan).values() for r in rs}
    keys: set[str] = set()
    if "panel" in roles:
        keys |= {"panel", "postgres", "valkey", "caddy"}
    if "subscription_page" in roles:
        keys |= {"subscription_page", "caddy"}
    if "node" in roles:
        keys.add("node")
        if plan.selfsteal_domain:
            keys.add("caddy")
    return keys


async def _chain(db: AsyncSession, source: RemnawaveInstallation) -> list[RemnawaveInstallation]:
    rows = (await db.execute(select(RemnawaveInstallation).where(RemnawaveInstallation.source_installation_id == source.id)
                             .order_by(RemnawaveInstallation.id))).scalars().all()
    return [source, *rows]


async def installations(db: AsyncSession) -> list[dict]:
    """Successful installations still in place, with what they run and what is out of date."""
    out = []
    rows = (await db.execute(select(RemnawaveInstallation).where(RemnawaveInstallation.action == "install",
                                                                 RemnawaveInstallation.status == "succeeded")
                             .order_by(RemnawaveInstallation.id))).scalars().all()
    for source in rows:
        chain = await _chain(db, source)
        done = [r for r in chain if r.status == "succeeded" and r.action in (*DEPLOYING, "remove")]
        if done and done[-1].action == "remove":
            continue
        deployed = dict((done[-1].plan or {}).get("images") or {}) if done else {}
        keys = relevant_images(source.params)
        stale = sorted(k for k in keys if deployed.get(k) != rw_plan.IMAGES.get(k))
        updates = [r for r in chain if r.action == "update"]
        last = updates[-1] if updates else None
        servers = []
        for sid in source.server_ids:
            server = await db.get(RemnawaveServer, sid)
            servers.append({"id": sid, "name": server.name if server else f"#{sid}", "host": server.host if server else None})
        out.append({"id": source.id, "mode": source.mode, "title": rw_plan.MODE_TITLES.get(source.mode, source.mode),
                    "servers": servers, "components": sorted(keys), "outdated": stale,
                    "busy": any(r.status in ("queued", "running") for r in chain[1:]),
                    "last_update": _row(last) if last else None})
    return out


def _row(r: RemnawaveInstallation) -> dict:
    return {"id": r.id, "source_id": r.source_installation_id, "status": r.status, "error": r.error, "created_by": r.created_by,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None, "automatic": r.created_by == ACTOR}


async def history(db: AsyncSession, limit: int = 30) -> list[dict]:
    rows = (await db.execute(select(RemnawaveInstallation).where(RemnawaveInstallation.action == "update")
                             .order_by(RemnawaveInstallation.id.desc()).limit(limit))).scalars().all()
    out = []
    for r in rows:
        item = _row(r)
        steps = (await db.execute(select(RemnawaveDeploymentStep.status).where(RemnawaveDeploymentStep.installation_id == r.id))).scalars().all()
        item["rolled_back"] = "rolled_back" in steps
        out.append(item)
    return out


async def outdated(db: AsyncSession, ids: list[int] | None = None) -> list[dict]:
    wanted = set(ids or [])
    return [i for i in await installations(db) if i["outdated"] and not i["busy"] and (not wanted or i["id"] in wanted)]


async def schedule_update(db: AsyncSession, source_id: int, actor: str, action: str = "update") -> RemnawaveInstallation:
    """The «update» plan of an installation, queued at once (the same plan an administrator approves by hand).
    v28.92.0: also «snapshot» for the daily snapshots of «Установка» (rw_snapshots)."""
    from . import rw_api
    from .main import audit

    source = await db.get(RemnawaveInstallation, source_id)
    if not source or source.action != "install" or source.status != "succeeded":
        raise HTTPException(409, "Обновляется только успешно завершённая установка")
    servers = await rw_api._servers_for(db, source.server_ids)
    busy = await rw_api._busy(db, source.server_ids)
    if busy:
        raise HTTPException(409, f"На серверах {busy} уже идёт другая установка")
    params = dict(source.params)
    try:
        plan = rw_plan.build_action(action, rw_plan.PlanIn(**params), servers)
    except ValueError as exc:
        raise HTTPException(409, f"План обновления не составлен: {exc}") from exc
    row = RemnawaveInstallation(action=action, mode=source.mode, server_ids=source.server_ids, params=params, plan=plan,
                                plan_sha256=rw_plan.plan_hash(plan, params), status="queued", secrets=source.secrets,
                                result={"state": (source.result or {}).get("state") or {}}, source_installation_id=source.id,
                                created_by=actor, approved_by=actor)
    db.add(row)
    await db.flush()
    for st in plan["steps"]:
        db.add(RemnawaveDeploymentStep(installation_id=row.id, server_id=st["server_id"], position=st["position"], kind=st["kind"],
                                       title=st["title"][:200], params=st["params"], status="pending"))
    await audit(db, f"rw.{'autoupdate' if action == 'update' else action}.queued", actor, str(row.id), {"source": source.id, "images": plan["images"]})
    return row  # the worker's loop (rw_jobs.installer_worker) picks the queued row up


# ---------- releases on GitHub ----------

async def fetch_upstream() -> dict:
    """Latest release tags of the panel, the node and the subscription page (seam for tests)."""
    from . import rw_releases
    out = {}
    for comp, repo in rw_plan.UPSTREAM.items():
        try:
            out[comp] = {"latest": (await rw_releases.fetch(repo, None)).get("tag_name"), "error": None}
        except rw_releases.ReleaseError as exc:
            out[comp] = {"latest": None, "error": str(exc)}
    return out


def upstream_view(cached: dict) -> dict:
    view = {}
    for comp, verified in rw_plan.VERSIONS.items():
        got = (cached.get("releases") or {}).get(comp) or {}
        latest = got.get("latest")
        view[comp] = {"repo": rw_plan.UPSTREAM[comp], "verified": verified, "latest": latest, "error": got.get("error"),
                      "newer": newer(latest, verified)}
    return {"checked_at": cached.get("checked_at"), "components": view}


async def panel_version() -> dict:
    """The panel the shop is connected to (REMNAWAVE_URL) against the version the shop's CI verified."""
    from .remnawave import RemnawaveClient, RemnawaveNotConfigured
    verified = rw_plan.VERSIONS["panel"]
    try:
        data = await asyncio.wait_for(RemnawaveClient()._request("GET", "/api/system/metadata"), 10)
    except RemnawaveNotConfigured:
        return {"status": "not_connected", "version": None, "verified": verified}
    except Exception as exc:  # noqa: BLE001 — shown as «нет ответа»
        return {"status": "unreachable", "version": None, "verified": verified, "error": type(exc).__name__}
    version = str((data or {}).get("version") or "").strip() or None
    if not _version(version):
        status = "unknown"
    elif version.lstrip("v") == verified:
        status = "verified"
    elif newer(version, verified):
        status = "newer"  # the panel is ahead of what the shop tested: watch the shop's next release
    else:
        status = "older"
    return {"status": status, "version": version, "verified": verified}


# ---------- the nightly run ----------

async def _notify(text: str) -> None:
    from . import main
    try:
        await main.send_alert(text)
    except Exception:  # noqa: BLE001 — a notification never stops an update
        logger.warning("auto-update notification failed")


def due(cfg: dict, state: dict, now: datetime) -> bool:
    local = now.astimezone(MSK)
    hh, mm = (int(x) for x in cfg["time"].split(":"))
    start = local.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return cfg["enabled"] and start <= local < start + WINDOW and state.get("last_run_date") != local.date().isoformat()


async def tick(db: AsyncSession, now: datetime | None = None) -> dict:
    """One pass of the scheduler: GitHub releases every 6 hours, the nightly update, outcomes of watched runs."""
    now = now or datetime.now(timezone.utc)
    cfg = await _load(db, KEY, DEFAULT)
    state = await _load(db, STATE_KEY, {"last_run_date": None, "watch": [], "announced": {}, "releases": {}, "checked_at": None})
    report = {"queued": [], "finished": [], "announced": []}
    checked = datetime.fromisoformat(state["checked_at"]) if state.get("checked_at") else None
    if checked is None or now - checked >= UPSTREAM_EVERY:
        state["releases"] = await fetch_upstream()
        state["checked_at"] = now.replace(microsecond=0).isoformat()
        for comp, item in upstream_view(state)["components"].items():
            if item["newer"] and state["announced"].get(comp) != item["latest"]:
                state["announced"][comp] = item["latest"]
                report["announced"].append(comp)
                if cfg["notify"]:
                    await _notify(f"Вышла {item['repo']} {item['latest']} (в магазине проверена {item['verified']}). "
                                  "Обновление на серверах — после выпуска магазина, который проверит эту версию в CI.")
    if due(cfg, state, now):
        state["last_run_date"] = now.astimezone(MSK).date().isoformat()
        for item in await outdated(db, cfg["installation_ids"]):
            try:
                row = await schedule_update(db, item["id"], ACTOR)
            except HTTPException as exc:
                if cfg["notify"]:
                    await _notify(f"Автообновление Remnawave: установка #{item['id']} пропущена — {exc.detail}")
                continue
            state["watch"].append(row.id)
            report["queued"].append(row.id)
        if report["queued"] and cfg["notify"]:
            await _notify(f"Автообновление Remnawave запущено: {len(report['queued'])} установок, "
                          "копия базы панели перед обновлением, откат при сбое.")
    still = []
    for rid in state.get("watch") or []:
        row = await db.get(RemnawaveInstallation, rid)
        if row is None:
            continue
        if row.status not in FINAL:
            still.append(rid)
            continue
        report["finished"].append(rid)
        if cfg["notify"]:
            text = ("обновлена" if row.status == "succeeded" else f"не обновлена, изменения откатаны: {(row.error or '')[:300]}")
            await _notify(f"Автообновление Remnawave: установка #{row.source_installation_id} {text}")
    state["watch"] = still
    await _save(db, STATE_KEY, state)
    await db.commit()
    return report


async def scheduler() -> None:
    """Runs in the worker. A Redis lock keeps two workers from queueing the same night twice."""
    from . import main
    from .db import SessionLocal
    while True:
        try:
            lock = await main.redis_client.set("lock:rw-autoupdate", "1", nx=True, ex=55) if main.redis_client else True
            if lock:
                async with SessionLocal() as db:
                    await tick(db)
                from . import rw_snapshots
                async with SessionLocal() as db:
                    await rw_snapshots.tick(db)
        except Exception:
            logger.exception("Remnawave auto-update pass failed")
        await asyncio.sleep(60)


# ---------- copies of the panel's database kept by the shop ----------

COPY_NAME = re.compile(r"^panel-\d{1,9}-\d{8}T\d{6}Z\.dump\.enc$")


def panel_copies(limit: int = 30) -> list[dict]:
    from .rw_steps import panel_copies_dir
    folder = panel_copies_dir()
    if not folder.is_dir():
        return []
    files = sorted((f for f in folder.glob("panel-*.dump.enc") if COPY_NAME.match(f.name)), key=lambda f: f.name, reverse=True)
    return [{"name": f.name, "server_id": int(f.name.split("-")[1]), "size": f.stat().st_size,
             "created_at": datetime.strptime(f.name.split("-")[2][:16], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).isoformat()}
            for f in files[:limit]]


# ---------- API ----------

async def overview(db: AsyncSession, with_panel: bool = True) -> dict:
    cfg = await _load(db, KEY, DEFAULT)
    state = await _load(db, STATE_KEY, {})
    nxt = None
    if cfg["enabled"]:
        local = datetime.now(timezone.utc).astimezone(MSK)
        hh, mm = (int(x) for x in cfg["time"].split(":"))
        nxt = local.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if nxt <= local or state.get("last_run_date") == local.date().isoformat():
            nxt += timedelta(days=1)
        nxt = nxt.isoformat()
    return {"settings": cfg, "timezone": "Europe/Moscow", "next_run": nxt, "last_run_date": state.get("last_run_date"),
            "verified": rw_plan.VERSIONS, "upstream": upstream_view(state),
            "panel": await panel_version() if with_panel else None,
            "installations": await installations(db), "history": await history(db), "panel_copies": panel_copies()}


@router.get("")
async def get_auto_update(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("ops.releases"))):
    return await overview(db)


@router.put("")
async def put_auto_update(payload: SettingsIn, db: AsyncSession = Depends(get_db),
                          admin=Depends(require_permission("provision_nodes"))):
    from .main import audit
    known = {i["id"] for i in await installations(db)}
    unknown = sorted(set(payload.installation_ids) - known)
    if unknown:
        raise HTTPException(422, f"Нет таких действующих установок: {unknown}")
    await _save(db, KEY, payload.model_dump())
    await audit(db, "rw.autoupdate.settings", admin.email, None, payload.model_dump())
    await db.commit()
    return await overview(db, with_panel=False)


@router.post("/run")
async def run_now(payload: RunIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("provision_nodes"))):
    """«Обновить сейчас» для выбранных установок (панель, ноды): тот же план, сразу в очередь."""
    queued = []
    for iid in payload.installation_ids:
        row = await schedule_update(db, iid, admin.email)
        queued.append(row.id)
    state = await _load(db, STATE_KEY, {"watch": []})
    state["watch"] = [*(state.get("watch") or []), *queued]
    await _save(db, STATE_KEY, state)
    await db.commit()
    return {"queued": queued, **await overview(db, with_panel=False)}


@router.post("/check")
async def check_releases(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("ops.releases"))):
    """Проверить релизы на GitHub сейчас (без ожидания шестичасовой проверки)."""
    state = await _load(db, STATE_KEY, {})
    state["releases"] = await fetch_upstream()
    state["checked_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    await _save(db, STATE_KEY, state)
    await db.commit()
    return await overview(db)


@router.get("/panel-copies/{name}")
async def download_panel_copy(name: str, db: AsyncSession = Depends(get_db), admin=Depends(require_stepup("backups.write"))):
    """Копия базы панели, расшифрованная (формат pg_dump -Fc): восстановить — pg_restore на сервере панели."""
    from .main import audit
    from .rw_steps import panel_copies_dir, unseal
    if not COPY_NAME.match(name):
        raise HTTPException(404, "Нет такой копии")
    path = panel_copies_dir() / name
    if not path.is_file():
        raise HTTPException(404, "Нет такой копии")
    try:
        data = unseal(path.read_bytes())
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    await audit(db, "rw.panel_copy.downloaded", admin.email, name, {"size": len(data)})
    await db.commit()
    return Response(data, media_type="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{name.removesuffix(".enc")}"'})
