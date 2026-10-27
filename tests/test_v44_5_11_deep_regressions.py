"""v44.5.11: lost YooKassa create answers are recovered by order id, never re-created
(was: code lines searched in main.py and payments.py). Trial snapshots reach the panel: test_v44_5_9_deep_regressions.py."""
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app import main as shop
from app import payments
from app.models import Payment
from app_contract import tables
from test_subscription_commerce import database  # noqa: F401


def test_webhook_event_conflict_target_matches_database_constraint():
    unique = {tuple(c.name for c in con.columns) for con in tables()["payment_provider_events"].constraints if con.__class__.__name__ == "UniqueConstraint"}
    assert ("provider", "event_id") in unique


@pytest.mark.asyncio
async def test_a_lost_create_is_found_by_order_id_and_never_created_again(database, monkeypatch):
    database.add(Payment(user_id=1, subscription_id=1, plan_id=1, provider="yookassa", order_id="o-lost", amount=Decimal("100"),
                         currency="RUB", status="creation_unknown", fulfillment_terminal=True, idempotency_key="k-lost"))
    await database.commit()
    created, looked_up = [], []

    async def find(self, order_id, created_after=None):
        looked_up.append(order_id)
        return {"id": "yk-found", "confirmation": {"confirmation_url": "https://yoomoney.ru/checkout/1"}}

    async def create(self, *a, **k):
        created.append(a)
        return {"id": "yk-new"}

    async def unpaid(self, *a, **k):
        return False
    monkeypatch.setattr(shop.YooKassaProvider, "find_by_order_id", find)
    monkeypatch.setattr(shop.YooKassaProvider, "create", create)
    monkeypatch.setattr(shop.YooKassaProvider, "verify_succeeded", unpaid)
    out = await shop.reconcile_payments(database, SimpleNamespace(email="a@b.c"))
    row = await database.scalar(select(Payment).where(Payment.order_id == "o-lost").execution_options(populate_existing=True))
    assert out["creation_unknown_recovered"] == 1 and looked_up == ["o-lost"] and created == []
    assert (row.provider_payment_id, row.status, row.fulfillment_terminal) == ("yk-found", "pending", False)
    assert row.checkout_url == "https://yoomoney.ru/checkout/1"


@pytest.mark.asyncio
async def test_yookassa_uses_the_shop_order_as_its_idempotence_key(monkeypatch):
    sent = []

    class Client:
        is_closed = False

        async def post(self, url, json=None, headers=None, auth=None, **kw):
            sent.append(headers)
            return type("R", (), {"raise_for_status": lambda self: None, "json": lambda self: {
                "id": "yk-1", "status": "pending", "confirmation": {"confirmation_url": "https://pay"}}})()
    provider = payments.YooKassaProvider()

    async def client():
        return Client()
    monkeypatch.setattr(provider, "_get_client", client)
    await provider.create(Decimal("100"), "order-77", "VPN", "https://shop.example/paid")
    await provider.create(Decimal("100"), "order-77", "VPN", "https://shop.example/paid")
    assert [h["Idempotence-Key"] for h in sent] == ["order-77", "order-77"], "a repeated create returns the same YooKassa payment"


@pytest.mark.asyncio
async def test_find_by_order_id_matches_the_metadata_order(monkeypatch):
    pages = [{"items": [{"id": "yk-a", "metadata": {"order_id": "other"}}], "next_cursor": "c2"},
             {"items": [{"id": "yk-b", "metadata": {"order_id": "order-9"}}]}]
    seen = []

    class Client:
        async def get(self, url, auth=None, params=None):
            seen.append(params)
            page = pages[len(seen) - 1]
            return type("R", (), {"raise_for_status": lambda self: None, "json": lambda self: page})()

    @asynccontextmanager
    async def client(timeout):
        yield Client()
    monkeypatch.setattr(payments, "_public_client", client)
    found = await payments.YooKassaProvider().find_by_order_id("order-9", datetime(2026, 10, 1) - timedelta(hours=1))
    assert found["id"] == "yk-b" and seen[1]["cursor"] == "c2" and seen[0]["created_at.gte"].startswith("2026-09-30T23:00:00")
