"""v28.54 «Проверка доступности из РФ» (RIPE Atlas): the API addresses and the nodes checked from probes of real Russian
providers, without servers of your own in Russia.

Every ``interval_hours`` the shop asks RIPE Atlas for one-off ``sslcert`` measurements (TCP + TLS handshake, the way a
VPN client connects) from ``probes`` probes in ``country`` to every target of «Монитор блокировок»: the API domains on
443 and every node on its ports. After ``wait_minutes`` it reads the results: a target counts as reachable when at
least ``ok_share`` of the probes completed the handshake. The verdicts go into the block monitor as a virtual probe
«RIPE Atlas <country>» — so a block found this way triggers the same alert, reserve-address reorder and reserve
squad as your own probes (after ``fail_streak`` passes in a row).

Needs a RIPE Atlas API key with measurement credits (atlas.ripe.net → API keys; ``ripe_atlas.config``, stored
encrypted). Off by default. Admin: «Ноды → Монитор блокировок → RIPE Atlas» and the mobile card.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import require_permission

logger = logging.getLogger("vpnshop.ripe_atlas")
router = APIRouter()
CONFIG_KEY = "ripe_atlas.config"
PENDING_KEY = "ripe_atlas.pending"
API = "https://atlas.ripe.net/api/v2"
DEFAULT = {"enabled": False, "api_key": "", "country": "RU", "probes": 5, "interval_hours": 6, "wait_minutes": 15, "ok_share": 0.5,
           "last_run": None, "last_error": None, "last_results": {}}


class RipeIn(BaseModel):
    enabled: bool = False
    api_key: str = Field("", max_length=80)
    country: str = Field("RU", pattern=r"^[A-Z]{2}$")
    probes: int = Field(5, ge=1, le=50)
    interval_hours: int = Field(6, ge=1, le=72)
    wait_minutes: int = Field(15, ge=5, le=120)
    ok_share: float = Field(0.5, ge=0.1, le=1)


async def _load(db, key, default):
    from .node_health import _load as load
    return {**default, **(await load(db, key, default) or {})}


async def _save(db, key, value):
    from .node_health import _save as save
    await save(db, key, value)


def probe_id(country: str) -> str:
    return f"ripe-atlas-{country.lower()}"


def host_port(target: str) -> tuple[str, int] | None:
    """``https://host/health/live`` → (host, 443); ``tcp://1.2.3.4:8443`` → ("1.2.3.4", 8443)."""
    parts = urlsplit(target)
    if not parts.hostname:
        return None
    if parts.scheme == "https":
        return parts.hostname, parts.port or 443
    if parts.scheme == "tcp" and parts.port:
        return parts.hostname, parts.port
    return None


def definitions(targets: list[dict]) -> list[dict]:
    out = []
    for t in targets:
        hp = host_port(t["target"])
        if hp:
            out.append({"type": "sslcert", "af": 4, "target": hp[0], "port": hp[1], "resolve_on_probe": True, "is_oneoff": True,
                        "description": f"Corgi Lusi availability: {t.get('label') or hp[0]}"[:120]})
    return out


def verdict(results: list[dict], ok_share: float) -> tuple[bool, int, int]:
    """(reachable, ok, total): a probe succeeded when it got a certificate."""
    total = len(results)
    ok = sum(1 for r in results if r.get("cert") and not r.get("err"))
    return (total > 0 and ok / total >= ok_share), ok, total


async def _http(method: str, path: str, key: str, body: dict | None = None):
    import httpx
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.request(method, API + path, json=body, headers={"Authorization": f"Key {key}", "Accept": "application/json"})
    if r.status_code in (401, 403):
        raise ValueError("RIPE Atlas не принял ключ API или у ключа нет прав на измерения")
    if r.status_code >= 400:
        raise ValueError(f"RIPE Atlas ответил {r.status_code}: {r.text[:160]}")
    return r.json()


async def start(db: AsyncSession, cfg: dict, call=None, now: datetime | None = None) -> dict:
    """Ask for the measurements of every target of the block monitor."""
    from .block_monitor import targets
    from .security import decrypt_secret
    call = call or _http
    known = [t for t in await targets(db) if host_port(t["target"])]
    defs = definitions(known)
    if not defs:
        return {}
    answer = await call("POST", "/measurements/", decrypt_secret(cfg["api_key"]),
                        {"definitions": defs, "probes": [{"type": "country", "value": cfg["country"], "requested": int(cfg["probes"])}]})
    ids = answer.get("measurements") or []
    pending = {"created": (now or datetime.utcnow()).isoformat(), "items": [{"target": t["target"], "label": t.get("label"), "msm": m} for t, m in zip(known, ids)]}
    await _save(db, PENDING_KEY, pending)
    await db.commit()
    return pending


