"""v28.27.0 money-path review: each test reproduces a confirmed bug and checks the fix."""
import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app import gift_orders, ops_alerts, partners
from app import main as shop
from app.app_config import season_sticker
from app.models import AutoRenewMethod, FinancialLedger, GiftCode, Payment, Subscription, User
from test_subscription_commerce import database  # noqa: F401


def _scheduler_env(monkeypatch, db, charges):
    monkeypatch.setattr(shop, "engine", db.bind)
    monkeypatch.setattr(shop.settings, "auto_renew_enabled", True, raising=False)

    async def allowed(*a): return True

    async def lock(*a, **k): return ("k", "t")

    async def charge(self, amount, order_id, desc, token):
        charges.append((amount, order_id))
        return {"id": "yk-1"}

    async def verified(self, *a, **k): return False

    monkeypatch.setattr(shop, "production_payments_allowed", allowed)
    monkeypatch.setattr(shop, "_acquire_redis_lock", lock)
    monkeypatch.setattr(shop, "decrypt_secret", lambda v: "tok")
    monkeypatch.setattr(shop.YooKassaProvider, "charge_recurring", charge)
    monkeypatch.setattr(shop.YooKassaProvider, "verify_succeeded", verified)


async def _run_scheduler_once(monkeypatch):
    calls = {"n": 0}
    real_sleep = asyncio.sleep

    async def fake_sleep(s):
        calls["n"] += 1
        if calls["n"] > 1:
            raise asyncio.CancelledError()
        await real_sleep(0)
    monkeypatch.setattr(shop.asyncio, "sleep", fake_sleep)
    with pytest.raises(asyncio.CancelledError):
        await shop.auto_renew_scheduler()
    monkeypatch.setattr(shop.asyncio, "sleep", real_sleep)


async def _renewable(db, **sub_fields):
    user = await db.get(User, 1)
    user.auto_renew_enabled = True
    sub = await db.get(Subscription, 1)
    sub.auto_renew_enabled = True
    sub.expires_at = datetime.utcnow() + timedelta(days=1)
    for key, value in sub_fields.items():
        setattr(sub, key, value)
    db.add(AutoRenewMethod(user_id=1, provider="yookassa", external_token_encrypted="x", enabled=True, status="active"))
    await db.commit()


@pytest.mark.asyncio
async def test_auto_renew_never_charges_a_cancelled_subscription(database, monkeypatch):
    charges = []
    _scheduler_env(monkeypatch, database, charges)
    expires = datetime.utcnow() + timedelta(days=1)
    await _renewable(database, scheduled_cancel_at=expires, lifecycle_status="cancel_scheduled")
    await _run_scheduler_once(monkeypatch)
    assert charges == []


@pytest.mark.asyncio
async def test_auto_renew_still_charges_a_live_subscription(database, monkeypatch):
    charges = []
    _scheduler_env(monkeypatch, database, charges)
    await _renewable(database)
    await _run_scheduler_once(monkeypatch)
    assert charges and charges[0][0] == Decimal("100")


def test_restricted_or_suspended_customers_are_not_chargeable():
    live = SimpleNamespace(restricted_at=None, scheduled_cancel_at=None, lifecycle_status="active")
    user = SimpleNamespace(restricted_at=None)
    assert shop.auto_renew_chargeable(user, live)
    assert shop.auto_renew_chargeable(user, SimpleNamespace(**{**vars(live), "lifecycle_status": "grace"}))
    assert not shop.auto_renew_chargeable(SimpleNamespace(restricted_at=datetime.utcnow()), live)
    assert not shop.auto_renew_chargeable(user, SimpleNamespace(**{**vars(live), "lifecycle_status": "suspended"}))
    assert not shop.auto_renew_chargeable(user, SimpleNamespace(**{**vars(live), "scheduled_cancel_at": datetime.utcnow()}))


