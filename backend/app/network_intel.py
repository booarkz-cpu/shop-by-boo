"""Network intelligence for VPN nodes: DNS, ASN/registry and IP reputation with a freshness cache.

Sources (both optional, both rate limited):

* ``ripestat`` — RIPEstat Data API (RIPE NCC), no key: announcing ASN, holder, prefix and the
  RIR registration country. Requests carry ``sourceapp`` as RIPEstat asks.
* ``abuseipdb`` — AbuseIPDB v2 ``check``, only when ``ABUSEIPDB_API_KEY`` is set: abuse confidence
  score, report count, usage type, Tor flag.

Node addresses come from Remnawave. Host names are resolved (A and AAAA). Private, loopback,
link-local and reserved addresses are never sent to a source. Results are cached per IP and
source with a TTL; a failed refresh keeps the last good data and marks it stale, so the
admin always sees how old each fact is.
"""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
import time
from collections import Counter
from datetime import datetime, timedelta
from typing import Callable

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import get_db
from .models import ConnectionObservation, NetworkIntel, NetworkIntelSourceState
from .security import require_permission

logger = logging.getLogger("vpnshop.network_intel")

SOURCES = {
    "ripestat": {"ttl": timedelta(days=7), "limit": 60, "window": timedelta(minutes=10), "label": "RIPEstat (RIPE NCC)"},
    "abuseipdb": {"ttl": timedelta(hours=24), "limit": 40, "window": timedelta(hours=1), "label": "AbuseIPDB"},
}
ERROR_BACKOFF = [timedelta(minutes=5), timedelta(minutes=30), timedelta(hours=2), timedelta(hours=12)]
BAD_REPUTATION = 50
MANUAL_REFRESH_GAP = timedelta(minutes=2)


def private(response: Response):
    response.headers["Cache-Control"] = "private, no-store"


router = APIRouter(dependencies=[Depends(private)])


def enabled_sources() -> list[str]:
    if not settings.network_intel_enabled:
        return []
    return ["ripestat"] + (["abuseipdb"] if settings.abuseipdb_api_key.strip() else [])


def public_ip(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    return ip.is_global and not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved)


# ---------------------------------------------------------------- DNS

def _resolve(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except OSError:
        return []
    out: list[str] = []
    for info in infos:
        address = info[4][0].split("%", 1)[0]
        if address not in out:
            out.append(address)
    return out


resolver: Callable[[str], list[str]] = _resolve  # tests replace this


async def resolve(address: str) -> tuple[list[str], str | None]:
    """Returns (ips, error). Accepts an IP literal, a host name or host:port."""
    host = (address or "").strip()
    if host.startswith("[") and "]" in host:
        host = host[1:host.index("]")]
    elif host.count(":") == 1:
        host = host.split(":", 1)[0]
    if not host:
        return [], "Адрес узла не указан"
    try:
        return [str(ipaddress.ip_address(host))], None
    except ValueError:
        pass
    ips = await asyncio.to_thread(resolver, host)
    return (ips, None) if ips else ([], "DNS не вернул адресов")


# ---------------------------------------------------------------- sources

def _default_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0), follow_redirects=False, headers={"User-Agent": "CorgiShop-NetworkIntel/1"})


client_factory: Callable[[], httpx.AsyncClient] = _default_client


class RateLimited(Exception):
    def __init__(self, retry_after: int):
        super().__init__(f"rate limited for {retry_after}s")
        self.retry_after = retry_after


def _retry_after(response: httpx.Response) -> int:
    try:
        return max(60, min(86400, int(response.headers.get("retry-after", "600"))))
    except ValueError:
        return 600


async def fetch_ripestat(client: httpx.AsyncClient, ip: str) -> dict:
    params = {"resource": ip, "sourceapp": "corgi-vpn-shop"}
    overview = await client.get("https://stat.ripe.net/data/prefix-overview/data.json", params=params)
    if overview.status_code == 429:
        raise RateLimited(_retry_after(overview))
    overview.raise_for_status()
    data = overview.json().get("data") or {}
    asns = [a for a in data.get("asns") or [] if isinstance(a, dict)]
    country = None
    rir = await client.get("https://stat.ripe.net/data/rir-stats-country/data.json", params=params)
    if rir.status_code == 429:
        raise RateLimited(_retry_after(rir))
    if rir.status_code == 200:
        located = (rir.json().get("data") or {}).get("located_resources") or []
        country = next((str(x.get("location"))[:2].upper() for x in located if isinstance(x, dict) and x.get("location")), None)
    return {
        "asn": int(asns[0]["asn"]) if asns and str(asns[0].get("asn", "")).isdigit() else None,
        "holder": str(asns[0].get("holder") or "")[:200] if asns else None,
        "prefix": data.get("resource") if data.get("announced") else None,
        "announced": bool(data.get("announced")),
        "country": country,
    }


