"""v28.32.0: behaviour tests for the payment path after its move to payments_api.py.

Each test replaces an ``assert '<code line>' in MAIN`` of test_v23_reliability.py: the webhook
verifies the provider object before it claims the event, provider events are claimed once per
provider, checkout validates the plan and needs an idempotency key, and provisioning is
serialised per user with a distributed lock."""
import json
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from starlette.requests import Request

from app import main as shop
from app.models import Payment
from test_subscription_commerce import database  # noqa: F401


def webhook(body: dict, ip="10.1.2.3"):
    raw = json.dumps(body).encode()

    async def receive():
        return {"type": "http.request", "body": raw, "more_body": False}
    return Request({"type": "http", "method": "POST", "path": "/api/webhooks/yookassa", "headers": [(b"content-type", b"application/json")],
                    "client": (ip, 443), "query_string": b""}, receive)


@pytest.mark.asyncio
async def test_yookassa_webhook_verifies_the_payment_before_claiming_the_event(database, monkeypatch):
    """Was: MAIN.index('verify_succeeded(...)') < MAIN.index('register_provider_event(db,"yookassa"')."""
    database.add(Payment(user_id=1, subscription_id=1, plan_id=1, provider="yookassa", order_id="yk-order", provider_payment_id="yk-1",
                         amount=Decimal("100"), currency="RUB", status="pending", idempotency_key="yk-idem"))
    await database.commit()
    monkeypatch.setattr(shop.settings, "yookassa_webhook_ip_allowlist", "10.0.0.0/8")
    claimed, verified = [], []

    async def verify(self, pid, amount, currency, order_id):
        verified.append((pid, amount, currency, order_id))
        return False  # the provider does not confirm this payment

    async def claim(*args, **kwargs):
        claimed.append(args[1:3])
        return True
    monkeypatch.setattr(shop.YooKassaProvider, "verify_succeeded", verify)
    monkeypatch.setattr(shop, "register_provider_event", claim)
    body = {"id": "evt-1", "event": "payment.succeeded", "object": {"id": "yk-1", "metadata": {"order_id": "yk-order"}}}
    with pytest.raises(HTTPException) as unverified:
        await shop.yookassa_webhook(webhook(body), database)
    assert unverified.value.status_code == 503
    assert verified == [("yk-1", Decimal("100"), "RUB", "yk-order")] and claimed == [], "nothing is claimed for an unverified payment"
    # An address outside the allowlist is refused before anything is read.
    with pytest.raises(HTTPException) as outside:
        await shop.yookassa_webhook(webhook(body, ip="203.0.113.9"), database)
    assert outside.value.status_code == 403 and len(verified) == 1
    # A metadata order that is not the stored one is refused too.
    body["object"]["metadata"]["order_id"] = "someone-else"
    with pytest.raises(HTTPException) as mismatch:
        await shop.yookassa_webhook(webhook(body), database)
    assert mismatch.value.status_code in (403, 503)
    assert claimed == []


@pytest.mark.asyncio
async def test_provider_events_are_claimed_once_per_provider(database):
    """Was: 'ON CONFLICT (provider,event_id) DO UPDATE' and 'payment_provider_events.provider = EXCLUDED.provider' in MAIN."""
    if database.bind.dialect.name != "postgresql":
        pytest.skip("provider event claims use PostgreSQL upserts")
    assert await shop.register_provider_event(database, "yookassa", "evt-7", None) is True
    assert await shop.register_provider_event(database, "yookassa", "evt-7", None) is False, "a processing event is not claimed twice"
    assert await shop.register_provider_event(database, "platega", "evt-7", None) is True, "the same id of another provider is its own event"
    await shop.finish_provider_event(database, "yookassa", "evt-7", ok=False, error="boom")
    assert await shop.register_provider_event(database, "yookassa", "evt-7", None) is True, "a failed event is retried"
    await shop.finish_provider_event(database, "yookassa", "evt-7", ok=True)
    assert await shop.register_provider_event(database, "yookassa", "evt-7", None) is False, "a processed event is immutable"
    attempts = (await database.execute(text("SELECT attempts FROM payment_provider_events WHERE provider='yookassa' AND event_id='evt-7'"))).scalar_one()
    assert attempts == 2
    assert await shop.register_provider_event(database, "yookassa", "", None) is True, "events without an id are not deduplicated"


def checkout(headers=()):
    return Request({"type": "http", "method": "POST", "path": "/api/payments/create", "headers": list(headers), "client": ("10.0.0.1", 1), "query_string": b""})


@pytest.mark.asyncio
async def test_checkout_validates_the_plan_and_needs_an_idempotency_key(database, monkeypatch):
    """Was: 'raise HTTPException(400,"Invalid plan_id")' and the idempotency key format in MAIN."""
    async def yes(*args, **kwargs):
        return True
    monkeypatch.setattr(shop, "production_payments_allowed", yes)
    monkeypatch.setattr(shop, "e2e_checkout_allowed", yes)
    for plan in ("abc", None, [1]):
        with pytest.raises(HTTPException) as bad:
            await shop.create_payment({"plan_id": plan, "provider": "yookassa"}, checkout([(b"idempotency-key", b"k1")]), database)
        assert (bad.value.status_code, bad.value.detail) == (400, "Invalid plan_id")
    with pytest.raises(HTTPException) as no_key:
        await shop.create_payment({"plan_id": 1, "provider": "yookassa"}, checkout(), database)
    assert (no_key.value.status_code, no_key.value.detail) == (400, "Idempotency-Key is required")
    with pytest.raises(HTTPException) as long_key:
        await shop.create_payment({"plan_id": 1, "provider": "yookassa"}, checkout([(b"idempotency-key", b"x" * 129)]), database)
    assert long_key.value.status_code == 400


