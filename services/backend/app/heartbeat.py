"""Liveness files for the services without an HTTP port: worker, bot and mail receiver (v28.58.0, BUG-A6).

These services had no healthcheck: a worker whose loop hung on the database or Redis was shown as
running, and nothing waiting on it could tell. With a healthcheck Docker marks it «unhealthy» (visible in
``docker compose ps``, ``docker inspect`` and ``depends_on: condition: service_healthy``). Each service now touches
``/tmp/<name>.alive`` (``/tmp`` is a tmpfs in compose) — the worker only after a successful heartbeat
to PostgreSQL and Redis — and its healthcheck runs ``python -m app.heartbeat <name> <max-age>``.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import sys
import time
from pathlib import Path


def _path(name: str) -> Path:
    return Path(os.environ.get("HEARTBEAT_DIR", "/tmp")) / f"{name}.alive"


def beat(name: str) -> None:
    # A read-only /tmp only makes the healthcheck fail, which is the signal we want.
    with contextlib.suppress(OSError):
        _path(name).write_text(str(int(time.time())))


def fresh(name: str, max_age: float) -> bool:
    try:
        return time.time() - _path(name).stat().st_mtime <= max_age
    except OSError:
        return False


async def keep_beating(name: str, interval: float = 30) -> None:
    """For services whose only work is an event loop: proves the loop still runs."""
    while True:
        beat(name)
        await asyncio.sleep(interval)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: python -m app.heartbeat <name> <max-age-seconds>")
    sys.exit(0 if fresh(sys.argv[1], float(sys.argv[2])) else 1)
