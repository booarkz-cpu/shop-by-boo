"""Staging E2E v2: signed result, production admission and a full run through the shop's own routes."""
import asyncio
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app import e2e_v2, main
from app.config import settings
from app.models import AdminUser, Base, E2ECase, E2ERun, E2EWebhookCapture, Payment, Plan, RefundRequest, Subscription
from test_subscription_commerce import database

ADMIN = SimpleNamespace(id=1, email="root@example.test", role="admin", disabled=False)
NOW = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
NONCE = "e2e2n.abcdef123456.0123456789abcdef01234567"


def payload(**changes):
    results = [{"provider": "yookassa", "status": "passed", "checks": list(e2e_v2.REQUIRED_CHECKS)}]
    data = {"contract_version": 2, "environment": "staging", "distribution_tag": e2e_v2.DISTRIBUTION_TAG, "nonce": NONCE,
            "run_id": "run-1", "status": "passed", "full_e2e": True, "finished_at": (NOW - timedelta(hours=1)).isoformat(),
            "provider_results": results}
    data.update(changes)
    return data


def check(text_, key, **kwargs):
    args = dict(nonce=NONCE, issued_at=NOW - timedelta(hours=2), now=NOW, providers=["yookassa"])
    args.update(kwargs)
    return e2e_v2.verify_attestation(text_, e2e_v2.public_key_text(key), **args)


def test_signed_attestation_is_accepted():
    key = Ed25519PrivateKey.generate()
    assert check(e2e_v2.sign_attestation(payload(), key), key)["run_id"] == "run-1"


@pytest.mark.parametrize("changes,kwargs,reason", [
    ({"nonce": "e2e2n.abcdef123456.ffffffffffffffffffffffff"}, {}, "Код запуска"),
    ({"distribution_tag": "v1.0.0"}, {}, "Стенд работает"),
    ({"environment": "production"}, {}, "не на стенде"),
    ({"contract_version": 1}, {}, "версия контракта"),
    ({"status": "failed", "full_e2e": False}, {}, "не пройдена"),
    ({"finished_at": (NOW - timedelta(hours=25)).isoformat()}, {"issued_at": NOW - timedelta(hours=30)}, "24 часов"),
    ({"finished_at": (NOW + timedelta(hours=1)).isoformat()}, {}, "будущем"),
    ({"finished_at": (NOW - timedelta(hours=3)).isoformat()}, {}, "раньше, чем выдан"),
    ({"provider_results": [{"provider": "yookassa", "status": "passed", "checks": list(e2e_v2.REQUIRED_CHECKS[:-1])}]}, {}, "Не все"),
    ({}, {"providers": ["yookassa", "platega"]}, "Не все"),
])
def test_attestation_rejections(changes, kwargs, reason):
    key = Ed25519PrivateKey.generate()
    with pytest.raises(e2e_v2.AttestationError, match=reason):
        check(e2e_v2.sign_attestation(payload(**changes), key), key, **kwargs)


def test_foreign_key_or_tampered_payload_is_rejected():
    key, other = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    signed = e2e_v2.sign_attestation(payload(), other)
    with pytest.raises(e2e_v2.AttestationError, match="Подпись"):
        check(signed, key)
    head, body, sig = e2e_v2.sign_attestation(payload(status="failed", full_e2e=False), key).split(".")
    forged = ".".join([head, e2e_v2._b64e(e2e_v2.canonical(payload())), sig])
    with pytest.raises(e2e_v2.AttestationError, match="Подпись"):
        check(forged, key)


