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


@pytest.mark.asyncio
async def test_the_same_checkout_key_for_another_plan_is_refused(database, monkeypatch):
    """Was: 'lock:checkout-intent:' and 'if existing.plan_id != plan_id' in MAIN (test_v301_audit.py)."""
    await _checkout_env(database, monkeypatch, ["platega"])
    with pytest.raises(HTTPException):
        await shop.create_payment({"plan_id": 1, "provider": "platega"}, checkout([(b"idempotency-key", b"buy-plan")]), database)
    with pytest.raises(HTTPException) as other:
        await shop.create_payment({"plan_id": 2, "provider": "platega"}, checkout([(b"idempotency-key", b"buy-plan")]), database)
    assert (other.value.status_code, other.value.detail) == (409, "Idempotency-Key уже использован для другого платежа")
    assert Gateway.calls == ["SecondGateway"], "the other plan never reaches the provider"


@pytest.mark.asyncio
async def test_reconciliation_recovers_a_lost_yookassa_answer_by_the_order_id(database, monkeypatch):
    """Was: main.count('find_by_order_id(p.order_id, p.created_at)') and no provider.create in MAIN (test_critical_audit_v2005.py)."""
    from sqlalchemy import select
    from app import recovery_api
    seen = []

    class Lookup:
        async def find_by_order_id(self, order_id, created_at):
            seen.append(("find", order_id))
            return {"id": "yk-found", "confirmation": {"confirmation_url": "https://pay.example.test/yk-found"}}

        async def create(self, *args, **kwargs):
            seen.append(("create",))
            raise AssertionError("reconciliation must not open a second charge")

        async def verify_succeeded(self, *args):
            seen.append(("verify",) + args[:1])
            return False

    class Idle:
        pass

    async def noop(*args, **kwargs):
        return None
    for name in ("PlategaProvider", "RollyPayProvider", "CryptoBotProvider", "FreekassaProvider", "StripePlatform", "PayPalPlatform",
                 "CryptoGatewayPlatform"):
        monkeypatch.setattr(shop, name, Idle)
    monkeypatch.setattr(shop, "YooKassaProvider", Lookup)
    monkeypatch.setattr(recovery_api, "extra_gateways", lambda: {})
    monkeypatch.setattr(shop, "audit", noop)
    database.add(Payment(user_id=1, subscription_id=1, plan_id=1, provider="yookassa", order_id="lost-order", amount=100, currency="RUB",
                         status="creation_unknown", fulfillment_terminal=True))
    await database.commit()
    out = await recovery_api.reconcile_payments(database, admin=type("A", (), {"email": "owner@example.test"})())
    assert out["creation_unknown_recovered"] == 1
    assert seen == [("find", "lost-order"), ("verify", "yk-found")]
    row = await database.scalar(select(Payment).where(Payment.order_id == "lost-order").execution_options(populate_existing=True))
    assert (row.provider_payment_id, row.status, row.fulfillment_terminal) == ("yk-found", "pending", False)
    assert row.checkout_url == "https://pay.example.test/yk-found"


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["subscription", "retry", "topup"])
@pytest.mark.parametrize("reply", ["accepted", "timeout"])
async def test_checkout_preserves_a_payment_settled_before_creation_returns(database, monkeypatch, entry, reply):
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession

    await _checkout_env(database, monkeypatch, ["yookassa"])
    from app import payments_api
    monkeypatch.setattr(shop, "_release_payment_side_effect_lock", payments_api._release_payment_side_effect_lock)
    key = f"early-paid-{entry}-{reply}"
    request = checkout([(b"idempotency-key", key.encode())])
    payload = {"amount": "100", "provider": "yookassa"} if entry == "topup" else {"plan_id": 1, "provider": "yookassa"}
    create = shop.wallet_topup if entry == "topup" else shop.create_payment
    if entry == "retry":
        with pytest.raises(HTTPException) as first:
            await create(payload, request, database)
        assert first.value.status_code == 503
    calls = []

    class EarlyCallback:
        async def create(self, amount, order_id, description, return_url):
            async with AsyncSession(database.bind) as callback:
                payment = await callback.scalar(select(Payment).where(Payment.order_id == order_id))
                await shop.bind_provider_payment_id(callback, payment, "verified-payment")
                payment.status = "paid"
                payment.fulfillment_status = "completed"
                payment.fulfillment_terminal = True
                await callback.commit()
            calls.append(order_id)
            if reply == "timeout":
                raise TimeoutError("create response was lost")
            return {"id": "verified-payment", "url": "https://checkout.example/used", "status": "pending"}

    monkeypatch.setattr(shop, "YooKassaProvider", EarlyCallback)
    out = await create(payload, request, database)
    assert out["status"] == "paid" and out["id"] == "verified-payment"
    assert out.get("url") is None
    stored = await database.scalar(select(Payment).where(Payment.idempotency_key == key).execution_options(populate_existing=True))
    assert (stored.status, stored.fulfillment_status, stored.fulfillment_terminal) == ("paid", "completed", True)
    assert (await create(payload, request, database))["status"] == "paid"
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(("status", "same_id", "save_url", "save_method"), [
    ("pending", True, True, True), ("pending", False, False, False),
    ("paid", True, False, True), ("refunded", True, False, False),
])
async def test_late_checkout_metadata_stays_bound_to_the_verified_payment(
        database, monkeypatch, status, same_id, save_url, save_method):
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.models import AuditLog, AutoRenewMethod

    await _checkout_env(database, monkeypatch, ["yookassa"])
    monkeypatch.setattr(shop, "encrypt_secret", lambda _: "test-encrypted")
    class GatewayWithMetadata:
        async def create(self, amount, order_id, description, return_url):
            async with AsyncSession(database.bind) as callback:
                payment = await callback.scalar(select(Payment).where(Payment.order_id == order_id))
                await shop.bind_provider_payment_id(callback, payment, "verified")
                payment.status = status
                await callback.commit()
            return {"id": "verified" if same_id else "different", "url": "https://checkout.example/page",
                    "status": "succeeded", "recurring_token": "test-token"}

    monkeypatch.setattr(shop, "YooKassaProvider", GatewayWithMetadata)
    result = await shop.create_payment({"plan_id": 1}, checkout([(b"idempotency-key", b"metadata")]), database)
    assert (result["id"], result["status"]) == ("verified", status)
    assert (result["url"] == "https://checkout.example/page") is save_url
    method = await database.scalar(select(AutoRenewMethod).where(AutoRenewMethod.user_id == 1))
    assert (method is not None) is save_method
    if save_method:
        assert method.external_token_encrypted == "test-encrypted"
    conflict = await database.scalar(select(AuditLog).where(AuditLog.action == "payment.creation.identifier_mismatch"))
    assert (conflict is None) is same_id


