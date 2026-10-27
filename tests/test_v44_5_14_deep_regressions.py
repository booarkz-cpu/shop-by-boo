"""v44.5.12–v44.5.15 logic integrity, checked by running the code (was: code lines searched in main.py and
remnawave.py). Re-enabling and re-applying terms to an existing panel user: test_v45_5_deep_regressions.py."""
import io
import os
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text

from app import main as shop
from app.models import Payment, Plan, Subscription
from app.remnawave import RemnawaveClient
from test_behaviour_payments_v2 import checkout
from test_integration_billing_vpn import app_request, customer, panel  # noqa: F401
from test_subscription_commerce import database  # noqa: F401
from test_v44_5_7_deep_regressions import checkout_env

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.asyncio
async def test_no_trial_while_a_subscription_runs_including_one_without_an_end(customer, panel):  # noqa: F811
    db = customer
    (await db.get(shop.User, 2)).telegram_id = 222
    db.add(Subscription(id=5, user_id=2, plan_id=1, expires_at=None, lifecycle_status="active", is_primary=True))
    await db.commit()
    with pytest.raises(HTTPException) as running:
        await shop.claim_trial(shop.TrialIn(plan_id=1, days=3), app_request(), db)
    assert running.value.status_code in (400, 409)
    sub = await db.get(Subscription, 5)
    sub.expires_at = datetime.utcnow() + timedelta(days=5)
    await db.commit()
    with pytest.raises(HTTPException) as active:
        await shop.claim_trial(shop.TrialIn(plan_id=1, days=3), app_request(), db)
    assert active.value.detail == "Пробный период недоступен при действующей подписке"


@pytest.mark.asyncio
async def test_new_terms_clear_old_limits_and_squads_on_the_panel(panel):  # noqa: F811
    uid = str(uuid.uuid4())
    panel.users[uid] = {"uuid": uid, "id": uid, "username": "u", "trafficLimitBytes": 5 * 1024 ** 3, "activeInternalSquads": ["old-squad"],
                        "expireAt": datetime.utcnow().isoformat(), "status": "ACTIVE"}
    await RemnawaveClient().update_entitlements(uid, None, None)
    assert panel.users[uid]["trafficLimitBytes"] == 0 and panel.users[uid]["activeInternalSquads"] == [], "unlimited and no stale squad"


@pytest.mark.asyncio
async def test_a_webhook_binds_a_lost_creation_by_order_id(database):
    database.add(Payment(user_id=1, subscription_id=1, plan_id=1, provider="yookassa", order_id="o-bind", amount=Decimal("100"),
                         currency="RUB", status="creation_unknown", fulfillment_terminal=True, idempotency_key="k-bind"))
    await database.commit()
    found = await shop.payment_by_provider_or_order(database, "yookassa", "yk-late", "o-bind")
    assert found is not None and found.order_id == "o-bind"
    await shop.bind_provider_payment_id(database, found, "yk-late")
    assert (found.provider_payment_id, found.status, found.fulfillment_terminal) == ("yk-late", "pending", False)
    with pytest.raises(HTTPException) as mismatch:
        await shop.bind_provider_payment_id(database, found, "yk-someone-else")
    assert mismatch.value.status_code == 409
    assert await shop.payment_by_provider_or_order(database, "platega", "yk-late", "o-bind") is None, "never across providers"


@pytest.mark.asyncio
async def test_database_check_constraints_of_the_integrity_release():
    url = os.environ.get("AUDIT_TEST_DATABASE_URL")
    if not url:
        pytest.skip("checked on the migrated PostgreSQL in CI")
    from sqlalchemy.ext.asyncio import create_async_engine
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            names = set((await conn.execute(text("SELECT conname FROM pg_constraint WHERE contype = 'c'"))).scalars())
    finally:
        await engine.dispose()
    assert {'ck_trial_grants_days_valid', 'ck_promo_codes_reserved_nonnegative', 'ck_promo_codes_used_nonnegative',
            'ck_payments_amount_positive', 'ck_payments_discount_nonnegative'} <= names


def test_release_points_to_44_5_15_and_latest_migration():
    assert "0030_v44_5_16_privacy_and_refund_integrity" in (ROOT / "scripts/build-release.sh").read_text()


@pytest.mark.asyncio
async def test_a_retry_is_answered_from_the_intent_even_if_the_plan_was_switched_off(database, monkeypatch):
    await checkout_env(database, monkeypatch)
    key = [(b"idempotency-key", b"plan-off")]
    first = await shop.create_payment({"plan_id": 1, "provider": "yookassa"}, checkout(key), database)
    (await database.get(Plan, 1)).enabled = False
    await database.commit()
    again = await shop.create_payment({"plan_id": 1, "provider": "yookassa"}, checkout(key), database)
    assert again["id"] == first["id"]
    with pytest.raises(HTTPException):
        await shop.create_payment({"plan_id": 1, "provider": "yookassa"}, checkout([(b"idempotency-key", b"plan-off-new")]), database)


@pytest.mark.asyncio
async def test_a_provider_answer_without_a_payment_id_is_not_a_checkout(database, monkeypatch):
    await checkout_env(database, monkeypatch)

    class NoId:
        async def create(self, *a, **k):
            return {"url": "https://pay"}
    monkeypatch.setattr(shop, "YooKassaProvider", NoId)
    with pytest.raises(HTTPException) as broken:
        await shop.create_payment({"plan_id": 1, "provider": "yookassa"}, checkout([(b"idempotency-key", b"no-id")]), database)
    assert broken.value.status_code >= 400
    row = await database.scalar(select(Payment).where(Payment.idempotency_key == "no-id"))
    assert row is None or row.provider_payment_id is None and row.status != "pending"


def _pin(name):
    """Exact pinned version of a backend requirement as a tuple of ints (Dependabot moves pins forward)."""
    import re
    for line in (ROOT / "backend/requirements.txt").read_text().splitlines():
        m = re.match(rf"^{re.escape(name)}(\[[^\]]*\])?==([0-9][0-9.]*)\s*$", line.strip(), re.I)
        if m:
            return tuple(int(x) for x in m.group(2).split("."))
    raise AssertionError(f"{name} is not pinned exactly")


def test_cryptography_is_pinned_to_a_security_fixed_release():
    assert _pin("cryptography") >= (50, 0, 1)


@pytest.mark.asyncio
async def test_uploads_are_read_with_a_hard_limit():
    from starlette.datastructures import Headers, UploadFile
    big = UploadFile(file=io.BytesIO(b"x" * (2 * 1024 * 1024 + 1)), filename="bg.png", headers=Headers({"content-type": "image/png"}))
    with pytest.raises(HTTPException) as too_big:
        await shop._read_upload_limited(big, 2 * 1024 * 1024)
    assert too_big.value.status_code == 413
    ok = UploadFile(file=io.BytesIO(b"x" * 1024), filename="bg.png", headers=Headers({"content-type": "image/png"}))
    assert len(await shop._read_upload_limited(ok, 2 * 1024 * 1024)) == 1024
