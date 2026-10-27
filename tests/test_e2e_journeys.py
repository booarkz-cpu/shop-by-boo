"""End-to-end journeys across modules, with only the outside world replaced (gateways, Remnawave, systemd):

* the main gateway fails → its circuit opens → the reserve gateway (CryptoBot) takes the order → its signed
  webhook pays it → the subscription is extended in Remnawave → every client sees it through /api/me/sync;
* a YooKassa recurring charge is tried three times, then auto-renew stops and never charges again;
* the panel asks for an update → the server agent installs it → a failed release is rolled back and reported →
  the owner retries from the panel → the new release is installed.
Deep links (corgi://login, corgi://payment) are covered in test_app_login.py and test_integration_billing_vpn.py."""
import json
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from starlette.requests import Request

from app import account_sync, payments_api
from app import main as shop
from app.models import AutoRenewMethod, Payment, PaymentProviderHealth, Subscription, User
from test_auto_update_agent import agent  # noqa: F401
from test_behaviour_payments_v2 import FakeRedis, checkout
from test_cryptobot import TOKEN, api, signed  # noqa: F401
from test_integration_billing_vpn import panel  # noqa: F401
from test_money_review import _renewable, _scheduler_env
from test_subscription_commerce import database  # noqa: F401


async def quiet(*a, **k):
    return None


class Down:
    async def create(self, *a, **k):
        raise RuntimeError("YooKassa timeout")


@pytest.mark.asyncio
async def test_reserve_gateway_takes_over_and_the_paid_order_reaches_every_client(database, panel, api, monkeypatch):  # noqa: F811
    db = database
    if db.bind.dialect.name != "postgresql":
        pytest.skip("the webhook path uses PostgreSQL interval arithmetic, as in production")

    async def yes(*a, **k):
        return True

    async def risk(*a):
        return 0, "allow", {}
    for name, value in {"_risk_score": risk, "production_payments_allowed": yes, "e2e_checkout_allowed": yes,
                        "redis_client": FakeRedis(), "YooKassaProvider": Down, "notify_user_telegram": quiet,
                        # Side sessions (provider events, audit) must use this test's database, not the app engine.
                        "engine": db.bind}.items():
        monkeypatch.setattr(shop, name, value)
    for name, value in {"yookassa_shop_id": "shop", "yookassa_secret_key": "key", "yookassa_webhook_ip_allowlist": "185.71.76.0/27",
                        "cryptobot_token": TOKEN}.items():
        monkeypatch.setattr(shop.settings, name, value)
    # The commerce fixture stubs lock release; the journey needs the real one with the in-memory Redis.
    monkeypatch.setattr(shop, "_release_payment_side_effect_lock", payments_api._release_payment_side_effect_lock)
    remote = str(uuid.uuid4())
    sub = await db.get(Subscription, 1)
    sub.remnawave_uuid, sub.expires_at = remote, datetime.utcnow() + timedelta(days=5)
    panel.users[remote] = {"uuid": remote, "id": remote, "username": "corgi_1", "status": "ACTIVE",
                           "expireAt": sub.expires_at.isoformat(), "subscriptionUrl": "https://sub.corgi.test/one"}
    await db.commit()

    # 1. The main gateway does not answer three times in a row: its circuit opens.
    for attempt in range(3):
        with pytest.raises(HTTPException) as down:
            await shop.create_payment({"plan_id": 1}, checkout([(b"idempotency-key", f"down-{attempt}".encode())]), db)
        assert down.value.status_code == 503, down.value.detail
        uncertain = await db.scalar(select(Payment).where(Payment.idempotency_key == f"down-{attempt}"))
        uncertain.status = "failed"  # reconciliation settled it: never charged
        await db.commit()
    health = await db.scalar(select(PaymentProviderHealth).where(PaymentProviderHealth.provider == "yookassa").execution_options(populate_existing=True))
    assert health.failure_count == 3 and health.circuit_open_until > datetime.utcnow()

    # 2. The next order goes to CryptoBot without anyone switching anything.
    before = json.loads((await account_sync.my_sync(Request({"type": "http", "method": "GET", "path": "/api/me/sync", "headers": [],
                                                                "query_string": b"", "client": ("10.0.0.1", 1)}), db=db)).body)
    out = await shop.create_payment({"plan_id": 1}, checkout([(b"idempotency-key", b"reserve-1")]), db)
    assert out["id"] == "777" and out["url"].startswith("https://t.me/CryptoBot")
    payment = await db.scalar(select(Payment).where(Payment.idempotency_key == "reserve-1"))
    assert payment.provider == "cryptobot" and payment.status == "pending"
    payment_id, order_id = payment.id, payment.order_id
    api.invoice.update({"payload": order_id, "amount": str(payment.amount)})

    # 3. Its signed webhook pays the order and the subscription is extended in Remnawave.
    update = {"update_type": "invoice_paid", "payload": {"invoice_id": 777, "status": "paid", "payload": order_id}}
    assert (await shop.cryptobot_webhook(signed(update), db))["ok"] is True
    paid = await db.scalar(select(Payment).where(Payment.id == payment_id).execution_options(populate_existing=True))
    assert paid.status == "paid" and paid.fulfillment_status == "completed"
    assert panel.count("POST", "/actions/extend") == 1

    # 4. Every client reading /api/me/sync sees the new state.
    after = json.loads((await account_sync.my_sync(Request({"type": "http", "method": "GET", "path": "/api/me/sync", "headers": [],
                                                               "query_string": b"", "client": ("10.0.0.1", 1)}), since=before["version"], db=db)).body)
    assert after["version"] != before["version"]
    assert after["subscriptions"][0]["expires_at"] > before["subscriptions"][0]["expires_at"]


