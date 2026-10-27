"""v44.5.8–v44.5.10 financial integrity, checked by running the code (was: code lines searched in main.py,
worker.py and models.py). Provisioning retries reuse the persisted target: test_integration_billing_vpn.py
(«premium extension whose answer was lost is not applied twice»)."""
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.responses import Response

from app import admin_auth_api
from app import main as shop
from app.models import AdminUser, Payment, Plan, RefundRequest, Subscription
from app.security import encrypt_secret, hash_password, set_recovery_codes
from app_contract import ROOT, revision, tables
from test_behaviour_auth import db, limiter, request  # noqa: F401
from test_subscription_commerce import database  # noqa: F401
from test_v44_5_9_deep_regressions import device_request


@pytest.mark.asyncio
async def test_a_recovery_code_signs_in_once(db, limiter):  # noqa: F811
    admin = AdminUser(email="owner@corgi.test", password_hash=hash_password("correct horse"), role="owner",
                      totp_secret_encrypted=encrypt_secret("JBSWY3DPEHPK3PXP"), mfa_enabled=True)
    set_recovery_codes(admin, ["AB12CD34EF"])
    db.add(admin)
    await db.commit()
    login = lambda otp: admin_auth_api.admin_login(shop.LoginIn(email="owner@corgi.test", password="correct horse", otp=otp),  # noqa: E731
                                                   request("/api/admin/auth/login"), Response(), db)
    assert (await login("ab12cd34ef"))["email"] == "owner@corgi.test", "codes are case-insensitive"
    with pytest.raises(HTTPException) as reused:
        await login("AB12CD34EF")
    assert reused.value.detail == "MFA code required or invalid", "a used recovery code is gone"


@pytest.mark.asyncio
async def test_the_device_limit_comes_from_the_subscription_snapshot(database):
    (await database.get(Plan, 1)).device_limit = 1  # the plan was cut after the purchase
    await database.commit()
    assert (await database.get(Subscription, 1)).device_limit_snapshot == 2
    register = lambda key: shop.register_device(shop.DeviceRegisterIn(device_key=key * 16, subscription_id=1), device_request(), database)  # noqa: E731
    await register("a")
    assert (await register("b"))["status"] == "active", "the customer keeps the two devices that were sold"


@pytest.mark.asyncio
async def test_a_refund_in_review_can_be_retried_but_not_a_finished_one(database, monkeypatch):
    if database.bind.dialect.name != "postgresql":
        pytest.skip("the refund claim uses SELECT … FOR UPDATE")
    database.add(Payment(id=70, user_id=1, subscription_id=1, plan_id=1, provider="yookassa", order_id="o-70", provider_payment_id="yk-70",
                         amount=Decimal("100"), currency="RUB", status="paid", fulfillment_status="completed", idempotency_key="k-70"))
    database.add(RefundRequest(id=9, payment_id=70, user_id=1, amount=Decimal("100"), status="refunded"))
    await database.commit()
    admin = SimpleNamespace(email="a@b.c")
    with pytest.raises(HTTPException) as done:
        await shop.execute_refund(9, database, admin)
    assert done.value.status_code == 400
    calls = []

    async def refund(self, *a):
        calls.append(a)
        raise RuntimeError("provider down")
    monkeypatch.setattr(shop.YooKassaProvider, "refund", refund)
    monkeypatch.setattr(shop, "engine", database.bind)
    (await database.get(RefundRequest, 9)).status = "review"
    await database.commit()
    with pytest.raises(Exception):
        await shop.execute_refund(9, database, admin)
    assert len(calls) == 1, "a refund waiting for review is sent to the provider again"


def test_schema_of_the_financial_integrity_release():
    rev = revision("0027_v44_5_10_financial_integrity")
    assert rev.down_revision == "0026_v44_5_9_retry_hardening"
    unique = {tuple(c.name for c in con.columns) for con in tables()["payment_provider_events"].constraints if con.__class__.__name__ == "UniqueConstraint"}
    assert ("provider", "event_id") in unique, "a provider event is claimed once per provider"
    assert tables()["payments"].c.provider_payment_id.nullable, "the intent is stored before the provider assigns an id"
    assert tables()["subscriptions"].c.device_limit_snapshot.nullable


def test_release_artifact_and_migration_head_are_current():
    build = (ROOT / 'scripts/build-release.sh').read_text()
    assert '0030_v44_5_16_privacy_and_refund_integrity' in build
