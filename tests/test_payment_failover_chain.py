"""The whole reserve chain: ЮKassa → RollyPay → Platega → CryptoBot → Freekassa.

Each gateway that fails three times in a row cools down and the next order goes to the next one; the operator
reorders the queue and brings a fixed gateway back from the admin panel (web and mobile use the same API)."""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app import enterprise_api
from app import main as shop
from app import payments_api
from app.models import Payment, PaymentProviderHealth
from test_behaviour_payments_v2 import FakeRedis, checkout
from test_cryptobot import TOKEN, api  # noqa: F401
from test_subscription_commerce import database  # noqa: F401

ADMIN = SimpleNamespace(email="owner@corgi.test")
STATE = {"down": set(), "calls": []}


def gateway(name):
    class Fake:
        async def create(self, amount, order_id, description, return_url, method=""):
            STATE["calls"].append(name)
            if name in STATE["down"]:
                raise RuntimeError(f"{name} timeout")
            return {"id": f"{name}-{order_id}", "url": f"https://pay.{name}.test/{order_id}"}
    return Fake


async def quiet(*a, **k):
    return None


@pytest.fixture
def shop_env(database, monkeypatch, api):  # noqa: F811
    async def yes(*a, **k):
        return True

    async def risk(*a):
        return 0, "allow", {}
    STATE["down"].clear(); STATE["calls"].clear()
    for name, value in {"_risk_score": risk, "production_payments_allowed": yes, "e2e_checkout_allowed": yes, "redis_client": FakeRedis(),
                        "YooKassaProvider": gateway("yookassa"), "RollyPayProvider": gateway("rollypay"), "PlategaProvider": gateway("platega"),
                        "audit": quiet, "engine": database.bind, "payments_sandbox_allowed": lambda: False}.items():
        monkeypatch.setattr(shop, name, value)
    monkeypatch.setattr(shop, "_release_payment_side_effect_lock", payments_api._release_payment_side_effect_lock)
    for name, value in {"yookassa_shop_id": "shop", "yookassa_secret_key": "key", "yookassa_webhook_ip_allowlist": "185.71.76.0/27",
                        "rollypay_api_key": "rk", "rollypay_signing_secret": "rs", "platega_merchant_id": "pm", "platega_secret": "ps",
                        "cryptobot_token": TOKEN, "freekassa_shop_id": "7012", "freekassa_secret1": "s1", "freekassa_secret2": "s2",
                        "freekassa_api_key": "fk"}.items():
        monkeypatch.setattr(shop.settings, name, value)
    return database


counter = {"n": 0}


async def buy(db):
    """One checkout; afterwards the order is settled so the next checkout is not «the same open order»."""
    counter["n"] += 1
    key = f"chain-{counter['n']}"
    try:
        out = await shop.create_payment({"plan_id": 1}, checkout([(b"idempotency-key", key.encode())]), db)
    except HTTPException as exc:
        out = {"error": exc.status_code}
    row = await db.scalar(select(Payment).where(Payment.idempotency_key == key))
    provider = row.provider if row else None
    if row:
        row.status = "failed"
        await db.commit()
    return provider, out


async def fail_three_times(db, name):
    STATE["down"].add(name)
    for _ in range(3):
        provider, out = await buy(db)
        assert provider == name and out == {"error": 503}, (provider, out)


@pytest.mark.asyncio
async def test_orders_walk_down_the_whole_chain_and_the_operator_steers_it(shop_env):
    db = shop_env
    assert (await buy(db))[0] == "yookassa", "the main gateway first"
    for current, following in (("yookassa", "rollypay"), ("rollypay", "platega"), ("platega", "cryptobot")):
        await fail_three_times(db, current)
        provider, out = await buy(db)
        assert provider == following and "error" not in out, f"after {current} the order goes to {following}"
    queue = {row["provider"]: row for row in await enterprise_api.v41_providers(db, ADMIN)}
    assert [p for p, r in queue.items() if r["cooling"]] == ["yookassa", "rollypay", "platega"]
    assert all(r["configured"] for r in queue.values())

    # The operator puts Freekassa above CryptoBot: the next order goes there.
    await enterprise_api.v41_provider_update("freekassa", enterprise_api.ProviderHealthIn(enabled=True, priority=35), db, ADMIN)
    assert (await buy(db))[0] == "freekassa"
    # ЮKassa is fixed: «Вернуть в работу» ends its cooldown and it is first again.
    STATE["down"].discard("yookassa")
    await enterprise_api.v41_provider_reset("yookassa", db, ADMIN)
    health = await db.scalar(select(PaymentProviderHealth).where(PaymentProviderHealth.provider == "yookassa").execution_options(populate_existing=True))
    assert (health.failure_count, health.circuit_open_until) == (0, None)
    assert (await buy(db))[0] == "yookassa"
    # A disabled gateway is skipped even when it is first and healthy.
    await enterprise_api.v41_provider_update("yookassa", enterprise_api.ProviderHealthIn(enabled=False, priority=10), db, ADMIN)
    assert (await buy(db))[0] == "freekassa"


@pytest.mark.asyncio
async def test_every_agent_can_be_managed_and_unknown_ones_are_refused(shop_env):
    db = shop_env
    await shop._payment_provider_order(db, None)  # bootstraps the rows
    for name in ("cryptobot", "freekassa", "platega", "rollypay"):
        await enterprise_api.v41_provider_update(name, enterprise_api.ProviderHealthIn(enabled=True, priority=50), db, ADMIN)
    with pytest.raises(HTTPException) as unknown:
        await enterprise_api.v41_provider_reset("paypal", db, ADMIN)
    assert unknown.value.status_code == 404


@pytest.mark.asyncio
async def test_launch_checks_ask_for_a_second_gateway(database, monkeypatch):
    from app import ops_alerts
    for name in ("rollypay_api_key", "platega_merchant_id", "cryptobot_token", "freekassa_shop_id"):
        monkeypatch.setattr(shop.settings, name, "")
    monkeypatch.setattr(shop.settings, "yookassa_shop_id", "shop")
    monkeypatch.setattr(shop.settings, "yookassa_secret_key", "key")
    checks = {c["key"]: c for c in (await ops_alerts.readiness(database, None))["checks"]}
    assert checks["payments"]["ok"] and not checks["reserve_payments"]["ok"] and checks["reserve_payments"]["level"] == "recommended"
    monkeypatch.setattr(shop.settings, "cryptobot_token", TOKEN)
    checks = {c["key"]: c for c in (await ops_alerts.readiness(database, None))["checks"]}
    assert checks["reserve_payments"]["ok"]


@pytest.mark.asyncio
async def test_launch_checks_cover_the_new_safety_nets(database, monkeypatch):
    from app import ops_alerts, telegram_backup
    monkeypatch.setattr(shop.settings, "api_mirror_domains", "")
    checks = {c["key"]: c for c in (await ops_alerts.readiness(database, None))["checks"]}
    for key in ("telegram_backup", "api_mirrors", "support_ai"):
        assert not checks[key]["ok"] and checks[key]["level"] == "recommended" and checks[key]["hint"]
    await telegram_backup.save(database, {**telegram_backup.DEFAULT, "enabled": True, "chat_id": "-1001234567890"})
    await database.commit()
    monkeypatch.setattr(shop.settings, "api_mirror_domains", "api2.corgi.test")
    checks = {c["key"]: c for c in (await ops_alerts.readiness(database, None))["checks"]}
    assert checks["telegram_backup"]["ok"] and checks["api_mirrors"]["ok"]
