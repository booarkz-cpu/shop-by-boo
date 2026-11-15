"""v28.146.0 (REQ-INFRA-0024): structured logs. With ``LOG_FORMAT=json`` every log line of the backend and the worker is
one JSON object — time, level, logger, message, the request's correlation ID (``X-Request-ID``, ``system`` outside a
request) and the exception, if any — so a log collector can filter one request across services without parsing text.
The default stays the plain text format.

Loaded through ``routers.MODULES`` (main.py is kept under 1000 lines); the router is empty.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter

router = APIRouter()
__all__ = ["router", "JsonFormatter", "install"]


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        try:
            from .main import _REQUEST_ID
            request_id = _REQUEST_ID.get()
        except Exception:  # noqa: BLE001 — before main is imported (the worker, the CLI)
            request_id = "system"
        line = {"time": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
                "level": record.levelname, "logger": record.name, "message": record.getMessage(), "request_id": request_id}
        if record.exc_info:
            line["exception"] = self.formatException(record.exc_info)
        return json.dumps(line, ensure_ascii=False)


def install(fmt: str | None = None) -> bool:
    """Switches the root logger (and uvicorn's) to JSON when ``LOG_FORMAT=json``. Returns whether it did."""
    if (fmt if fmt is not None else os.environ.get("LOG_FORMAT", "text")).strip().lower() != "json":
        return False
    formatter = JsonFormatter()
    root = logging.getLogger()
    if not root.handlers:
        root.addHandler(logging.StreamHandler())
    for name in ("", "uvicorn", "uvicorn.error", "uvicorn.access"):
        for handler in logging.getLogger(name).handlers:
            handler.setFormatter(formatter)
    return True


install()