@pytest.mark.asyncio
async def test_a_lost_recurring_charge_is_adopted_not_charged_again(monkeypatch):
    charges = []

    async def found(self, order_id, created_after=None): return {"id": "yk-existing"}

    async def charge(self, *a): charges.append(a); return {"id": "yk-new"}
    monkeypatch.setattr(shop.YooKassaProvider, "find_by_order_id", found)
    monkeypatch.setattr(shop.YooKassaProvider, "charge_recurring", charge)
    monkeypatch.setattr(shop, "decrypt_secret", lambda v: "tok")
    method = SimpleNamespace(external_token_encrypted="x")
    plan = SimpleNamespace(name="Basic")
    payment = SimpleNamespace(order_id="auto-renew-1", amount=Decimal("100"), created_at=datetime.utcnow() - timedelta(hours=30),
                              provider_payment_id=None, status="creating", fulfillment_terminal=False, fulfillment_error=None)
    assert await shop.adopt_or_retry_recurring(payment, method, plan) == "adopted"
    assert payment.provider_payment_id == "yk-existing" and payment.status == "pending" and charges == []

    async def nothing(self, order_id, created_after=None): return None
    monkeypatch.setattr(shop.YooKassaProvider, "find_by_order_id", nothing)
    old = SimpleNamespace(**{**vars(payment), "provider_payment_id": None, "status": "creating"})
    assert await shop.adopt_or_retry_recurring(old, method, plan) == "unknown"
    assert old.status == "creation_unknown" and old.fulfillment_terminal and charges == []  # key expired: never re-sent

    fresh = SimpleNamespace(**{**vars(old), "status": "creating", "created_at": datetime.utcnow() - timedelta(minutes=20)})
    assert await shop.adopt_or_retry_recurring(fresh, method, plan) == "retried"
    assert fresh.provider_payment_id == "yk-new" and len(charges) == 1


class FakeRW:
    def __init__(self, status="DISABLED"):
        self.calls = []
        self.expiry = None
        self.status = status

    async def get_user(self, uid): return {"status": self.status, "userTraffic": {"usedTrafficBytes": 0}}

    async def get_expiry(self, uid): return self.expiry

    async def update_entitlements(self, *a, **k): self.calls.append(("update", a))

    async def extend_idempotent(self, uid, days, before, after):
        self.calls.append(("extend", days))
        self.expiry = after
        return {}

    async def enable_user(self, uid): self.calls.append(("enable", uid))

    async def disable_user(self, uid): self.calls.append(("disable", uid))

    async def patch_user(self, uid, payload): self.calls.append(("patch", payload))

    async def get_subscription(self, uid): return {"subscriptionUrl": "u"}


def _gift(code="GIFT_X"):
    return GiftCode(code=code, plan_id=1, duration_days=30, max_uses=1, purchaser_user_id=2,
                    entitlements_snapshot={"days": 30, "traffic_gb": 100, "devices": 2, "profile_id": None, "currency": "RUB"},
                    purchase_amount=Decimal("100"))


async def _redeem(code):
    return await gift_orders.redeem_gift(SimpleNamespace(code=code, subscription_id=None, model_dump=lambda exclude=None: {}), None, None)


@pytest.mark.asyncio
async def test_a_gift_onto_an_expired_subscription_switches_access_back_on(database, monkeypatch):
    db = database
    sub = await db.get(Subscription, 1)
    sub.expires_at = datetime.utcnow() - timedelta(days=5)
    sub.lifecycle_status = "expired"
    db.add(_gift())
    await db.commit()
    rw = FakeRW()
    monkeypatch.setattr(shop, "RemnawaveClient", lambda: rw)
    import app.subscription_commerce as commerce
    monkeypatch.setattr(commerce, "RemnawaveClient", lambda: rw)
    out = await gift_orders.redeem_gift(SimpleNamespace(code="GIFT_X", subscription_id=None, model_dump=lambda exclude=None: {}), None, db)
    sub = await db.get(Subscription, 1)
    assert out["ok"] and sub.lifecycle_status == "active"
    assert ("enable", "remote-1") in rw.calls
    assert rw.calls.index(("enable", "remote-1")) < next(i for i, c in enumerate(rw.calls) if c[0] == "extend")


