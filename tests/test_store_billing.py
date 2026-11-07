"""v28.89.0 (BACKLOG A5): subscriptions bought in Google Play and App Store — off by default; the shop asks the store
itself; renewals and refunds arrive as the stores' notifications. Google and Apple are fakes here (live: BLOCKED_SECRETS)."""
import base64
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import jwt
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from fastapi import HTTPException
from sqlalchemy import select
from starlette.requests import Request

from app import main as shop
from app import store_billing
from app.models import Payment, RefundRequest, StoreSubscription, Subscription
from test_money_review import FakeRW
from test_subscription_commerce import database  # noqa: F401

NOW = datetime.now(timezone.utc)


def _cert(subject, issuer_name, key, issuer_key, *, ca, oid=None, days=(-1, 365)):
    builder = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, subject)]))
               .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, issuer_name)])).public_key(key.public_key())
               .serial_number(x509.random_serial_number()).not_valid_before(NOW + timedelta(days=days[0]))
               .not_valid_after(NOW + timedelta(days=days[1])).add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True))
    if oid:
        builder = builder.add_extension(x509.UnrecognizedExtension(x509.ObjectIdentifier(oid), b"\x05\x00"), critical=False)
    return builder.sign(issuer_key, hashes.SHA256())


class FakeApple:
    """An Apple-like chain: our own «Apple Root CA G3», a WWDR intermediate and a StoreKit leaf."""

    def __init__(self, *, leaf_oid=store_billing.APPLE_LEAF_OID.dotted_string, leaf_days=(-1, 365)):
        self.root_key, self.mid_key, self.leaf_key = (ec.generate_private_key(ec.SECP256R1()) for _ in range(3))
        self.root = _cert("Apple Root CA - G3", "Apple Root CA - G3", self.root_key, self.root_key, ca=True)
        self.mid = _cert("WWDR", "Apple Root CA - G3", self.mid_key, self.root_key, ca=True, oid=store_billing.APPLE_INTERMEDIATE_OID.dotted_string)
        self.leaf = _cert("StoreKit", "WWDR", self.leaf_key, self.mid_key, ca=False, oid=leaf_oid, days=leaf_days)

    def fingerprint(self):
        return self.root.fingerprint(hashes.SHA256()).hex()

    def sign(self, payload, *, key=None, chain=None):
        x5c = [base64.b64encode(c.public_bytes(serialization.Encoding.DER)).decode() for c in (chain or (self.leaf, self.mid, self.root))]
        return jwt.encode(payload, key or self.leaf_key, algorithm="ES256", headers={"x5c": x5c})


@pytest.fixture
def apple(monkeypatch):
    fake = FakeApple()
    monkeypatch.setattr(store_billing, "APPLE_ROOT_G3_SHA256", fake.fingerprint())
    return fake


def test_an_apple_signed_payload_is_accepted(apple):
    assert store_billing.verify_apple_jws(apple.sign({"transactionId": "1"})) == {"transactionId": "1"}


def test_a_jws_outside_apples_chain_is_refused(apple, monkeypatch):
    stranger = FakeApple()
    bad = {
        "another root": stranger.sign({"transactionId": "1"}),
        "signed by another key": apple.sign({"transactionId": "1"}, key=ec.generate_private_key(ec.SECP256R1())),
        "leaf from another intermediate": apple.sign({"transactionId": "1"}, chain=(apple.leaf, stranger.mid, apple.root)),
        "no chain": jwt.encode({"transactionId": "1"}, apple.leaf_key, algorithm="ES256"),
        "not ES256": jwt.encode({"transactionId": "1"}, "secret", algorithm="HS256"),
        "garbage": "not-a-jws",
    }
    for name, token in bad.items():
        with pytest.raises(store_billing.StoreError):
            store_billing.verify_apple_jws(token)
        assert name
    no_marker = FakeApple(leaf_oid="1.2.3.4")
    monkeypatch.setattr(store_billing, "APPLE_ROOT_G3_SHA256", no_marker.fingerprint())
    with pytest.raises(store_billing.StoreError):
        store_billing.verify_apple_jws(no_marker.sign({"transactionId": "1"}))
    expired = FakeApple(leaf_days=(-30, -1))
    monkeypatch.setattr(store_billing, "APPLE_ROOT_G3_SHA256", expired.fingerprint())
    with pytest.raises(store_billing.StoreError, match="validity"):
        store_billing.verify_apple_jws(expired.sign({"transactionId": "1"}))


