"""The first payment of the day per provider must not crash on empty metric counters.

Column ``default=0`` is applied by SQLAlchemy only at INSERT, so a freshly
constructed ``PaymentProviderMetric`` has ``None`` counters until it is flushed.
"""
import importlib
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest


@pytest.fixture
def shop(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "backend"))
    return importlib.import_module("app.main")


def _db(existing=None):
    result = Mock()
    result.scalar_one_or_none.return_value = existing
    db = Mock()
    db.execute = AsyncMock(return_value=result)
    db.add = Mock()
    return db


@pytest.mark.asyncio
async def test_first_metric_of_the_day_starts_from_zero(shop):
    db = _db(existing=None)
    await shop._record_provider_metric(db, "sandbox", attempt=1, success=1, gross=Decimal("100"), fee=Decimal("3"))
    db.add.assert_called_once()
    row = db.add.call_args.args[0]
    assert isinstance(row, shop.PaymentProviderMetric)
    assert (row.attempts, row.succeeded, row.failed, row.refunded) == (1, 1, 0, 0)
    assert row.gross_amount == Decimal("100")
    assert row.fees_amount == Decimal("3")
    assert row.net_amount == Decimal("97")


@pytest.mark.asyncio
async def test_existing_metric_row_accumulates(shop):
    row = shop.PaymentProviderMetric(provider="sandbox", day="2026-10-22", attempts=2, succeeded=1, failed=1, refunded=0,
                                     gross_amount=Decimal("50"), fees_amount=Decimal("1"), net_amount=Decimal("49"))
    db = _db(existing=row)
    await shop._record_provider_metric(db, "sandbox", attempt=1, failed=1)
    db.add.assert_not_called()
    assert (row.attempts, row.succeeded, row.failed) == (3, 1, 2)
    assert row.net_amount == Decimal("49")