def test_a_gift_keeps_the_value_of_paid_days_for_upgrades():
    now = datetime.utcnow()
    unit = Decimal(100) / 30
    # 25 paid days + 30 gifted: the paid value (25 × unit) is spread over 55 days.
    spread = gift_orders.gift_unit_price(unit, now + timedelta(days=25), now + timedelta(days=55), now)
    assert abs(spread * 55 - unit * 25) < Decimal("0.01")
    assert gift_orders.gift_unit_price(unit, now - timedelta(days=1), now + timedelta(days=30), now) == 0
    assert gift_orders.gift_unit_price(None, now + timedelta(days=5), now + timedelta(days=35), now) == 0


def _payment(order, status, **kw):
    return Payment(user_id=1, subscription_id=1, plan_id=1, provider="yookassa", order_id=order, amount=100, currency="RUB",
                   status=status, fulfillment_status="completed", duration_days_snapshot=30, purpose="subscription", **kw)


@pytest.mark.asyncio
async def test_refunding_the_latest_payment_takes_back_only_its_days(database, monkeypatch):
    db = database
    sub = await db.get(Subscription, 1)
    sub.expires_at = datetime.utcnow() + timedelta(days=55)
    p1, p2 = _payment("o1", "paid"), _payment("o2", "refunded")
    db.add_all([p1, p2])
    await db.commit()
    rw = FakeRW()
    monkeypatch.setattr(shop, "RemnawaveClient", lambda: rw)
    out = await shop._safe_revoke_for_refunded_payment(db, p2, "admin", "x")
    await db.commit()
    assert out["revoked"] and out["days_removed"] == 30
    left = sub.expires_at - datetime.utcnow()
    assert timedelta(days=24, hours=23) < left <= timedelta(days=25)
    assert ("disable", "remote-1") not in rw.calls and rw.calls[0][0] == "patch"
    # A retry or a second reconcile never subtracts again.
    again = await shop._safe_revoke_for_refunded_payment(db, p2, "admin", "x")
    assert again.get("already_applied") and sub.expires_at - datetime.utcnow() > timedelta(days=24)


@pytest.mark.asyncio
async def test_refunding_the_only_payment_still_ends_access(database, monkeypatch):
    db = database
    sub = await db.get(Subscription, 1)
    sub.expires_at = datetime.utcnow() + timedelta(days=29)
    p = _payment("o1", "refunded")
    db.add(p)
    await db.commit()
    rw = FakeRW()
    monkeypatch.setattr(shop, "RemnawaveClient", lambda: rw)
    assert (await shop._safe_revoke_for_refunded_payment(db, p, "admin", "x"))["revoked"]
    assert ("disable", "remote-1") in rw.calls and sub.expires_at <= datetime.utcnow()


@pytest.mark.asyncio
async def test_a_purchase_found_by_username_adds_all_paid_days(database, monkeypatch):
    db = database
    sub = await db.get(Subscription, 1)
    remaining = datetime.utcnow() + timedelta(days=20)
    sub.remnawave_uuid = "None"
    sub.expires_at = remaining
    p = Payment(user_id=1, subscription_id=1, plan_id=1, provider="yookassa", order_id="o3", amount=100, currency="RUB",
                status="paid", fulfillment_status="pending", duration_days_snapshot=30, traffic_limit_gb_snapshot=100, purpose="subscription")
    db.add(p)
    await db.commit()
    rw = FakeRW(status="ACTIVE")
    rw.expiry = remaining

    async def by_name(name): return {"id": "remote-1", "status": "ACTIVE"}
    rw.get_user_by_username = by_name
    monkeypatch.setattr(shop, "RemnawaveClient", lambda: rw)
    monkeypatch.setattr(shop, "redis_client", object())
    await shop.fulfill(p.id, db)
    sub = await db.get(Subscription, 1)
    assert ("extend", 30) in rw.calls
    assert sub.expires_at > datetime.utcnow() + timedelta(days=49)


