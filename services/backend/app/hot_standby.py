"""Hot standby: a second server with a streaming copy of the database, ready to take over.

The database part is PostgreSQL streaming replication set up by ``scripts/hot-standby.sh`` (TLS, a replication-only
role, the port open to the standby's address only). On the standby a small agent (``scripts/standby-agent.py``,
standard library, a systemd timer every minute) reports here how far behind it is and whether it still sees the
primary; when the primary stops answering for ``fail_limit`` minutes in a row it alerts in Telegram and — only if
the owner turned that on — promotes itself and points the DNS records to its address (Cloudflare).

This module is the primary's side: what the owner sees in «Резервные копии → Горячий резерв»:

* replication straight from PostgreSQL (``pg_stat_replication``, replication slots) — is the standby streaming,
  how big is the lag, is WAL piling up for a lost standby;
* the agent's last heartbeat;
* alerts (ops_alerts) when the standby is expected but not streaming, falls behind or stops reporting.

Split brain is the real risk of automatic promotion: if the primary is only cut off from the standby, both would
accept writes. That is why auto promotion is off by default, needs the primary to be silent on every path (its public
address, TCP to its IP, the replication stream), and why the returning old primary must be demoted (``hot-standby.sh demote``) before it starts again.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import require_permission

logger = logging.getLogger("vpnshop.hot_standby")
router = APIRouter()

CONFIG_KEY = "standby.config"
HEARTBEAT_KEY = "standby.heartbeat"
DEFAULT_CONFIG = {"enabled": False, "lag_alert_seconds": 300, "token_sha": ""}
STALE_HEARTBEAT = timedelta(minutes=10)
SLOT_ALERT_BYTES = 5 * 1024 ** 3  # WAL kept for a standby that stopped reading: the disk fills up


class ConfigIn(BaseModel):
    enabled: bool
    lag_alert_seconds: int = Field(300, ge=10, le=86400)


class HeartbeatIn(BaseModel):
    in_recovery: bool
    lag_seconds: float | None = Field(None, ge=0, le=10 ** 7)
    primary_ok: bool = True
    auto_promote: bool = False
    fail_streak: int = Field(0, ge=0, le=100000)
    host: str = Field("", max_length=120)
    version: str = Field("", max_length=40)
    files: dict | None = None  # {"at", "ok", "error"} — media, Support Pro uploads, app packages copied
    drill: dict | None = None  # {"at", "ok", "users", "payments", "migration", "error"} — weekly promotion drill


async def _load(db, key, default):
    from .node_health import _load as load
    return await load(db, key, default)


async def _save(db, key, value):
    from .node_health import _save as save
    await save(db, key, value)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def replication(db: AsyncSession) -> dict:
    """What PostgreSQL itself says. Not PostgreSQL (tests, sqlite) → ``supported: False``."""
    bind = db.bind
    if bind is None or bind.dialect.name != "postgresql":
        return {"supported": False, "in_recovery": False, "replicas": [], "slots": []}
    in_recovery = bool(await db.scalar(text("SELECT pg_is_in_recovery()")))
    replicas, slots = [], []
    if not in_recovery:
        rows = (await db.execute(text(
            "SELECT client_addr::text, state, sync_state, EXTRACT(EPOCH FROM replay_lag)::float AS lag, "
            "pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn)::bigint AS behind FROM pg_stat_replication"))).mappings().all()
        replicas = [{"address": r["client_addr"], "state": r["state"], "sync": r["sync_state"],
                     "lag_seconds": round(r["lag"] or 0, 1), "behind_bytes": int(r["behind"] or 0)} for r in rows]
        rows = (await db.execute(text(
            "SELECT slot_name, active, pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)::bigint AS retained "
            "FROM pg_replication_slots WHERE slot_type = 'physical'"))).mappings().all()
        slots = [{"name": r["slot_name"], "active": bool(r["active"]), "retained_bytes": int(r["retained"] or 0)} for r in rows]
    return {"supported": True, "in_recovery": in_recovery, "replicas": replicas, "slots": slots}


def assess(config: dict, repl: dict, beat: dict | None, now: datetime) -> list[tuple[str, str, str, str]]:
    """(key, title, detail, severity) — pure, so the rules are tested without PostgreSQL."""
    if not config.get("enabled"):
        return []
    out = []
    streaming = [r for r in repl.get("replicas", []) if r.get("state") == "streaming"]
    if repl.get("supported") and not repl.get("in_recovery") and not streaming:
        out.append(("standby:down", "Горячий резерв не получает данные",
                    "К базе не подключена ни одна реплика: при потере сервера данные с момента последней копии пропадут. "
                    "На резервном сервере: bash scripts/hot-standby.sh status.", "critical"))
    limit = int(config.get("lag_alert_seconds") or 300)
    for r in streaming:
        if r["lag_seconds"] > limit:
            out.append((f"standby:lag:{r['address']}", "Горячий резерв отстаёт",
                        f"Реплика {r['address']} отстаёт на {int(r['lag_seconds'])} с (порог {limit} с). Проверьте сеть и диск резервного сервера.",
                        "high"))
    for s in repl.get("slots", []):
        if not s["active"] and s["retained_bytes"] > SLOT_ALERT_BYTES:
            out.append((f"standby:slot:{s['name']}", "WAL копится для отключённого резерва",
                        f"Слот {s['name']} держит {s['retained_bytes'] // 1024 ** 2} МБ журнала, реплика не читает его — диск заполнится. "
                        "Верните резерв или удалите слот: bash scripts/hot-standby.sh drop-slot.", "high"))
    drill = (beat or {}).get("drill") or {}
    if drill and not drill.get("ok"):
        out.append(("standby:drill", "Учебное повышение резерва не прошло",
                    f"Копия базы резерва не запустилась как основная: {str(drill.get('error') or '')[:200]}. "
                    "Проверьте место на диске резерва и выполните: python3 /usr/local/bin/corgi-standby drill.", "high"))
    files = (beat or {}).get("files") or {}
    if files and not files.get("ok"):
        out.append(("standby:files", "Файлы на резерв не копируются",
                    f"{str(files.get('error') or '')[:200]}. Медиа и вложения поддержки на резерве устаревают: "
                    "hot-standby.sh files-key на резерве и files-allow на основном.", "medium"))
    seen = datetime.fromisoformat(beat["at"]) if beat and beat.get("at") else None
    if not seen or now - seen > STALE_HEARTBEAT:
        out.append(("standby:agent", "Агент горячего резерва молчит",
                    ("Резервный сервер не присылал отчёт больше 10 минут" if seen else "Агент резервного сервера ещё ни разу не отчитался")
                    + ": он не сможет предупредить о падении основного. systemctl status corgi-standby.timer на резервном сервере.", "medium"))
    return out


async def problems(db: AsyncSession, now: datetime | None = None) -> list[tuple[str, str, str, str]]:
    config = await _load(db, CONFIG_KEY, DEFAULT_CONFIG)
    if not config.get("enabled"):
        return []
    try:
        repl = await replication(db)
    except Exception as exc:  # noqa: BLE001 — a managed database may hide pg_stat_replication
        logger.warning("replication status failed: %s", exc)
        await db.rollback()
        repl = {"supported": False, "replicas": [], "slots": []}
    return assess(config, repl, await _load(db, HEARTBEAT_KEY, {}), now or datetime.utcnow())


@router.post("/api/standby/heartbeat")
async def heartbeat(payload: HeartbeatIn, request: Request, db: AsyncSession = Depends(get_db)):
    auth = request.headers.get("authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    config = await _load(db, CONFIG_KEY, DEFAULT_CONFIG)
    if not token or not config.get("token_sha") or not secrets.compare_digest(config["token_sha"], _hash(token)):
        raise HTTPException(401, "Standby token required")
    previous = await _load(db, HEARTBEAT_KEY, {})
    await _save(db, HEARTBEAT_KEY, {**payload.model_dump(), "at": datetime.utcnow().isoformat(),
                                    "from": request.client.host if request.client else None})
    await db.commit()
    drill = payload.drill or {}
    if drill.get("at") and drill.get("at") != ((previous or {}).get("drill") or {}).get("at"):
        try:
            await drill_report(db, drill, payload.lag_seconds)
        except Exception as exc:  # noqa: BLE001 — the report never breaks the heartbeat
            logger.warning("Drill report was not sent: %s", exc)
    return {"ok": True}


async def drill_report(db: AsyncSession, drill: dict, lag: float | None, sender=None) -> str:
    """v28.49: every weekly promotion drill of the standby ends with a Telegram card — passed or not — with the
    replication lag and the last verified backup, so a silent standby is never mistaken for a ready one."""
    from sqlalchemy import select
    from .models import BackupVerification
    if sender is None:
        from .ops_alerts import send as sender
    last = (await db.execute(select(BackupVerification).order_by(BackupVerification.id.desc()).limit(1))).scalar_one_or_none()
    backup = "нет проверенных копий" if not last else f"последняя проверка копии: {'успешно' if last.status in {'ok', 'verified', 'passed'} else last.status}, {last.created_at:%d.%m %H:%M}"
    if drill.get("ok"):
        text = (f"🟢 <b>Учения резерва пройдены</b>\n<blockquote>Копия базы поднялась как основная: клиентов {drill.get('users', '—')}, "
                f"платежей {drill.get('payments', '—')}, миграция {drill.get('migration', '—')}. Отставание репликации: "
                f"{'—' if lag is None else f'{lag:.0f} с'}; {backup}.</blockquote>")
    else:
        text = (f"🔴 <b>Учения резерва не прошли</b>\n<blockquote>{str(drill.get('error') or 'причина не передана')[:300]}. "
                f"Отставание репликации: {'—' if lag is None else f'{lag:.0f} с'}; {backup}. Проверьте место на диске резерва и выполните "
                f"python3 /usr/local/bin/corgi-standby drill.</blockquote>")
    await sender(text)
    return text


@router.get("/api/admin/standby")
async def get_standby(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("ops.diagnostics"))):
    config = await _load(db, CONFIG_KEY, DEFAULT_CONFIG)
    try:
        repl = await replication(db)
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        repl = {"supported": False, "replicas": [], "slots": [], "error": str(exc)[:200]}
    beat = await _load(db, HEARTBEAT_KEY, {})
    now = datetime.utcnow()
    return {"config": {k: v for k, v in config.items() if k != "token_sha"}, "token_set": bool(config.get("token_sha")),
            "replication": repl, "heartbeat": beat,
            "heartbeat_fresh": bool(beat and beat.get("at") and now - datetime.fromisoformat(beat["at"]) <= STALE_HEARTBEAT),
            "problems": [{"key": k, "title": t, "detail": d, "severity": s} for k, t, d, s in assess(config, repl, beat, now)]}


@router.put("/api/admin/standby")
async def put_standby(payload: ConfigIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("settings.runtime.write"))):
    from .main import audit
    config = await _load(db, CONFIG_KEY, DEFAULT_CONFIG)
    config.update(payload.model_dump())
    await _save(db, CONFIG_KEY, config)
    await audit(db, "standby.config", admin.email, None, payload.model_dump())
    await db.commit()
    return {"ok": True}


@router.post("/api/admin/standby/token")
async def new_token(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("settings.runtime.write"))):
    """A new agent token (the old one stops working); shown once with the command for the standby server."""
    from .config import settings
    from .main import audit
    from .release_identity import DISTRIBUTION_TAG
    token = secrets.token_urlsafe(32)
    config = await _load(db, CONFIG_KEY, DEFAULT_CONFIG)
    config["token_sha"] = _hash(token)
    await _save(db, CONFIG_KEY, config)
    await audit(db, "standby.token", admin.email, None, None)
    await db.commit()
    raw = f"https://raw.githubusercontent.com/booarkz-cpu/shop-by-boo/{DISTRIBUTION_TAG}/scripts/standby-agent.py"
    return {"token": token,
            "install": f"curl -fsSL {raw} -o /usr/local/bin/corgi-standby && sudo SHOP_URL=https://{settings.api_domain} "
                       f"STANDBY_TOKEN={token} PRIMARY_IP=<IP основного> python3 /usr/local/bin/corgi-standby install"}
