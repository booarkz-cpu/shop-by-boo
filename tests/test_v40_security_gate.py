from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app import main as shop
from app_contract import permissions
from test_behaviour_payments_v2 import checkout
from test_subscription_commerce import database  # noqa: F401

ROOT=Path(__file__).resolve().parents[1]
def read(rel): return (ROOT/rel).read_text(encoding="utf-8")

def test_admin_frontend_identifiers_are_valid_and_staging_secret_preservation_is_supported():
    s=read("admin/src/main.tsx")
    assert "function Workers(" in s and "function Jobs(" in s
    assert "<Рабочие процессы" not in s and "<Задачаs" not in s
    assert "сохранить текущий" in s

@pytest.mark.asyncio
async def test_real_payments_are_open_by_default_with_an_emergency_switch(database, monkeypatch):
    from app.staging_e2e_api import production_payments_allowed
    assert permissions("POST", "/api/admin/payments/production-gate") == {"security.manage"}
    assert await production_payments_allowed(database) is True
    admin = SimpleNamespace(email="owner@corgi.test")
    assert await shop.production_payment_gate(shop.ProductionGateIn(enabled=False), database, admin) == {"enabled": False}
    monkeypatch.setattr(shop, "production_payments_allowed", production_payments_allowed)

    async def no(*a, **k):
        return False
    monkeypatch.setattr(shop, "e2e_checkout_allowed", no)
    with pytest.raises(HTTPException) as closed:
        await shop.create_payment({"plan_id": 1, "provider": "yookassa"}, checkout([(b"idempotency-key", b"k-gate")]), database)
    assert (closed.value.status_code, closed.value.detail) == (503, "Приём платежей временно остановлен администратором")
    await shop.production_payment_gate(shop.ProductionGateIn(enabled=True), database, admin)
    assert await production_payments_allowed(database) is True


@pytest.mark.asyncio
async def test_staging_internal_endpoint_is_loopback_only(database):
    from app.staging_e2e_api import _require_staging_runner

    def req(host):
        return Request({"type": "http", "method": "POST", "path": "/api/internal/staging-e2e/payment", "client": (host, 1), "query_string": b"",
                        "headers": [(b"x-staging-runner-token", b"whatever")]})
    with pytest.raises(HTTPException) as remote:
        await _require_staging_runner(req("203.0.113.5"), database)
    assert remote.value.detail == "Staging endpoint доступен только локальному runner"
    with pytest.raises(HTTPException) as no_config:
        await _require_staging_runner(req("127.0.0.1"), database)
    assert no_config.value.detail == "Недействительный staging runner token", "loopback still needs the runner token"


def test_admin_auth_has_rate_limits_for_both_login_paths():
    assert shop.RATE_LIMITS["/api/admin/auth/login"] == 8 and shop.RATE_LIMITS["/api/admin/auth/telegram"] == 8
