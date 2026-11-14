"""v28.147.0 (REQ-INFRA-0025): what /metrics lacked — request latency percentiles, disk, memory, CPU load, the process's
memory and the database connection pool. Counts and sizes only, nothing personal.

* latency: a pure ASGI middleware keeps the durations of the last 5000 HTTP requests (no extra dependency);
  ``vpnshop_http_request_seconds{quantile="0.5|0.95|0.99"}``;
* host: ``vpnshop_disk_free_bytes`` / ``vpnshop_disk_total_bytes`` for / and the media folder,
  ``vpnshop_memory_available_bytes`` / ``vpnshop_memory_total_bytes`` (/proc/meminfo), ``vpnshop_load1``,
  ``vpnshop_cpu_count``, ``vpnshop_process_resident_bytes``;
* database: ``vpnshop_db_pool_size`` and ``vpnshop_db_pool_checked_out``.

Loaded through ``routers.MODULES`` (main.py is kept under 1000 lines): on import it adds the middleware to the app,
which is allowed until the first request; the router is empty. observability.operational_metrics appends the lines.
"""
from __future__ import annotations

import os
import shutil
import time
from collections import deque

from fastapi import APIRouter

router = APIRouter()
__all__ = ["router", "LatencyMiddleware", "quantiles", "lines", "SAMPLES"]

SAMPLES: deque = deque(maxlen=5000)


class LatencyMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)
        started = time.perf_counter()
        try:
            return await self.app(scope, receive, send)
        finally:
            SAMPLES.append(time.perf_counter() - started)


def quantiles(samples, points=(0.5, 0.95, 0.99)) -> dict[float, float]:
    data = sorted(samples)
    if not data:
        return {}
    return {q: data[min(len(data) - 1, int(q * len(data)))] for q in points}


def _meminfo(path: str = "/proc/meminfo") -> dict[str, int]:
    out = {}
    try:
        for line in open(path, encoding="ascii"):
            key, _, rest = line.partition(":")
            parts = rest.split()
            if parts and parts[0].isdigit():
                out[key] = int(parts[0]) * 1024
    except OSError:
        pass
    return out


def _resident(path: str = "/proc/self/status") -> int | None:
    return _meminfo(path).get("VmRSS")


def _gauge(name: str, help_text: str, values: list[tuple[str, float]]) -> str:
    return f"# HELP {name} {help_text}\n# TYPE {name} gauge\n" + "".join(f"{name}{labels} {value}\n" for labels, value in values)


def lines(media_dir: str | None = None) -> str:
    out = []
    q = quantiles(list(SAMPLES))
    out.append(_gauge("vpnshop_http_request_seconds", "Request duration of the last 5000 HTTP requests",
                      [(f'{{quantile="{k}"}}', round(v, 4)) for k, v in q.items()]))
    out.append(_gauge("vpnshop_http_requests_sampled", "HTTP requests in the latency window", [("", len(SAMPLES))]))
    disks = []
    for label, path in (("root", "/"), ("media", media_dir)):
        if path and os.path.isdir(path):
            usage = shutil.disk_usage(path)
            disks.append((label, usage))
    out.append(_gauge("vpnshop_disk_free_bytes", "Free disk space", [(f'{{mount="{m}"}}', u.free) for m, u in disks]))
    out.append(_gauge("vpnshop_disk_total_bytes", "Disk size", [(f'{{mount="{m}"}}', u.total) for m, u in disks]))
    mem = _meminfo()
    if "MemTotal" in mem:
        out.append(_gauge("vpnshop_memory_total_bytes", "Memory of the host", [("", mem["MemTotal"])]))
        out.append(_gauge("vpnshop_memory_available_bytes", "Memory available to new processes", [("", mem.get("MemAvailable", 0))]))
    try:
        out.append(_gauge("vpnshop_load1", "Load average over one minute", [("", round(os.getloadavg()[0], 2))]))
    except OSError:
        pass
    out.append(_gauge("vpnshop_cpu_count", "CPUs visible to the process", [("", os.cpu_count() or 0)]))
    rss = _resident()
    if rss is not None:
        out.append(_gauge("vpnshop_process_resident_bytes", "Resident memory of this process", [("", rss)]))
    try:
        from .db import engine
        pool = engine.sync_engine.pool
        out.append(_gauge("vpnshop_db_pool_size", "Connections the pool keeps", [("", pool.size())]))
        out.append(_gauge("vpnshop_db_pool_checked_out", "Connections in use now", [("", pool.checkedout())]))
    except Exception:  # noqa: BLE001 — a pool without these counters (NullPool, SQLite in tests)
        pass
    return "".join(out)


try:  # loaded by main.py while it includes the routers: the app exists and has not served a request yet
    from .main import app as _app
    _app.add_middleware(LatencyMiddleware)
except Exception:  # noqa: BLE001 — imported elsewhere (tests, the worker)
    pass