async def collect(db: AsyncSession, cfg: dict, pending: dict, call=None) -> dict:
    """Read the results and hand them to the block monitor as the virtual probe of the country."""
    from .block_monitor import PROBES_KEY, ResultIn, apply_report
    from .security import decrypt_secret
    call = call or _http
    key = decrypt_secret(cfg["api_key"])
    results, summary = [], {}
    for item in pending.get("items") or []:
        rows = await call("GET", f"/measurements/{item['msm']}/results/?format=json", key)
        reachable, ok, total = verdict(rows if isinstance(rows, list) else [], float(cfg["ok_share"]))
        summary[item["target"]] = {"label": item.get("label"), "ok": ok, "total": total, "reachable": reachable}
        if total:
            results.append(ResultIn(target=item["target"], ok=reachable, error=None if reachable else f"RIPE Atlas: {ok}/{total} проб"))
    pid = probe_id(cfg["country"])
    probes = await _load(db, PROBES_KEY, {})
    probes[pid] = {**probes.get(pid, {}), "name": f"RIPE Atlas {cfg['country']}", "region": f"{cfg['country']} (RIPE Atlas)", "token_sha": "",
                   "virtual": True, "stale_minutes": int(cfg["interval_hours"]) * 60 * 2 + int(cfg["wait_minutes"]),
                   "created_at": probes.get(pid, {}).get("created_at") or datetime.utcnow().isoformat(), "last_seen_at": probes.get(pid, {}).get("last_seen_at")}
    await _save(db, PROBES_KEY, probes)
    await db.commit()
    blocked = (await apply_report(db, pid, results)) if results else {"blocked": []}
    await _save(db, PENDING_KEY, {})
    cfg = await _load(db, CONFIG_KEY, DEFAULT)
    cfg.update(last_results=summary, last_error=None)
    await _save(db, CONFIG_KEY, cfg)
    await db.commit()
    return {"summary": summary, "blocked": blocked["blocked"]}


async def tick(db: AsyncSession, now: datetime | None = None, call=None) -> str:
    now = now or datetime.utcnow()
    cfg = await _load(db, CONFIG_KEY, DEFAULT)
    if not cfg["enabled"] or not cfg["api_key"]:
        return "off"
    pending = await _load(db, PENDING_KEY, {})
    try:
        if pending.get("items"):
            if datetime.fromisoformat(pending["created"]) > now - timedelta(minutes=int(cfg["wait_minutes"])):
                return "waiting"
            await collect(db, cfg, pending, call)
            return "collected"
        last = cfg.get("last_run")
        if last and datetime.fromisoformat(last) > now - timedelta(hours=int(cfg["interval_hours"])):
            return "idle"
        await start(db, cfg, call, now)
        cfg = await _load(db, CONFIG_KEY, DEFAULT)
        cfg["last_run"] = now.isoformat()
        await _save(db, CONFIG_KEY, cfg)
        await db.commit()
        return "started"
    except Exception as exc:  # noqa: BLE001 — shown in the admin; the next pass tries again
        await db.rollback()
        cfg = await _load(db, CONFIG_KEY, DEFAULT)
        cfg["last_error"] = str(exc)[:200]
        cfg["last_run"] = now.isoformat()
        await _save(db, CONFIG_KEY, cfg)
        await _save(db, PENDING_KEY, {})
        await db.commit()
        logger.warning("RIPE Atlas pass failed: %s", exc)
        return "error"


async def _loop():
    from .db import SessionLocal
    from .main import redis_client
    while True:
        await asyncio.sleep(300)
        try:
            if redis_client is not None and not await redis_client.set("lock:ripe_atlas", "1", nx=True, ex=280):
                continue
            async with SessionLocal() as db:
                await tick(db)
        except Exception as exc:  # noqa: BLE001
            logger.warning("RIPE Atlas loop failed: %s", exc)


def _start():
    from .main import _track_task
    _track_task(_loop())


router.add_event_handler("startup", _start)


def public(cfg: dict) -> dict:
    return {**{k: v for k, v in cfg.items() if k != "api_key"}, "key_set": bool(cfg.get("api_key"))}


@router.get("/api/admin/ripe-atlas")
async def get_ripe(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("ops.diagnostics"))):
    cfg = await _load(db, CONFIG_KEY, DEFAULT)
    pending = await _load(db, PENDING_KEY, {})
    return {**public(cfg), "pending": bool(pending.get("items"))}


@router.put("/api/admin/ripe-atlas")
async def put_ripe(payload: RipeIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("settings.runtime.write"))):
    from .main import audit
    from .security import encrypt_secret
    cfg = await _load(db, CONFIG_KEY, DEFAULT)
    value = payload.model_dump()
    value["api_key"] = encrypt_secret(payload.api_key) if payload.api_key else cfg.get("api_key", "")
    if value["enabled"] and not value["api_key"]:
        raise HTTPException(400, "Укажите ключ API RIPE Atlas")
    cfg.update(value)
    await _save(db, CONFIG_KEY, cfg)
    await audit(db, "ripe_atlas.config", admin.email, None, {k: v for k, v in value.items() if k != "api_key"})
    await db.commit()
    return public(cfg)


@router.post("/api/admin/ripe-atlas/run")
async def run_ripe(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("ops.diagnostics"))):
    """Start a check now (the results come in ``wait_minutes``)."""
    cfg = await _load(db, CONFIG_KEY, DEFAULT)
    if not cfg["api_key"]:
        raise HTTPException(409, "Укажите ключ API RIPE Atlas")
    try:
        pending = await start(db, cfg)
    except ValueError as exc:
        raise HTTPException(502, str(exc)) from exc
    cfg = await _load(db, CONFIG_KEY, DEFAULT)
    cfg["last_run"] = datetime.utcnow().isoformat()
    await _save(db, CONFIG_KEY, cfg)
    await db.commit()
    return {"ok": True, "targets": len(pending.get("items") or [])}