@pytest.mark.asyncio
async def test_a_direct_purchase_ends_partner_attribution_for_renewals(database):
    db = database
    db.add(_payment("partner-1", "paid", reseller_id=7, reseller_percent_snapshot=Decimal("10")))
    await db.commit()
    assert (await partners.latest_partner_order(db, 1)).order_id == "partner-1"
    db.add(_payment("direct-1", "paid"))
    await db.commit()
    assert await partners.latest_partner_order(db, 1) is None
    assert await partners.renewal_terms(db, 1) == {}


@pytest.mark.asyncio
async def test_auto_renew_payments_get_a_ledger_credit(database):
    db = database
    p = _payment("auto-renew-1", "paid")
    db.add(p)
    await db.commit()
    await shop._record_paid(db, p)
    await shop._record_paid(db, p)
    await db.commit()
    rows = (await db.execute(select(FinancialLedger).where(FinancialLedger.payment_id == p.id))).scalars().all()
    assert [(r.operation_key, r.direction) for r in rows] == [(f"payment:{p.id}:paid", "credit")]


class Panel:
    async def list_nodes(self, start=0, size=1): return {}


@pytest.mark.asyncio
async def test_a_spent_refunded_top_up_alerts_the_operator(database):
    user = await database.get(User, 1)
    user.wallet_balance = Decimal("-250")
    await database.commit()
    found = {p.key: p for p in await ops_alerts.collect(database, datetime.utcnow(), remnawave=Panel())}
    assert "wallet_debt:1" in found and "-250" in found["wallet_debt:1"].detail


@pytest.mark.asyncio
async def test_after_payment_screen_reads_only_the_customers_own_order(database):
    db = database
    db.add_all([_payment("order-paid-1", "paid"),
                Payment(user_id=1, plan_id=1, provider="yookassa", order_id="order-wait-1", amount=100, currency="RUB",
                        status="paid", fulfillment_status="pending", purpose="subscription"),
                Payment(user_id=1, plan_id=1, provider="yookassa", order_id="order-fail-1", amount=100, currency="RUB",
                        status="failed", fulfillment_status="pending", purpose="topup"),
                Payment(user_id=2, plan_id=1, provider="yookassa", order_id="order-other-1", amount=100, currency="RUB",
                        status="paid", fulfillment_status="completed", purpose="subscription")])
    await db.commit()
    request = SimpleNamespace(headers={}, cookies={})
    assert (await shop.my_payment_by_order("order-paid-1", request, db))["state"] == "paid"
    assert (await shop.my_payment_by_order("order-wait-1", request, db))["state"] == "processing"
    failed = await shop.my_payment_by_order("order-fail-1", request, db)
    assert failed["state"] == "failed" and failed["purpose"] == "topup"
    with pytest.raises(shop.HTTPException) as other:
        await shop.my_payment_by_order("order-other-1", request, db)
    assert other.value.status_code == 404


def test_payment_return_address_carries_the_order(monkeypatch):
    monkeypatch.setattr(shop.settings, "cabinet_url", "https://shop.example/cabinet?lang=ru&order=old")
    assert shop._return_url("abc-123") == "https://shop.example/cabinet?lang=ru&order=abc-123"
    assert shop._return_url("abc-123", "https://app.example") == "https://app.example/?order=abc-123"
    assert shop._return_url("abc-123", "") == ""


def test_promotions_get_a_seasonal_lusi_sticker():
    assert season_sticker(datetime(2026, 12, 20)) == "holiday"
    assert season_sticker(datetime(2027, 1, 5)) == "holiday"
    assert season_sticker(datetime(2026, 7, 1)) == "gift"
