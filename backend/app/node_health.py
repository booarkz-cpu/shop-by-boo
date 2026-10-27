"""Remnawave node status: a short Redis cache shared by every backend and worker process, and node monitoring.

``node_snapshot()`` asks Remnawave at most once per ``CACHE_TTL`` seconds for all processes together; the admin
panel, the apps' server list and the monitor read the same snapshot. Without Redis it asks Remnawave directly.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger("vpnshop.nodes")
CACHE_KEY = "nodes:status:v1"
CACHE_TTL = 30


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def node_row(node: dict) -> dict:
    """One node as the shop keeps it (admin view: the address is included, customers get ``public_node``)."""
    from .tariff_api import public_node

    shown = public_node(node)
    return {
        "uuid": str(node.get("uuid") or node.get("id") or "")[:64],
        "name": shown.get("name"),
        "country": shown.get("country") or None,
        "status": shown.get("status"),
        "users_online": shown.get("users_online"),
        "address": str(node.get("address") or node.get("host") or "")[:255],
        "xray_version": str(node.get("xrayVersion") or "")[:32] or None,
        "node_version": str(node.get("nodeVersion") or node.get("version") or "")[:32] or None,
        "last_status_message": str(node.get("lastStatusMessage") or "")[:300] or None,
    }


async def fetch_nodes(client=None) -> list[dict]:
    from .remnawave import RemnawaveClient
    from .tariff_api import _iter_nodes

    raw = await (client or RemnawaveClient()).list_nodes(start=0, size=500)
    return [node_row(n) for n in _iter_nodes(raw)]


def _redis():
    try:
        from . import main
        return main.redis_client
    except Exception:  # noqa: BLE001 — imported outside the app (scripts, tests)
        return None


async def node_snapshot(*, force: bool = False, redis=None, fetch=None) -> dict:
    """``{"nodes": [...], "fetched_at": iso, "cached": bool, "error": str|None}``."""
    redis = redis if redis is not None else _redis()
    if redis is not None and not force:
        try:
            raw = await redis.get(CACHE_KEY)
            if raw:
                return {**json.loads(raw), "cached": True}
        except Exception as exc:  # noqa: BLE001 — a cache error falls back to Remnawave
            logger.warning("Node cache read failed: %s", exc)
    try:
        nodes = await (fetch or fetch_nodes)()
        snap = {"nodes": nodes, "fetched_at": _now().isoformat(), "error": None}
    except Exception as exc:  # noqa: BLE001
        return {"nodes": [], "fetched_at": _now().isoformat(), "error": f"Remnawave недоступен: {str(exc)[:200]}", "cached": False}
    if redis is not None:
        try:
            await redis.set(CACHE_KEY, json.dumps(snap, ensure_ascii=False), ex=CACHE_TTL)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Node cache write failed: %s", exc)
    return {**snap, "cached": False}
