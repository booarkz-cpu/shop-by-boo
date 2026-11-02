"""v28.59.0 (stage 5): every API error is JSON with ``detail``; an unexpected failure also carries the request id."""
import httpx
import pytest
from fastapi import HTTPException

from app import main as shop
from app.db import get_db


@pytest.mark.asyncio
async def test_unexpected_failure_answers_json_with_the_request_id(monkeypatch):
    async def broken():
        raise RuntimeError("database exploded")
        yield
    monkeypatch.setitem(shop.app.dependency_overrides, get_db, broken)
    transport = httpx.ASGITransport(app=shop.app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
        response = await client.get("/api/public/config", headers={"X-Request-ID": "req-12345678"})
    assert response.status_code == 500
    body = response.json()
    assert body["request_id"] == "req-12345678" and "Внутренняя ошибка" in body["detail"]
    assert "database exploded" not in response.text  # the cause stays in the log, not in the answer


@pytest.mark.asyncio
async def test_expected_errors_keep_their_status_and_detail(monkeypatch):
    async def refused():
        raise HTTPException(409, "Тариф уже используется")
        yield
    monkeypatch.setitem(shop.app.dependency_overrides, get_db, refused)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=shop.app), base_url="http://localhost") as client:
        response = await client.get("/api/public/config")
    assert response.status_code == 409 and response.json() == {"detail": "Тариф уже используется"}


@pytest.mark.asyncio
async def test_remnawave_not_configured_is_a_clear_503(monkeypatch):
    """v28.61.0: an empty REMNAWAVE_URL used to reach the panel as an internal error from httpx."""
    from app import remnawave
    from app.config import settings
    monkeypatch.setattr(settings, "remnawave_url", "")
    with pytest.raises(remnawave.RemnawaveNotConfigured):
        await remnawave.RemnawaveClient().list_users(0, 25)
    request = type("R", (), {"state": type("S", (), {"request_id": "rid-1"})(), "headers": {}, "url": type("U", (), {"path": "/x"})()})()
    from app.errors import remnawave_error
    answer = await remnawave_error(request, remnawave.RemnawaveNotConfigured("x"))
    assert answer.status_code == 503 and "REMNAWAVE_URL" in answer.body.decode()
    failed = await remnawave_error(request, remnawave.RemnawaveError("GET /api/users: 500: secret user data"))
    assert failed.status_code == 502 and "secret" not in failed.body.decode()
