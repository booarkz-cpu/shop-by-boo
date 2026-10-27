from pathlib import Path

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app import main as shop
from app_contract import missing_paths, tables

ROOT=Path(__file__).parents[1]

# v28.32.0: the user lock, the webhook order and the provider-scoped event claim are run in
# tests/test_behaviour_payments_v2.py instead of being looked up in the source.
# Restore archive safety runs in test_v20_v21_release.py.
def test_v23_provisioning_operation_and_recovery_routes():
    assert {'provisioning_operations', 'worker_states'} <= set(tables())
    assert callable(shop.RemnawaveClient.get_user_by_username)
    assert not missing_paths('/api/admin/recovery', '/api/admin/incident-mode', '/api/admin/referrals/reconcile')


@pytest.mark.asyncio
async def test_metrics_need_their_own_token(monkeypatch):
    def req(token=""):
        return Request({"type": "http", "method": "GET", "path": "/metrics", "client": ("10.0.0.1", 1), "query_string": b"",
                        "headers": [(b"x-metrics-token", token.encode())]})
    monkeypatch.setattr(shop.settings, "metrics_enabled", False)
    with pytest.raises(HTTPException) as off:
        await shop.metrics(req())
    assert off.value.status_code == 404
    monkeypatch.setattr(shop.settings, "metrics_enabled", True)
    monkeypatch.setattr(shop.settings, "metrics_token", "")
    with pytest.raises(HTTPException) as unset:
        await shop.metrics(req("anything"))
    assert (unset.value.status_code, unset.value.detail) == (503, "Metrics authentication is not configured"), "never open by default"
    monkeypatch.setattr(shop.settings, "metrics_token", "m" * 32)
    with pytest.raises(HTTPException) as wrong:
        await shop.metrics(req("x" * 32))
    assert wrong.value.status_code == 401
    body = await shop.metrics(req("m" * 32))
    assert "requests_total" in getattr(body, "body", b"").decode()