@pytest.mark.asyncio
async def test_a_recurring_charge_is_tried_three_times_then_auto_renew_stops(database, monkeypatch):
    charges = []
    _scheduler_env(monkeypatch, database, charges)
    statuses = iter(["canceled", "canceled", "canceled"])

    async def charge(self, amount, order_id, desc, token):
        charges.append(order_id)
        return {"id": f"yk-{len(charges)}"}

    async def status(self, payment_id):
        return next(statuses)
    monkeypatch.setattr(shop.YooKassaProvider, "charge_recurring", charge)
    monkeypatch.setattr(shop.YooKassaProvider, "get_payment_status", status)
    monkeypatch.setattr(shop, "_acquire_payment_side_effect_lock", lambda *a, **k: _lock())
    await _renewable(database)
    for _ in range(8):
        sub = await database.get(Subscription, 1)
        sub.next_renewal_at = None  # the backoff has passed
        await database.commit()
        await shop.run_auto_renew_pass(database)
    method = await database.scalar(select(AutoRenewMethod).execution_options(populate_existing=True))
    user = await database.scalar(select(User).where(User.id == 1).execution_options(populate_existing=True))
    assert len(charges) == 3 and len(set(charges)) == 3, (charges, method.status, method.failure_count, method.last_error)
    assert (method.status, method.enabled, user.auto_renew_enabled) == ("payment_failed", False, False)


async def _lock():
    return ("k", "t")


@pytest.mark.asyncio
async def test_panel_agent_update_rollback_and_retry(agent, tmp_path, monkeypatch):  # noqa: F811
    from types import SimpleNamespace

    from app import auto_update_api as panel_api

    class Db:
        async def commit(self):
            return None
    monkeypatch.setenv("AUTO_UPDATE_CONTROL_DIR", str(agent.CONTROL_DIR))
    monkeypatch.setattr(shop, "audit", quiet)
    owner = SimpleNamespace(email="owner@corgi.test")
    agent.cmd_install()
    agent.cmd_agent()  # the agent reports itself to the panel

    # The panel asks for an update; the release fails its checks and update.sh rolls back to 28.33.0.
    agent.state["result"] = 1
    asked = await panel_api.run_auto_update(Db(), owner)
    agent.cmd_agent()
    seen = panel_api.read_state()["status"]
    assert (seen["last_result"], seen["installed"]) == ("failed", "28.33.0")
    assert agent.state["runs"] == 1 and "не удалось" in agent.notes[-1]
    assert json.loads(agent.STATUS.read_text())["handled_check_now"] == asked["requested"]

    # The nightly schedule does not repeat a failed release, but the owner may retry it from the panel.
    assert agent.run_update() == "skipped"
    agent.state["result"] = 0
    await panel_api.run_auto_update(Db(), owner)
    agent.cmd_agent()
    seen = panel_api.read_state()["status"]
    assert (seen["last_result"], seen["installed"]) == ("updated", "28.34.0")