class FakeRedis:
    def __init__(self):
        self.keys = {}

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.keys:
            return False
        self.keys[key] = value
        return True

    async def eval(self, script, n, key, token, *ttl):
        if ttl:
            return 1 if self.keys.get(key) == token else 0  # lease renewal
        if self.keys.get(key) == token:
            del self.keys[key]
            return 1
        return 0



@pytest.mark.asyncio
async def test_provisioning_is_serialised_per_user(monkeypatch):
    """Was: 'lock:fulfill:user:' in MAIN."""
    redis = FakeRedis()
    monkeypatch.setattr(shop, "redis_client", redis)
    key, token = await shop._acquire_user_fulfillment_lock(5)
    assert key == "lock:fulfill:user:5"
    with pytest.raises(HTTPException) as busy:
        await shop._acquire_user_fulfillment_lock(5)
    assert (busy.value.status_code, busy.value.detail) == (409, "User provisioning/deletion is already in progress")
    other, other_token = await shop._acquire_user_fulfillment_lock(6)  # another customer is not blocked
    await shop._release_payment_side_effect_lock(key, token)
    again, again_token = await shop._acquire_user_fulfillment_lock(5)
    for k, t in ((other, other_token), (again, again_token)):
        await shop._release_payment_side_effect_lock(k, t)
    assert redis.keys == {}
    monkeypatch.setattr(shop, "redis_client", None)
    with pytest.raises(HTTPException) as no_redis:
        await shop._acquire_user_fulfillment_lock(7)
    assert (no_redis.value.status_code, no_redis.value.detail) == (409, "Redis is required for distributed locking")


class Gateway:
    """A payment provider whose create() times out after reading what the shop stored first."""
    calls: list = []
    seen: list = []
    bind = None

    async def create(self, amount, order_id, description, return_url):
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession
        async with AsyncSession(Gateway.bind) as other:
            row = await other.scalar(select(Payment).where(Payment.order_id == order_id))
        Gateway.seen.append((type(self).__name__, row.status if row else None, row.provider_payment_id if row else "missing"))
        Gateway.calls.append(type(self).__name__)
        raise TimeoutError("provider did not answer")


class FirstGateway(Gateway):
    pass


class SecondGateway(Gateway):
    pass


async def _checkout_env(database, monkeypatch, order):
    async def yes(*args, **kwargs):
        return True

    async def providers(db, requested):
        return list(order)

    async def risk(*args):
        return 0, "allow", {}
    monkeypatch.setattr(shop, "_risk_score", risk)
    monkeypatch.setattr(shop, "production_payments_allowed", yes)
    monkeypatch.setattr(shop, "e2e_checkout_allowed", yes)
    monkeypatch.setattr(shop, "_payment_provider_order", providers)
    monkeypatch.setattr(shop, "redis_client", FakeRedis())
    monkeypatch.setattr(shop, "YooKassaProvider", FirstGateway)
    monkeypatch.setattr(shop, "PlategaProvider", SecondGateway)
    Gateway.calls, Gateway.seen, Gateway.bind = [], [], database.bind


@pytest.mark.asyncio
async def test_checkout_stores_the_intent_first_and_never_falls_back_after_a_timeout(database, monkeypatch):
    """Was: block.index('db.add(payment_row)') < block.index('result=await candidate_provider.create'),
    'payment_row.status="creation_unknown"', 'fallback_blocked' and the «не определён» message in MAIN."""
    from sqlalchemy import select
    await _checkout_env(database, monkeypatch, ["yookassa", "platega"])
    with pytest.raises(HTTPException) as unknown:
        await shop.create_payment({"plan_id": 1, "provider": "yookassa"}, checkout([(b"idempotency-key", b"buy-timeout")]), database)
    assert unknown.value.status_code == 503 and "не определён" in unknown.value.detail
    assert Gateway.seen == [("FirstGateway", "creating", None)], "the intent is committed before the provider is called"
    assert Gateway.calls == ["FirstGateway"], "no second provider after an ambiguous creation"
    row = await database.scalar(select(Payment).where(Payment.idempotency_key == "buy-timeout").execution_options(populate_existing=True))
    assert (row.status, row.fulfillment_terminal) == ("creation_unknown", True)


@pytest.mark.asyncio
async def test_an_uncertain_non_yookassa_payment_is_not_charged_again(database, monkeypatch):
    """Was: 'if existing.provider != "yookassa":' and 'Повторное списание заблокировано' in MAIN."""
    await _checkout_env(database, monkeypatch, ["platega"])
    with pytest.raises(HTTPException):
        await shop.create_payment({"plan_id": 1, "provider": "platega"}, checkout([(b"idempotency-key", b"buy-twice")]), database)
    assert Gateway.calls == ["SecondGateway"]
    with pytest.raises(HTTPException) as blocked:
        await shop.create_payment({"plan_id": 1, "provider": "platega"}, checkout([(b"idempotency-key", b"buy-twice")]), database)
    assert blocked.value.status_code == 409 and "повторное списание заблокировано" in blocked.value.detail
    assert Gateway.calls == ["SecondGateway"], "the retry never reaches the provider"