@pytest.mark.asyncio
async def test_optional_admission_records_the_result_and_never_closes_payments(database, monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    key = Ed25519PrivateKey.generate()
    assert await main.production_payments_allowed(database) is True  # open from the first start
    await e2e_v2.save_admission_config(e2e_v2.AdmissionConfigIn(public_key=e2e_v2.public_key_text(key), providers=["yookassa"]), database, ADMIN)
    nonce = (await e2e_v2.issue_nonce(database, ADMIN))["nonce"]
    assert e2e_v2.NONCE_RE.match(nonce)
    assert await main.production_payments_allowed(database) is True  # the optional check does not close payments
    good = payload(nonce=nonce, finished_at=datetime.now(timezone.utc).isoformat())
    with pytest.raises(HTTPException) as wrong:
        await e2e_v2.accept_attestation(e2e_v2.AttestationIn(attestation=e2e_v2.sign_attestation(payload(), key)), database, ADMIN)
    assert wrong.value.status_code == 409 and "Код запуска" in wrong.value.detail
    accepted = await e2e_v2.accept_attestation(e2e_v2.AttestationIn(attestation=e2e_v2.sign_attestation(good, key)), database, ADMIN)
    assert accepted["contract_version"] == 2 and accepted["full_e2e"] is True
    # The same attestation cannot be accepted twice: the nonce is spent.
    with pytest.raises(HTTPException):
        await e2e_v2.accept_attestation(e2e_v2.AttestationIn(attestation=e2e_v2.sign_attestation(good, key)), database, ADMIN)
    # The emergency switch closes and reopens real payments.
    assert await main.production_payment_gate(main.ProductionGateIn(enabled=False), database, ADMIN) == {"enabled": False}
    assert await main.production_payments_allowed(database) is False
    assert await main.production_payment_gate(main.ProductionGateIn(enabled=True), database, ADMIN) == {"enabled": True}
    assert await main.production_payments_allowed(database) is True


@pytest.mark.asyncio
async def test_staging_refuses_admission_and_production_refuses_runs(database, monkeypatch):
    monkeypatch.setattr(settings, "app_env", "staging")
    with pytest.raises(HTTPException) as exc:
        await e2e_v2.issue_nonce(database, ADMIN)
    assert exc.value.status_code == 409
    monkeypatch.setattr(settings, "app_env", "production")
    with pytest.raises(HTTPException) as exc:
        await e2e_v2.start_run(e2e_v2.RunIn(nonce=NONCE, plan_id=1, providers=["yookassa"]), database, ADMIN)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_only_one_active_run(database, monkeypatch):
    monkeypatch.setattr(settings, "app_env", "staging")
    for i in range(2):
        database.add(E2ERun(id=f"r{i}", nonce=NONCE, status="queued", active=False, providers=["yookassa"], plan_id=1,
                            admin_id=1, admin_email="a", distribution_tag="t", created_at=datetime.utcnow()))
    await database.commit()
    first = await database.get(E2ERun, "r0")
    first.active = True
    await database.commit()
    second = await database.get(E2ERun, "r1")
    second.active = True
    with pytest.raises(Exception):
        await database.commit()
    await database.rollback()


# ---------------------------------------------------------------------------
# A full run against the real routes: PostgreSQL and Redis are required.
# ---------------------------------------------------------------------------

class FakeYooKassa:
    state = {"paid": False, "payment_id": None, "refunds": 0}

    async def create(self, amount, order_id, description, return_url):
        pid = "yk-" + uuid.uuid4().hex[:12]
        FakeYooKassa.state["payment_id"] = pid
        return {"id": pid, "url": f"https://sandbox.yookassa.test/pay/{pid}", "status": "pending"}

    async def verify_succeeded(self, payment_id, expected_amount, currency, expected_order_id=None):
        return FakeYooKassa.state["paid"] and payment_id == FakeYooKassa.state["payment_id"]

    async def refund(self, payment_id, amount, currency, reason=""):
        FakeYooKassa.state["refunds"] += 1
        return {"id": f"rf-{FakeYooKassa.state['refunds']}", "status": "succeeded"}

    async def get_refund_status(self, refund_id):
        return "succeeded"


class FakeRemnawave:
    users: dict = {}

    async def get_user(self, user_id):
        return FakeRemnawave.users.get(str(user_id))

    async def get_user_by_username(self, username):
        return next((u for u in FakeRemnawave.users.values() if u["username"] == username), None)

    async def create_user(self, username, expires, traffic, active_internal_squads=None, telegram_id=None, device_limit=None):
        uid = str(uuid.uuid4())
        FakeRemnawave.users[uid] = {"id": uid, "uuid": uid, "username": username, "status": "ACTIVE", "expire": expires,
                                    "subscriptionUrl": f"https://sub.test/{uid}"}
        return FakeRemnawave.users[uid]

    async def get_expiry(self, user_id):
        return FakeRemnawave.users[str(user_id)]["expire"]

    async def disable_user(self, user_id):
        FakeRemnawave.users[str(user_id)]["status"] = "DISABLED"

    async def enable_user(self, user_id):
        FakeRemnawave.users[str(user_id)]["status"] = "ACTIVE"

    async def update_entitlements(self, *args, **kwargs):
        return None

    async def extend_idempotent(self, user_id, days, before, after):
        FakeRemnawave.users[str(user_id)]["expire"] = after

    async def get_subscription(self, user_id):
        return {"subscriptionUrl": FakeRemnawave.users[str(user_id)]["subscriptionUrl"]}


@pytest_asyncio.fixture
async def shop(monkeypatch):
    url, redis_url = os.environ.get("AUDIT_TEST_DATABASE_URL"), os.environ.get("REDIS_URL")
    if not url or not redis_url:
        pytest.skip("A full E2E v2 run needs PostgreSQL and Redis (CI)")
    from redis.asyncio import Redis
    redis = Redis.from_url(redis_url, decode_responses=True)
    try:
        await redis.ping()
    except Exception:
        pytest.skip("Redis is not reachable")
    schema = "e2e_v2_" + uuid.uuid4().hex
    root = create_async_engine(url)
    async with root.begin() as conn:
        await conn.execute(text(f"CREATE SCHEMA {schema}"))
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as db:
        db.add(Plan(id=1, name="E2E", price=100, duration_days=30, enabled=True, remnawave_profile_id="squad-1"))
        db.add(AdminUser(id=1, email="root@example.test", password_hash="x", role="admin"))
        await db.commit()
        await db.execute(text("SELECT setval(pg_get_serial_sequence('plans','id'), 1, true)"))
        await db.execute(text("SELECT setval(pg_get_serial_sequence('admin_users','id'), 1, true)"))
        await db.commit()

    async def get_db_override():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session
    main.app.dependency_overrides[main.get_db] = get_db_override
    monkeypatch.setattr(main, "engine", engine)
    monkeypatch.setattr(main, "redis_client", redis)
    monkeypatch.setattr(main, "YooKassaProvider", FakeYooKassa)
    monkeypatch.setattr(main, "RemnawaveClient", FakeRemnawave)
    monkeypatch.setattr(settings, "app_env", "staging")
    monkeypatch.setattr(settings, "yookassa_shop_id", "sandbox-shop")
    monkeypatch.setattr(settings, "yookassa_secret_key", "sandbox-secret")
    monkeypatch.setattr(settings, "yookassa_webhook_ip_allowlist", "203.0.113.0/24")
    monkeypatch.setattr(e2e_v2.Runner, "payment_poll", 0.05)
    monkeypatch.setattr(e2e_v2.Runner, "refund_poll", 0.05)
    monkeypatch.setattr(e2e_v2.Runner, "webhook_grace", 1.0)
    FakeYooKassa.state = {"paid": False, "payment_id": None, "refunds": 0}
    FakeRemnawave.users = {}
    yield engine
    main.app.dependency_overrides.pop(main.get_db, None)
    await redis.aclose()
    await engine.dispose()
    async with root.begin() as conn:
        await conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
    await root.dispose()


async def _wait_stage(engine, run_id, stage):
    for _ in range(400):
        async with AsyncSession(engine, expire_on_commit=False) as db:
            case = (await db.execute(select(E2ECase).where(E2ECase.run_id == run_id))).scalar_one()
            if case.stage == stage:
                return case
            if case.status == "failed":
                raise AssertionError(case.error)
        await asyncio.sleep(0.05)
    raise AssertionError(f"stage {stage} not reached")


async def _start(engine):
    async with AsyncSession(engine, expire_on_commit=False) as db:
        admin = await db.get(AdminUser, 1)
        started = await e2e_v2.start_run(e2e_v2.RunIn(nonce=NONCE, plan_id=1, providers=["yookassa"], payment_timeout_seconds=300), db, admin)
    return started["id"]


async def _deliver_webhook(order_id):
    FakeYooKassa.state["paid"] = True
    body = {"type": "notification", "event": "payment.succeeded",
            "object": {"id": FakeYooKassa.state["payment_id"], "status": "succeeded", "metadata": {"order_id": order_id}}}
    transport = httpx.ASGITransport(app=main.app, client=("203.0.113.10", 44300))
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
        response = await client.post("/api/webhooks/yookassa", json=body)
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_full_run_passes_through_real_routes_and_signs_the_result(shop):
    issued = datetime.now(timezone.utc)
    run_id = await _start(shop)
    case = await _wait_stage(shop, run_id, "awaiting_payment")
    assert case.checks == ["checkout", "idempotent_checkout"]
    await _deliver_webhook(case.order_id)
    await asyncio.wait_for(e2e_v2._TASKS[run_id], 60)
    async with AsyncSession(shop, expire_on_commit=False) as db:
        run = await db.get(E2ERun, run_id)
        case = (await db.execute(select(E2ECase).where(E2ECase.run_id == run_id))).scalar_one()
        assert case.error is None and case.status == "passed", case.error
        assert case.checks == list(e2e_v2.REQUIRED_CHECKS)
        assert run.status == "passed" and run.active is None
        payment = await db.get(Payment, case.payment_id)
        assert payment.status == "refunded"
        refunds = (await db.execute(select(RefundRequest).where(RefundRequest.payment_id == payment.id))).scalars().all()
        assert len(refunds) == 1 and FakeYooKassa.state["refunds"] == 1
        sub = await db.get(Subscription, payment.subscription_id)
        assert FakeRemnawave.users[sub.remnawave_uuid]["status"] == "DISABLED"
        capture = (await db.execute(select(E2EWebhookCapture))).scalar_one()
        assert capture.data_encrypted is None  # erased when the run ended
        key = await e2e_v2.signing_key(db)
    attested = e2e_v2.verify_attestation(run.attestation, e2e_v2.public_key_text(key), nonce=NONCE, issued_at=issued,
                                         now=datetime.now(timezone.utc), providers=["yookassa"])
    assert attested["provider_results"][0]["payment_id"] == case.payment_id


@pytest.mark.asyncio
async def test_payment_marked_paid_without_a_webhook_fails_the_run(shop):
    run_id = await _start(shop)
    case = await _wait_stage(shop, run_id, "awaiting_payment")
    async with AsyncSession(shop, expire_on_commit=False) as db:
        payment = await db.get(Payment, case.payment_id)
        payment.status = "paid"  # a poll or a manual edit is not a signed webhook
        await db.commit()
    await asyncio.wait_for(e2e_v2._TASKS[run_id], 60)
    async with AsyncSession(shop, expire_on_commit=False) as db:
        run = await db.get(E2ERun, run_id)
        case = (await db.execute(select(E2ECase).where(E2ECase.run_id == run_id))).scalar_one()
    assert run.status == "failed" and case.status == "failed"
    assert "webhook" in case.error and "signed_webhook" not in case.checks
    key = Ed25519PrivateKey.generate()
    with pytest.raises(e2e_v2.AttestationError):
        e2e_v2.verify_attestation(run.attestation, e2e_v2.public_key_text(key), nonce=NONCE, issued_at=datetime.now(timezone.utc),
                                  now=datetime.now(timezone.utc), providers=["yookassa"])


@pytest.mark.asyncio
async def test_cancelled_run_stops_and_is_not_passed(shop):
    run_id = await _start(shop)
    await _wait_stage(shop, run_id, "awaiting_payment")
    async with AsyncSession(shop, expire_on_commit=False) as db:
        admin = await db.get(AdminUser, 1)
        await e2e_v2.cancel_run(run_id, db, admin)
    await asyncio.wait_for(e2e_v2._TASKS[run_id], 30)
    async with AsyncSession(shop, expire_on_commit=False) as db:
        run = await db.get(E2ERun, run_id)
    assert run.status == "cancelled" and run.active is None