@pytest.mark.asyncio
async def test_verified_wallet_webhook_credits_once_if_create_times_out(database, monkeypatch):
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.models import FinancialLedger, PaymentProviderEvent, User

    if database.bind.dialect.name != "postgresql":
        pytest.skip("the production event journal uses PostgreSQL")
    await _checkout_env(database, monkeypatch, ["yookassa"])
    monkeypatch.setattr(shop, "engine", database.bind)
    monkeypatch.setattr(shop.settings, "yookassa_webhook_ip_allowlist", "10.1.2.3/32")
    notifications = []
    class EarlyWalletPayment:
        async def verify_succeeded(self, payment_id, amount, currency, order_id):
            return (payment_id, amount, currency, order_id) == ("wallet-verified", Decimal("100"), "RUB", notifications[0]["object"]["metadata"]["order_id"])

        async def create(self, amount, order_id, description, return_url):
            event = {"id": "wallet-success", "event": "payment.succeeded",
                     "object": {"id": "wallet-verified", "metadata": {"order_id": order_id}}}
            notifications.append(event)
            async with AsyncSession(database.bind, expire_on_commit=False) as callback:
                assert (await shop.yookassa_webhook(webhook(event), callback))["ok"]
            raise TimeoutError("create response was lost")

    monkeypatch.setattr(shop, "YooKassaProvider", EarlyWalletPayment)
    request = checkout([(b"idempotency-key", b"wallet-callback")])
    payload = {"amount": "100", "provider": "yookassa"}
    assert (await shop.wallet_topup(payload, request, database))["status"] == "paid"
    async with AsyncSession(database.bind, expire_on_commit=False) as callback:
        assert (await shop.yookassa_webhook(webhook(notifications[0]), callback))["duplicate"]
    assert (await shop.wallet_topup(payload, request, database))["status"] == "paid"
    user = await database.get(User, 1, populate_existing=True)
    assert user.wallet_balance == Decimal("1100") and len(notifications) == 1
    entries = (await database.scalars(select(FinancialLedger.kind).order_by(FinancialLedger.id))).all()
    assert entries == ["payment", "wallet_topup"]
    event = await database.scalar(select(PaymentProviderEvent))
    assert (event.status, event.attempts) == ("processed", 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("found", ["matching", "missing", "other-currency"])
async def test_retry_of_an_old_yookassa_intent_only_reads_existing_payments(database, monkeypatch, found):
    from datetime import datetime, timedelta
    from sqlalchemy import select
    from app import payments_api

    await _checkout_env(database, monkeypatch, ["yookassa"])
    monkeypatch.setattr(shop, "_release_payment_side_effect_lock", payments_api._release_payment_side_effect_lock)
    key = "old-checkout"
    request = checkout([(b"idempotency-key", key.encode())])
    payload = {"plan_id": 1, "provider": "yookassa"}
    with pytest.raises(HTTPException):
        await shop.create_payment(payload, request, database)
    row = await database.scalar(select(Payment).where(Payment.idempotency_key == key))
    row.created_at = datetime.utcnow() - timedelta(days=2)
    await database.commit()
    looked_up, creates = [], []
    class RecoveryGateway:
        async def find_by_order_id(self, order_id, created_at):
            looked_up.append(order_id)
            if found == "missing":
                return None
            return {"id": "already-created", "metadata": {"order_id": order_id},
                    "status": "pending", "amount": {"value": "100.00", "currency": "USD" if found == "other-currency" else "RUB"}}

        async def create(self, *args):
            creates.append(args)
            return {"id": "new-checkout", "status": "pending"}

    monkeypatch.setattr(shop, "YooKassaProvider", RecoveryGateway)
    if found == "matching":
        out = await shop.create_payment(payload, request, database)
        assert (out["id"], out["status"]) == ("already-created", "pending")
    else:
        with pytest.raises(HTTPException) as err:
            await shop.create_payment(payload, request, database)
        assert err.value.status_code == 503
    assert looked_up == [row.order_id] and creates == []
