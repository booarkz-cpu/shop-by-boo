"""Behaviour of store receipts and card webhooks: no free plan from a client-side claim.

Replaces the source-text checks of test_critical_audit_v2002 with calls of the real code: the
Apple path is driven with forged and genuine-looking transactions, Stripe and PayPal amounts are
read from real-shaped webhook events.
"""
import time
from decimal import Decimal

import jwt
import pytest

from app import payment_platform
from app.config import settings
from app.payment_platform import AppleStorePlatform, PayPalPlatform, PlatformProviderError, StripePlatform


def unsigned(payload: dict) -> str:
    return jwt.encode(payload, "client-side-secret-that-the-shop-never-trusts", algorithm="HS256")


@pytest.fixture
def apple(monkeypatch):
    monkeypatch.setattr(settings, "apple_bundle_id", "shop.remnawave.user")
    monkeypatch.setattr(settings, "apple_issuer_id", "issuer")
    monkeypatch.setattr(settings, "apple_key_id", "KEY123")
    monkeypatch.setattr(settings, "apple_private_key", "unused-in-these-tests")
    return AppleStorePlatform()


@pytest.mark.asyncio
async def test_apple_needs_server_api_credentials(monkeypatch):
    monkeypatch.setattr(settings, "apple_bundle_id", "shop.remnawave.user")
    monkeypatch.setattr(settings, "apple_issuer_id", "")
    with pytest.raises(PlatformProviderError, match="credentials are not configured"):
        await AppleStorePlatform().verify_transaction(unsigned({"transactionId": "1"}))


@pytest.mark.asyncio
async def test_apple_client_jws_alone_grants_nothing(apple, monkeypatch):
    calls = []

    async def server_says(self, transaction_id):
        calls.append(transaction_id)
        return {}  # the App Store does not know this transaction
    monkeypatch.setattr(AppleStorePlatform, "get_transaction", server_says)
    with pytest.raises(PlatformProviderError, match="did not return a signed transaction"):
        await apple.verify_transaction(unsigned({"transactionId": "42", "bundleId": "shop.remnawave.user",
                                                 "expiresDate": int(time.time() * 1000) + 86_400_000}))
    assert calls == ["42"], "the transaction is always looked up on the App Store Server API"
    with pytest.raises(PlatformProviderError, match="transaction id is required"):
        await apple.verify_transaction(unsigned({"bundleId": "shop.remnawave.user"}))


@pytest.mark.parametrize("server_payload, message", [
    ({"transactionId": "42", "bundleId": "other.app", "expiresDate": 9_999_999_999_999}, "bundle id mismatch"),
    ({"transactionId": "43", "bundleId": "shop.remnawave.user", "expiresDate": 9_999_999_999_999}, "transaction id mismatch"),
    ({"transactionId": "42", "bundleId": "shop.remnawave.user", "expiresDate": 9_999_999_999_999, "revocationDate": 1}, "revoked"),
    ({"transactionId": "42", "bundleId": "shop.remnawave.user", "expiresDate": 1_000}, "expired"),
    ({"transactionId": "42", "bundleId": "shop.remnawave.user"}, "expired or has no expiry"),
])
@pytest.mark.asyncio
async def test_apple_server_answer_decides(apple, monkeypatch, server_payload, message):
    async def server_says(self, transaction_id):
        return {"signedTransactionInfo": unsigned(server_payload)}
    monkeypatch.setattr(AppleStorePlatform, "get_transaction", server_says)
    with pytest.raises(PlatformProviderError, match=message):
        await apple.verify_transaction(unsigned({"transactionId": "42"}))


@pytest.mark.asyncio
async def test_apple_valid_server_transaction_is_returned(apple, monkeypatch):
    payload = {"transactionId": "42", "bundleId": "shop.remnawave.user", "productId": "corgi.year",
               "expiresDate": int(time.time() * 1000) + 86_400_000}

    async def server_says(self, transaction_id):
        return {"signedTransactions": [unsigned(payload)]}
    monkeypatch.setattr(AppleStorePlatform, "get_transaction", server_says)
    result = await apple.verify_transaction(unsigned({"transactionId": "42", "productId": "forged.lifetime"}))
    assert result["productId"] == "corgi.year", "the product comes from the server, not from the client"


@pytest.mark.parametrize("event, expected", [
    ({"type": "checkout.session.completed", "data": {"object": {"payment_status": "paid", "amount_total": 29900, "currency": "rub"}}},
     (Decimal("299.00"), "RUB")),
    ({"type": "checkout.session.completed", "data": {"object": {"payment_status": "unpaid", "amount_total": 29900, "currency": "rub"}}}, None),
    ({"type": "payment_intent.succeeded", "data": {"object": {"amount_received": 1050, "currency": "usd"}}}, (Decimal("10.50"), "USD")),
    ({"type": "payment_intent.succeeded", "data": {"object": {"currency": "usd"}}}, None),
    ({"type": "payment_intent.succeeded", "data": {"object": {"amount_received": 1050}}}, None),
    ({"type": "charge.refunded", "data": {"object": {"amount": 1050, "currency": "usd"}}}, None),
    ({}, None),
])
def test_stripe_counts_only_collected_money(event, expected):
    assert StripePlatform().confirmed_amount(event) == expected


@pytest.mark.parametrize("event, expected", [
    ({"resource": {"amount": {"value": "4.99", "currency_code": "usd"}}}, (Decimal("4.99"), "USD")),
    ({"resource": {"purchase_units": [{"amount": {"value": "299", "currency_code": "RUB"}}]}}, (Decimal("299.00"), "RUB")),
    ({"resource": {"amount": {"value": "", "currency_code": "USD"}}}, None),
    ({"resource": {"amount": {"value": "4.99"}}}, None),
    ({"resource": {}}, None),
])
def test_paypal_counts_only_captured_money(event, expected):
    assert PayPalPlatform().captured_amount(event) == expected


@pytest.mark.asyncio
async def test_stripe_api_check_fails_closed_without_a_key(monkeypatch):
    monkeypatch.setattr(settings, "stripe_secret_key", "")
    assert await StripePlatform().verify_succeeded("pi_123", Decimal("10"), "USD") is False
    assert await StripePlatform().verify_succeeded("", Decimal("10"), "USD") is False


@pytest.mark.asyncio
async def test_paypal_api_errors_mean_not_paid(monkeypatch):
    async def broken_token(self):
        raise RuntimeError("network down")
    monkeypatch.setattr(PayPalPlatform, "_token", broken_token)
    assert await PayPalPlatform().verify_succeeded("ORDER-1", Decimal("4.99"), "USD") is False
    assert payment_platform.PlatformProviderError is PlatformProviderError