def http(path, body, query=b""):
    raw = json.dumps(body).encode()

    async def receive():
        return {"type": "http.request", "body": raw, "more_body": False}
    return Request({"type": "http", "method": "POST", "path": path, "headers": [(b"content-type", b"application/json")],
                    "client": ("203.0.113.1", 443), "query_string": query}, receive)


@pytest.fixture
def store(database, monkeypatch):
    """The shop with store purchases on, one product mapped to plan 1, locks and the panel faked."""
    state = SimpleNamespace(google={}, revoked=[], reversed=[])
    monkeypatch.setattr(shop.settings, "mobile_store_purchases_enabled", True)
    monkeypatch.setattr(shop.settings, "mobile_store_products", json.dumps({"corgi.month": 1}))
    monkeypatch.setattr(shop.settings, "google_play_package", "shop.remnawave.user")
    monkeypatch.setattr(shop.settings, "google_play_rtdn_token", "rtdn-secret")
    monkeypatch.setattr(shop.settings, "apple_bundle_id", "shop.remnawave.user")
    monkeypatch.setattr(shop, "engine", database.bind)
    monkeypatch.setattr(shop, "redis_client", object())

    async def lock(*a, **k):
        return "lock", "token"

    async def release(*a, **k):
        return None

    async def user(request, db):
        return await db.get(shop.User, 1)

    async def google(self, token):
        if token not in state.google:
            raise shop.PlatformProviderError("Google Play purchase is not active")
        return dict(state.google[token])

    async def revoke(db, payment, actor, action):
        state.revoked.append(payment.id)
        return {"revoked": True}

    async def reverse(db, payment, actor):
        state.reversed.append(payment.id)
        return {"reversed": True}
    monkeypatch.setattr(shop, "_acquire_user_fulfillment_lock", lock)
    monkeypatch.setattr(shop, "_acquire_payment_side_effect_lock", lock)
    monkeypatch.setattr(shop, "_release_payment_side_effect_lock", release)
    monkeypatch.setattr(shop, "user_from_token", user)
    monkeypatch.setattr(shop.GooglePlayPlatform, "verify_subscription", google)
    monkeypatch.setattr(shop, "_safe_revoke_for_refunded_payment", revoke)
    monkeypatch.setattr(shop, "_reverse_referral_reward_for_refund", reverse)
    return state


def google_answer(order, product="corgi.month"):
    return {"subscriptionState": "SUBSCRIPTION_STATE_ACTIVE", "latestOrderId": order, "productId": product,
            "lineItems": [{"productId": product, "expiryTime": (NOW + timedelta(days=30)).isoformat().replace("+00:00", "Z")}]}


async def panel(database, monkeypatch):
    sub = await database.get(Subscription, 1, populate_existing=True)
    rw = FakeRW(status="ACTIVE")
    rw.expiry = sub.expires_at
    monkeypatch.setattr(shop, "RemnawaveClient", lambda: rw)
    return rw


@pytest.mark.asyncio
async def test_store_purchases_are_off_until_the_owner_turns_them_on(database, monkeypatch):
    monkeypatch.setattr(shop.settings, "mobile_store_purchases_enabled", False)
    calls = []

    async def google(self, token):
        calls.append(token)
    monkeypatch.setattr(shop.GooglePlayPlatform, "verify_subscription", google)
    payload = shop.MobilePurchaseIn(provider="google_play", plan_id=1, purchase_token="t")
    for call in (lambda: shop.verify_mobile_purchase(payload, http("/api/payments/mobile/verify", {}), database),
                 lambda: store_billing.app_store_notification(http("/api/webhooks/app-store", {}), database),
                 lambda: store_billing.google_play_notification(http("/api/webhooks/google-play", {}), database)):
        with pytest.raises(HTTPException) as err:
            await call()
        assert err.value.status_code == 410
    assert calls == [], "nobody asks Google while it is off"