async def fetch_abuseipdb(client: httpx.AsyncClient, ip: str) -> dict:
    response = await client.get(
        "https://api.abuseipdb.com/api/v2/check",
        params={"ipAddress": ip, "maxAgeInDays": "90"},
        headers={"Key": settings.abuseipdb_api_key.strip(), "Accept": "application/json"},
    )
    if response.status_code == 429:
        raise RateLimited(_retry_after(response))
    response.raise_for_status()
    data = response.json().get("data") or {}
    return {
        "score": int(data.get("abuseConfidenceScore") or 0),
        "reports": int(data.get("totalReports") or 0),
        "usage": str(data.get("usageType") or "")[:80] or None,
        "isp": str(data.get("isp") or "")[:120] or None,
        "tor": bool(data.get("isTor")),
        "last_reported_at": data.get("lastReportedAt"),
    }


FETCHERS = {"ripestat": fetch_ripestat, "abuseipdb": fetch_abuseipdb}


async def _take_budget(db: AsyncSession, source: str, now: datetime) -> bool:
    state = await db.get(NetworkIntelSourceState, source, with_for_update=True)
    if state is None:
        state = NetworkIntelSourceState(source=source, used=0)
        db.add(state)
    if state.blocked_until and state.blocked_until > now:
        return False
    window = SOURCES[source]["window"]
    if not state.window_start or state.window_start <= now - window:
        state.window_start, state.used = now, 0
    if state.used >= SOURCES[source]["limit"]:
        return False
    state.used += 1
    return True


async def refresh_one(db: AsyncSession, ip: str, source: str, now: datetime | None = None) -> str:
    """Fetches one (ip, source). Returns fetched, rate_limited, budget, error or skipped."""
    now = now or datetime.utcnow()
    if source not in enabled_sources() or not public_ip(ip):
        return "skipped"
    if not await _take_budget(db, source, now):
        await db.commit()
        return "budget"
    row = await db.scalar(select(NetworkIntel).where(NetworkIntel.ip == ip, NetworkIntel.source == source).with_for_update())
    if row is None:
        row = NetworkIntel(ip=ip, source=source, attempts=0)
        db.add(row)
    await db.commit()
    try:
        async with client_factory() as client:
            data = await FETCHERS[source](client, ip)
    except RateLimited as exc:
        state = await db.get(NetworkIntelSourceState, source, with_for_update=True)
        state.blocked_until = now + timedelta(seconds=exc.retry_after)
        state.last_error = f"HTTP 429: пауза {exc.retry_after} с"
        await db.commit()
        return "rate_limited"
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        row = await db.scalar(select(NetworkIntel).where(NetworkIntel.ip == ip, NetworkIntel.source == source).with_for_update())
        row.attempts += 1
        row.error = (f"HTTP {exc.response.status_code}" if isinstance(exc, httpx.HTTPStatusError) else type(exc).__name__)[:255]
        row.error_at = now
        row.next_attempt_at = now + ERROR_BACKOFF[min(row.attempts, len(ERROR_BACKOFF)) - 1]
        await db.commit()
        return "error"
    row = await db.scalar(select(NetworkIntel).where(NetworkIntel.ip == ip, NetworkIntel.source == source).with_for_update())
    row.data, row.fetched_at, row.expires_at = data, now, now + SOURCES[source]["ttl"]
    row.error, row.error_at, row.attempts, row.next_attempt_at = None, None, 0, None
    state = await db.get(NetworkIntelSourceState, source)
    if state:
        state.last_error = None
    await db.commit()
    return "fetched"


# ---------------------------------------------------------------- nodes

async def list_nodes() -> tuple[list[dict], str | None]:
    """Remnawave nodes with their raw address (admin-only; never shown to customers)."""
    from .remnawave import RemnawaveClient
    from .tariff_api import _iter_nodes, public_node

    try:
        raw = await RemnawaveClient().list_nodes(start=0, size=200)
    except Exception:
        return [], "Remnawave недоступен"
    out = []
    for node in _iter_nodes(raw):
        shown = public_node(node)
        out.append({"uuid": str(node.get("uuid") or node.get("id") or "")[:64], "name": shown.get("name"), "status": shown.get("status"), "country": shown.get("country") or None, "address": str(node.get("address") or node.get("host") or "")[:255]})
    return out, None


