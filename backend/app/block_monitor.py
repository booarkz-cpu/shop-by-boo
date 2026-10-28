"""Block monitor: is the shop reachable from where the customers are?

Small probes on servers in the customers' regions (scripts/block-probe.py, standard library only, a systemd timer every
5 minutes) ask the shop which addresses to check — the API domain, its reserve domains and the VPN nodes — try them and
report back. A target counts as **blocked in a region** when every probe of that region failed it ``fail_streak``
times in a row while the shop itself sees it working (the API answers, Remnawave reports the node online): that is a
block, not an outage.

What happens then, without anyone:

* a Telegram alert with the target and the region («Запуск и оповещения», repeats while it lasts, a note when it ends);
* a blocked API address moves to the end of the signed reserve list the apps follow (anti_blocking.md), and the list
  is republished to the Gist — apps already on a working address stay there, the rest try the open ones first;
* optionally, while any node is blocked, every customer is added to a reserve Internal Squad (other protocol or
  other nodes: Reality, XHTTP…) so their subscription gains working profiles; removed again when the block ends.

Everything is configured in «Серверы → Монитор блокировок»; probes are added there with a one-time token.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .security import require_permission

logger = logging.getLogger("vpnshop.block_monitor")
router = APIRouter()

CONFIG_KEY = "block_monitor.config"
PROBES_KEY = "block_monitor.probes"
STATE_KEY = "block_monitor.state"
DEFAULT_CONFIG = {"enabled": False, "fail_streak": 3, "node_ports": [443], "reorder_mirrors": True,
                  "fallback_squad_uuid": "", "auto_fallback_squad": False}
MAX_PROBES = 50
MAX_RESULTS = 200
STALE_PROBE = timedelta(minutes=30)


class ConfigIn(BaseModel):
    enabled: bool
    fail_streak: int = Field(3, ge=1, le=20)
    node_ports: list[int] = Field(default_factory=lambda: [443], max_length=5)
    reorder_mirrors: bool = True
    fallback_squad_uuid: str = Field("", max_length=64, pattern=r"^[0-9a-fA-F-]*$")
    auto_fallback_squad: bool = False


class ProbeIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    region: str = Field(min_length=2, max_length=40, pattern=r"^[A-Za-zА-Яа-яЁё0-9 ._-]+$")


class ResultIn(BaseModel):
    target: str = Field(max_length=300)
    ok: bool
    ms: int | None = Field(None, ge=0, le=120000)
    error: str | None = Field(None, max_length=200)


class ReportIn(BaseModel):
    results: list[ResultIn] = Field(max_length=MAX_RESULTS)


async def _load(db, key, default):
    from .node_health import _load as load
    return await load(db, key, default)


async def _save(db, key, value):
    from .node_health import _save as save
    await save(db, key, value)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ---------------------------------------------------------------- targets

async def targets(db: AsyncSession, config: dict | None = None) -> list[dict]:
    """What the probes check: the API (main and reserve) and every enabled node on its ports."""
    from .config import settings
    from .mobile_mirrors import load as load_mirrors
    from .node_health import node_snapshot
    config = config or await _load(db, CONFIG_KEY, DEFAULT_CONFIG)
    out: list[dict] = []
    seen: set[str] = set()

    def add(item):
        if item["target"] not in seen:
            seen.add(item["target"]); out.append(item)
    domains = [d for d in settings.api_domains() if d and d != "localhost"]
    for i, domain in enumerate(domains):
        add({"target": f"https://{domain}/health/live", "kind": "api", "label": domain, "primary": i == 0})
    for url in (await load_mirrors(db)).get("mirrors", []):
        host = urlsplit(url).hostname
        if host:
            add({"target": f"https://{host}/health/live", "kind": "api", "label": host, "primary": False})
    snap = await node_snapshot()
    for node in snap.get("nodes", []):
        address = (node.get("address") or "").strip()
        if not address or node.get("status") == "disabled":
            continue
        for port in config.get("node_ports") or [443]:
            add({"target": f"tcp://{address}:{int(port)}", "kind": "node", "label": node.get("name") or address,
                 "node_uuid": node.get("uuid"), "node_online": node.get("status") == "online"})
    return out


# ---------------------------------------------------------------- evaluation

def evaluate(state: dict, probes: dict, known: list[dict], fail_streak: int, now: datetime) -> dict[str, dict]:
    """Targets blocked now: {target: {"regions": [...], "label", "kind"}}.

    A region decides only with fresh probes (seen in the last 30 min); every fresh probe of the region must have failed
    the target ``fail_streak`` times in a row. A node Remnawave reports offline is down, not blocked."""
    by_target = state.get("targets", {})
    regions: dict[str, list[str]] = {}
    for pid, probe in probes.items():
        seen = probe.get("last_seen_at")
        if seen and datetime.fromisoformat(seen) >= now - STALE_PROBE:
            regions.setdefault(probe["region"], []).append(pid)
    blocked: dict[str, dict] = {}
    for item in known:
        if item["kind"] == "node" and not item.get("node_online"):
            continue
        results = by_target.get(item["target"], {})
        hit = [region for region, pids in regions.items()
               if pids and all(results.get(pid, {}).get("fails", 0) >= fail_streak for pid in pids)]
        if hit:
            blocked[item["target"]] = {"regions": sorted(hit), "label": item["label"], "kind": item["kind"]}
    return blocked


async def apply_report(db: AsyncSession, probe_id: str, results: list[ResultIn], now: datetime | None = None) -> dict:
    now = now or datetime.utcnow()
    config = await _load(db, CONFIG_KEY, DEFAULT_CONFIG)
    probes = await _load(db, PROBES_KEY, {})
    state = await _load(db, STATE_KEY, {"targets": {}, "blocked": {}})
    known = await targets(db, config)
    allowed = {t["target"] for t in known}
    for r in results:
        if r.target not in allowed:
            continue  # a probe reports only what the shop asked for
        slot = state.setdefault("targets", {}).setdefault(r.target, {}).setdefault(probe_id, {"fails": 0})
        slot.update({"ok": r.ok, "ms": r.ms, "error": (r.error or "")[:200] or None, "at": now.isoformat()})
        slot["fails"] = 0 if r.ok else slot.get("fails", 0) + 1
    probes[probe_id]["last_seen_at"] = now.isoformat()
    previous = set(state.get("blocked", {}))
    blocked = evaluate(state, probes, known, int(config["fail_streak"]), now)
    for target, info in blocked.items():
        info["since"] = state.get("blocked", {}).get(target, {}).get("since") or now.isoformat()
    state["blocked"] = blocked
    await _save(db, STATE_KEY, state)
    await _save(db, PROBES_KEY, probes)
    await db.commit()
    if config.get("enabled") and set(blocked) != previous:
        await react(db, config, state, known)
    return {"blocked": sorted(blocked)}


async def react(db: AsyncSession, config: dict, state: dict, known: list[dict], panel=None) -> dict:
    """Actions when the set of blocked targets changes."""
    done = {"mirrors_reordered": False, "fallback": None}
    blocked = state.get("blocked", {})
    if config.get("reorder_mirrors"):
        from . import mobile_mirrors
        await mobile_mirrors.publish(db)  # the signed list orders blocked hosts last (blocked_hosts below)
        done["mirrors_reordered"] = True
    squad = config.get("fallback_squad_uuid")
    if config.get("auto_fallback_squad") and squad:
        nodes_blocked = any(v["kind"] == "node" for v in blocked.values())
        if nodes_blocked != bool(state.get("fallback_active")):
            from .remnawave import RemnawaveClient
            panel = panel or RemnawaveClient()
            try:
                if nodes_blocked:
                    await panel.squad_add_all_users(squad)
                else:
                    await panel.squad_remove_all_users(squad)
                state["fallback_active"] = nodes_blocked
                done["fallback"] = "added" if nodes_blocked else "removed"
                from .main import audit
                await audit(db, "block_monitor.fallback_squad", "system", squad, {"active": nodes_blocked})
            except Exception as exc:  # noqa: BLE001 — the alert still goes out; the operator sees the error
                state["fallback_error"] = str(exc)[:300]
                logger.warning("Fallback squad switch failed: %s", exc)
            await _save(db, STATE_KEY, state)
            await db.commit()
    return done


async def blocked_hosts(db: AsyncSession) -> set[str]:
    """API hosts currently blocked somewhere (used to order the signed mirror list)."""
    state = await _load(db, STATE_KEY, {"blocked": {}})
    return {urlsplit(t).hostname for t, v in state.get("blocked", {}).items() if v.get("kind") == "api" and urlsplit(t).hostname}


async def problems(db: AsyncSession) -> list[tuple[str, str, str]]:
    """(key, title, detail) for ops alerts."""
    config = await _load(db, CONFIG_KEY, DEFAULT_CONFIG)
    if not config.get("enabled"):
        return []
    state = await _load(db, STATE_KEY, {"blocked": {}})
    out = []
    for target, info in state.get("blocked", {}).items():
        what = "Адрес API" if info["kind"] == "api" else "Нода"
        out.append((f"blocked:{target}", f"{what} {info['label']} недоступен в регионе: {', '.join(info['regions'])}",
                    f"Пробы в регионе не могут подключиться к {target} с {str(info.get('since', ''))[:16].replace('T', ' ')} UTC, "
                    "хотя магазин видит его работающим — похоже на блокировку. "
                    + ("Приложения переключатся на резервный адрес сами." if info["kind"] == "api"
                       else "Включите резервный профиль (Reality/XHTTP) в «Серверы → Монитор блокировок».")))
    return out


# ---------------------------------------------------------------- probe API

async def _probe(request: Request, db: AsyncSession) -> tuple[str, dict]:
    auth = request.headers.get("authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    if not token:
        raise HTTPException(401, "Probe token required")
    probes = await _load(db, PROBES_KEY, {})
    digest = _hash(token)
    for pid, probe in probes.items():
        if secrets.compare_digest(probe.get("token_sha", ""), digest):
            return pid, probe
    raise HTTPException(401, "Unknown probe")


@router.get("/api/probe/targets")
async def probe_targets(request: Request, db: AsyncSession = Depends(get_db)):
    await _probe(request, db)
    return {"targets": [t["target"] for t in await targets(db)], "interval_seconds": 300}


@router.post("/api/probe/report")
async def probe_report(payload: ReportIn, request: Request, db: AsyncSession = Depends(get_db)):
    pid, _ = await _probe(request, db)
    return await apply_report(db, pid, payload.results)


# ---------------------------------------------------------------- admin API

@router.get("/api/admin/block-monitor")
async def get_monitor(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("ops.diagnostics"))):
    from .release_identity import DISTRIBUTION_TAG
    config = await _load(db, CONFIG_KEY, DEFAULT_CONFIG)
    probes = await _load(db, PROBES_KEY, {})
    state = await _load(db, STATE_KEY, {"targets": {}, "blocked": {}})
    now = datetime.utcnow()
    return {
        "config": config,
        "probes": [{"id": pid, "name": p["name"], "region": p["region"], "last_seen_at": p.get("last_seen_at"),
                    "fresh": bool(p.get("last_seen_at") and datetime.fromisoformat(p["last_seen_at"]) >= now - STALE_PROBE)}
                   for pid, p in probes.items()],
        "targets": [{**t, "results": {pid: {k: v for k, v in r.items()} for pid, r in state.get("targets", {}).get(t["target"], {}).items()}}
                    for t in await targets(db, config)],
        "blocked": state.get("blocked", {}),
        "fallback_active": bool(state.get("fallback_active")),
        "fallback_error": state.get("fallback_error"),
        "script_url": f"https://raw.githubusercontent.com/booarkz-cpu/shop-by-boo/{DISTRIBUTION_TAG}/scripts/block-probe.py",
    }


@router.put("/api/admin/block-monitor")
async def put_monitor(payload: ConfigIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("settings.runtime.write"))):
    from .main import audit
    value = payload.model_dump()
    value["node_ports"] = sorted({p for p in value["node_ports"] if 1 <= p <= 65535}) or [443]
    await _save(db, CONFIG_KEY, value)
    await audit(db, "block_monitor.config", admin.email, None, value)
    await db.commit()
    return value


@router.post("/api/admin/block-monitor/probes")
async def add_probe(payload: ProbeIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("settings.runtime.write"))):
    from .config import settings
    from .main import audit
    probes = await _load(db, PROBES_KEY, {})
    if len(probes) >= MAX_PROBES:
        raise HTTPException(400, f"Не больше {MAX_PROBES} проб")
    token = secrets.token_urlsafe(32)
    pid = secrets.token_hex(6)
    probes[pid] = {"name": payload.name.strip(), "region": payload.region.strip(), "token_sha": _hash(token),
                   "created_at": datetime.utcnow().isoformat(), "last_seen_at": None}
    await _save(db, PROBES_KEY, probes)
    await audit(db, "block_monitor.probe_added", admin.email, pid, {"name": payload.name, "region": payload.region})
    await db.commit()
    shop_url = f"https://{settings.api_domain}"
    # The token is shown once; only its hash is stored.
    from .release_identity import DISTRIBUTION_TAG
    script = f"https://raw.githubusercontent.com/booarkz-cpu/shop-by-boo/{DISTRIBUTION_TAG}/scripts/block-probe.py"
    return {"id": pid, "token": token,
            "install": f"curl -fsSL {script} -o /usr/local/bin/corgi-probe && "
                       f"sudo SHOP_URL={shop_url} PROBE_TOKEN={token} python3 /usr/local/bin/corgi-probe install"}


@router.delete("/api/admin/block-monitor/probes/{probe_id}")
async def delete_probe(probe_id: str, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("settings.runtime.write"))):
    from .main import audit
    probes = await _load(db, PROBES_KEY, {})
    if probes.pop(probe_id, None) is None:
        raise HTTPException(404, "Проба не найдена")
    state = await _load(db, STATE_KEY, {"targets": {}, "blocked": {}})
    for results in state.get("targets", {}).values():
        results.pop(probe_id, None)
    await _save(db, PROBES_KEY, probes)
    await _save(db, STATE_KEY, state)
    await audit(db, "block_monitor.probe_deleted", admin.email, probe_id, None)
    await db.commit()
    return {"ok": True}
