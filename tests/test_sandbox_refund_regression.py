"""Sandbox confirmation must use the same refund-safe path as webhooks."""
import importlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException


@pytest.mark.asyncio
@pytest.mark.parametrize("result,expected_status", [
    ({"ignored": True}, 409),
    ({"ignored": False}, None),
])
async def test_sandbox_completion_respects_refund_race(monkeypatch, result, expected_status):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "services" / "backend"))
    cabinet = importlib.import_module("app.cabinet_api")
    main = importlib.import_module("app.main")
    sandbox = importlib.import_module("app.sandbox_mode")
    monkeypatch.setattr(sandbox, "payments_sandbox_allowed", lambda: True)
    monkeypatch.setattr(main, "user_from_token", AsyncMock(return_value=SimpleNamespace(id=7)))
    confirm = AsyncMock(return_value=result)
    monkeypatch.setattr(main, "_confirm_and_fulfill_payment", confirm)

    payment = SimpleNamespace(id=13, user_id=7, status="refunded", fulfillment_status="pending")
    db = SimpleNamespace(
        execute=AsyncMock(return_value=Mock(scalar_one_or_none=lambda: payment)),
        refresh=AsyncMock(), commit=AsyncMock(),
    )
    if expected_status:
        with pytest.raises(HTTPException) as error:
            await cabinet.sandbox_complete({"order_id": "sandbox-order"}, Mock(), db)
        assert error.value.status_code == expected_status
        db.refresh.assert_not_awaited()
    else:
        response = await cabinet.sandbox_complete({"order_id": "sandbox-order"}, Mock(), db)
        assert response["payment_id"] == payment.id
        db.refresh.assert_awaited_once_with(payment)
    confirm.assert_awaited_once_with(payment.id, db)
    assert payment.status == "refunded"  # The endpoint itself never rewrites the status.
    db.commit.assert_not_awaited()