def _freshness(row: NetworkIntel | None, now: datetime) -> str:
    if row is None or row.fetched_at is None:
        return "error" if row and row.error else "missing"
    if row.expires_at and row.expires_at > now:
        return "fresh"
    return "stale"


def _entry(row: NetworkIntel | None, now: datetime) -> dict:
    return {
        "freshness": _freshness(row, now),
        "data": row.data if row else None,
        "fetched_at": row.fetched_at.isoformat() + "Z" if row and row.fetched_at else None,
        "age_hours": round((now - row.fetched_at).total_seconds() / 3600, 1) if row and row.fetched_at else None,
        "error": row.error if row else None,
    }


async def build_report(db: AsyncSession, nodes: list[dict], now: datetime | None = None) -> dict:
    now = now or datetime.utcnow()
    sources = enabled_sources()
    resolved = []
    for node in nodes:
        ips, dns_error = await resolve(node["address"])
        resolved.append((node, ips, dns_error))
    all_ips = sorted({ip for _, ips, _ in resolved for ip in ips})
    rows = (await db.scalars(select(NetworkIntel).where(NetworkIntel.ip.in_(all_ips)))).all() if all_ips else []
    cache = {(r.ip, r.source): r for r in rows}
    items = []
    asn_nodes: dict[int, list[str]] = {}
    for node, ips, dns_error in resolved:
        addresses = []
        for ip in ips:
            if not public_ip(ip):
                addresses.append({"ip": ip, "version": ipaddress.ip_address(ip).version, "private": True, "registry": None, "reputation": None})
                continue
            registry = _entry(cache.get((ip, "ripestat")), now) if "ripestat" in sources else None
            reputation = _entry(cache.get((ip, "abuseipdb")), now) if "abuseipdb" in sources else None
            addresses.append({"ip": ip, "version": ipaddress.ip_address(ip).version, "private": False, "registry": registry, "reputation": reputation})
            asn = ((registry or {}).get("data") or {}).get("asn")
            if asn:
                asn_nodes.setdefault(asn, [])
                if node["name"] not in asn_nodes[asn]:
                    asn_nodes[asn].append(node["name"])
        warnings = []
        if dns_error:
            warnings.append({"level": "danger", "text": dns_error})
        if ips and all(not public_ip(ip) for ip in ips):
            warnings.append({"level": "warn", "text": "Только внутренние адреса: внешняя проверка не выполняется"})
        for a in addresses:
            rep = ((a.get("reputation") or {}).get("data")) or {}
            if rep.get("score", 0) >= BAD_REPUTATION:
                warnings.append({"level": "danger", "text": f"{a['ip']}: репутация {rep['score']}/100, жалоб {rep.get('reports', 0)}"})
            if rep.get("tor"):
                warnings.append({"level": "warn", "text": f"{a['ip']}: отмечен как узел Tor"})
            reg = ((a.get("registry") or {}).get("data")) or {}
            if node.get("country") and reg.get("country") and node["country"].upper()[:2] != reg["country"]:
                warnings.append({"level": "info", "text": f"{a['ip']}: страна в панели {node['country']}, по RIR {reg['country']}"})
            if reg and reg.get("announced") is False:
                warnings.append({"level": "warn", "text": f"{a['ip']}: префикс не анонсируется в BGP"})
            for kind in ("registry", "reputation"):
                entry = a.get(kind)
                if entry and entry["freshness"] in ("stale", "error"):
                    warnings.append({"level": "info", "text": f"{a['ip']}: данные {SOURCES['ripestat' if kind == 'registry' else 'abuseipdb']['label']} {'устарели' if entry['freshness'] == 'stale' else 'не получены'}{' — ' + entry['error'] if entry.get('error') else ''}"})
        items.append({**node, "addresses": addresses, "warnings": warnings})
    concentration = [{"asn": asn, "nodes": names} for asn, names in sorted(asn_nodes.items()) if len(names) > 1]
    for item in items:
        for group in concentration:
            if item["name"] in group["nodes"]:
                item["warnings"].append({"level": "info", "text": f"В одной сети AS{group['asn']} с узлами: {', '.join(n for n in group['nodes'] if n != item['name'])}"})
    states = {s.source: s for s in (await db.scalars(select(NetworkIntelSourceState))).all()}
    return {
        "enabled": bool(sources),
        "sources": [
            {"id": key, "label": meta["label"], "enabled": key in sources, "ttl_hours": int(meta["ttl"].total_seconds() // 3600),
             "limit": meta["limit"], "window_minutes": int(meta["window"].total_seconds() // 60),
             "blocked_until": states[key].blocked_until.isoformat() + "Z" if key in states and states[key].blocked_until and states[key].blocked_until > now else None,
             "last_error": states[key].last_error if key in states else None}
            for key, meta in SOURCES.items()
        ],
        "nodes": items,
        "asn_concentration": concentration,
        "generated_at": now.isoformat() + "Z",
    }


async def customer_networks(db: AsyncSession, days: int = 7, now: datetime | None = None) -> dict:
    """Aggregated ASN/country of customer connections; individual IPs are never returned."""
    since = (now or datetime.utcnow()) - timedelta(days=days)
    rows = (await db.execute(
        select(ConnectionObservation.asn, ConnectionObservation.asn_org, ConnectionObservation.country, func.count(func.distinct(ConnectionObservation.user_id)))
        .where(ConnectionObservation.seen_at >= since)
        .group_by(ConnectionObservation.asn, ConnectionObservation.asn_org, ConnectionObservation.country)
    )).all()
    by_asn: Counter = Counter()
    names: dict[str, str] = {}
    by_country: Counter = Counter()
    for asn, org, country, users in rows:
        key = asn or "unknown"
        by_asn[key] += int(users)
        names.setdefault(key, org or "")
        by_country[country or "—"] += int(users)
    return {
        "days": days,
        "asns": [{"asn": k, "org": names.get(k) or None, "users": v} for k, v in by_asn.most_common(15)],
        "countries": [{"country": k, "users": v} for k, v in by_country.most_common(15)],
    }


# ---------------------------------------------------------------- refresh

async def refresh_due(db: AsyncSession, nodes: list[dict], now: datetime | None = None, limit: int = 20) -> dict[str, int]:
    """Refreshes missing or expired entries of current node IPs within the source budgets."""
    now = now or datetime.utcnow()
    ips = []
    for node in nodes:
        found, _ = await resolve(node["address"])
        ips.extend(ip for ip in found if public_ip(ip) and ip not in ips)
    stats: dict[str, int] = {}
    done = 0
    for source in enabled_sources():
        for ip in ips:
            if done >= limit:
                return stats
            row = await db.scalar(select(NetworkIntel).where(NetworkIntel.ip == ip, NetworkIntel.source == source))
            due = row is None or row.expires_at is None or row.expires_at <= now
            if row and row.next_attempt_at and row.next_attempt_at > now:
                due = False
            if not due:
                continue
            outcome = await refresh_one(db, ip, source, now)
            stats[outcome] = stats.get(outcome, 0) + 1
            done += 1
            if outcome in ("budget", "rate_limited"):
                break
    return stats


async def network_intel_scheduler():
    from .db import engine

    while True:
        try:
            if enabled_sources():
                nodes, error = await list_nodes()
                if not error:
                    async with AsyncSession(engine, expire_on_commit=False) as db:
                        await refresh_due(db, nodes)
        except Exception as exc:
            logger.warning("Network intel cycle failed: %s", type(exc).__name__)
        await asyncio.sleep(600)


# ---------------------------------------------------------------- admin API

@router.get("/api/admin/network/intel")
async def admin_network_intel(db: AsyncSession = Depends(get_db), admin=Depends(require_permission("ops.diagnostics"))):
    nodes, error = await list_nodes()
    report = await build_report(db, nodes)
    report["remnawave_error"] = error
    report["customers"] = await customer_networks(db)
    return report


class RefreshIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ip: str = Field(min_length=2, max_length=45)


_manual: dict[str, float] = {}


@router.post("/api/admin/network/intel/refresh")
async def admin_network_refresh(body: RefreshIn, db: AsyncSession = Depends(get_db), admin=Depends(require_permission("ops.diagnostics"))):
    try:
        ip = str(ipaddress.ip_address(body.ip.strip()))
    except ValueError:
        raise HTTPException(422, "Нужен IP-адрес")
    if not public_ip(ip):
        raise HTTPException(422, "Внутренние и зарезервированные адреса не проверяются")
    nodes, _ = await list_nodes()
    node_ips = set()
    for node in nodes:
        node_ips.update((await resolve(node["address"]))[0])
    if ip not in node_ips:
        raise HTTPException(404, "Это не адрес узла Remnawave")
    last = _manual.get(ip, 0.0)
    if time.monotonic() - last < MANUAL_REFRESH_GAP.total_seconds():
        raise HTTPException(429, "Этот адрес уже обновлялся в последние 2 минуты")
    _manual[ip] = time.monotonic()
    results = {source: await refresh_one(db, ip, source) for source in enabled_sources()}
    from .main import audit

    await audit(db, "network.intel.refresh", getattr(admin, "email", "admin"), ip, results)
    await db.commit()
    return {"ip": ip, "results": results}