@pytest.mark.asyncio
async def test_a_google_play_subscription_is_granted_renewed_and_taken_back(database, store, monkeypatch):
    db = database
    await panel(db, monkeypatch)
    store.google["token-1"] = google_answer("GPA.1000-0")
    verify = lambda: shop.verify_mobile_purchase(shop.MobilePurchaseIn(provider="google_play", plan_id=1, purchase_token="token-1"),
                                                 http("/api/payments/mobile/verify", {}), db)
    first = await verify()
    assert first["ok"] and first["fulfilled"]
    paid = await db.get(Payment, first["payment_id"])
    assert (paid.provider_payment_id, paid.status, paid.subscription_id, paid.fulfillment_status) == ("GPA.1000-0", "paid", 1, "completed")
    again = await verify()
    assert again["repeat"] and again["payment_id"] == first["payment_id"], "one store order → one shop payment"
    link = (await db.execute(select(StoreSubscription))).scalar_one()
    assert link.chain_key == store_billing.google_chain("token-1") and "token-1" not in json.dumps([link.chain_key, link.last_order_id])

    # Wrong secret in the Pub/Sub URL.
    message = lambda note: {"message": {"data": base64.b64encode(json.dumps(note).encode()).decode(), "messageId": "1"}}
    with pytest.raises(HTTPException) as err:
        await store_billing.google_play_notification(http("/api/webhooks/google-play", message({}), b"token=guess"), db)
    assert err.value.status_code == 403

    # RENEWED: the state is read from Google again; the new order is a new payment for the same subscription.
    await panel(db, monkeypatch)
    store.google["token-1"] = google_answer("GPA.1000-0..1")
    renewed = await store_billing.google_play_notification(http("/api/webhooks/google-play", message(
        {"packageName": "shop.remnawave.user", "subscriptionNotification": {"notificationType": 2, "purchaseToken": "token-1"}}), b"token=rtdn-secret"), db)
    second = await db.get(Payment, renewed["payment_id"])
    assert second.provider_payment_id == "GPA.1000-0..1" and second.subscription_id == 1 and second.status == "paid"

    # A purchase the shop never saw (bought on another account, or before) grants nothing from a notification.
    unknown = await store_billing.google_play_notification(http("/api/webhooks/google-play", message(
        {"packageName": "shop.remnawave.user", "subscriptionNotification": {"notificationType": 2, "purchaseToken": "token-x"}}), b"token=rtdn-secret"), db)
    assert unknown["ignored"]

    # Voided (refunded in Google Play): that order's payment is refunded and the access taken back, once.
    voided = message({"packageName": "shop.remnawave.user", "voidedPurchaseNotification": {"purchaseToken": "token-1", "orderId": "GPA.1000-0..1"}})
    out = await store_billing.google_play_notification(http("/api/webhooks/google-play", voided, b"token=rtdn-secret"), db)
    assert out["status"] == "refunded"
    again = await store_billing.google_play_notification(http("/api/webhooks/google-play", voided, b"token=rtdn-secret"), db)
    assert again["repeat"]
    await db.refresh(second)
    assert second.status == "refunded" and store.revoked == [second.id] and store.reversed == [second.id]
    refund = (await db.execute(select(RefundRequest).where(RefundRequest.payment_id == second.id))).scalar_one()
    assert refund.status == "refunded" and refund.amount == Decimal(str(second.amount))


@pytest.mark.asyncio
async def test_the_referral_reward_stays_while_the_access_could_not_be_taken_back(database, store, monkeypatch):
    db = database
    await panel(db, monkeypatch)
    store.google["token-2"] = google_answer("GPA.2000-0")
    first = await shop.verify_mobile_purchase(shop.MobilePurchaseIn(provider="google_play", plan_id=1, purchase_token="token-2"),
                                              http("/api/payments/mobile/verify", {}), db)

    async def down(db, payment, actor, action):
        raise RuntimeError("panel is down")
    monkeypatch.setattr(shop, "_safe_revoke_for_refunded_payment", down)
    payment = await db.get(Payment, first["payment_id"])
    out = await store_billing.take_back(db, payment, "test")
    assert out["status"] == "refunded_pending_revoke" and store.reversed == [], "the refund scheduler retries the revoke"


