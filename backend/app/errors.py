"""One error format for every client (v28.59.0, stage 5).

Expected errors are ``HTTPException`` (``{"detail": ...}``) and validation errors (422). An unexpected
failure used to reach the client as Starlette's plain-text «Internal Server Error»; now it answers JSON
with the request id, and the cause is logged with the same id instead of being sent to the client."""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("remnawave")


async def unhandled_error(request: Request, exc: Exception) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "") or request.headers.get("X-Request-ID", "")
    logger.error("unhandled error request_id=%s method=%s path=%s", request_id, request.method, request.url.path,
                 exc_info=(type(exc), exc, exc.__traceback__))
    return JSONResponse({"detail": "Внутренняя ошибка сервера. Сообщите код запроса в поддержку.", "request_id": request_id},
                        status_code=500, headers={"X-Request-ID": request_id} if request_id else None)


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(Exception, unhandled_error)