@pytest.mark.asyncio
async def test_a_product_for_another_plan_or_another_account_is_refused(database, store, monkeypatch):
    db = database
    await panel(db, monkeypatch)
    store.google["token-3"] = google_answer("GPA.3000-0", product="corgi.year")
    with pytest.raises(HTTPException) as err:
        await shop.verify_mobile_purchase(shop.MobilePurchaseIn(provider="google_play", plan_id=1, purchase_token="token-3"), http("/x", {}), db)
    assert err.value.status_code == 402, "an unmapped product is not sold"
    store.google["token-3"] = google_answer("GPA.3000-0")
    await shop.verify_mobile_purchase(shop.MobilePurchaseIn(provider="google_play", plan_id=1, purchase_token="token-3"), http("/x", {}), db)

    async def second(request, db):
        return await db.get(shop.User, 2)
    monkeypatch.setattr(shop, "user_from_token", second)
    with pytest.raises(HTTPException) as err:
        await shop.verify_mobile_purchase(shop.MobilePurchaseIn(provider="google_play", plan_id=1, purchase_token="token-3"), http("/x", {}), db)
    assert err.value.status_code == 409, "one store purchase serves one account"


@pytest.mark.asyncio
async def test_app_store_notifications_renew_and_refund(database, store, apple, monkeypatch):
    db = database
    await panel(db, monkeypatch)

    async def server(self, signed):
        return {"transactionId": "2000", "originalTransactionId": "1000", "productId": "corgi.month", "bundleId": "shop.remnawave.user",
                "expiresDate": int((NOW + timedelta(days=30)).timestamp() * 1000)}
    monkeypatch.setattr(shop.AppleStorePlatform, "verify_transaction", server)
    first = await shop.verify_mobile_purchase(shop.MobilePurchaseIn(provider="apple_iap", plan_id=1, signed_transaction="client-jws"), http("/x", {}), db)
    assert (await db.get(Payment, first["payment_id"])).provider_payment_id == "2000"

    def note(kind, tx, bundle="shop.remnawave.user"):
        return {"signedPayload": apple.sign({"notificationType": kind, "notificationUUID": kind + tx["transactionId"],
                                             "data": {"bundleId": bundle, "signedTransactionInfo": apple.sign(tx)}})}
    renewal = {"transactionId": "2001", "originalTransactionId": "1000", "productId": "corgi.month",
               "expiresDate": int((NOW + timedelta(days=60)).timestamp() * 1000)}
    await panel(db, monkeypatch)
    out = await store_billing.app_store_notification(http("/api/webhooks/app-store", note("DID_RENEW", renewal)), db)
    renewed = await db.get(Payment, out["payment_id"])
    assert renewed.provider_payment_id == "2001" and renewed.user_id == 1 and renewed.subscription_id == 1

    for bad in (note("REFUND", renewal, bundle="other.app"), {"signedPayload": FakeApple().sign({"notificationType": "REFUND"})}):
        with pytest.raises(HTTPException) as err:
            await store_billing.app_store_notification(http("/api/webhooks/app-store", bad), db)
        assert err.value.status_code == 403
    out = await store_billing.app_store_notification(http("/api/webhooks/app-store", note("REFUND", renewal)), db)
    assert out["status"] == "refunded"
    await db.refresh(renewed)
    assert renewed.status == "refunded" and store.revoked == [renewed.id]
    assert (await db.get(Payment, first["payment_id"], populate_existing=True)).status == "paid", "only the refunded period"
    stranger = {"transactionId": "9999", "originalTransactionId": "9000", "productId": "corgi.month"}
    assert (await store_billing.app_store_notification(http("/api/webhooks/app-store", note("DID_RENEW", stranger)), db))["ignored"]
