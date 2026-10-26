"""20.0.3 audit: unpaid and zero-amount checkouts cannot grant a plan."""
from main_source import main_source
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _slice(text: str, start: str, end: str) -> str:
    i = text.index(start)
    return text[i:text.index(end, i)]


def test_zero_amount_checkout_is_refused_before_the_gateway():
    main = main_source()
    create = _slice(main, "async def create_payment", "async def _renew_redis_lock")
    assert 'if final_amount<=0: raise HTTPException(400,"Amount must be positive")' in create
    assert create.index("Amount must be positive") < create.index("candidate_provider.create")


def test_stripe_paypal_and_crypto_are_confirmed_with_the_provider():
    main = main_source()
    platform = (ROOT / "backend/app/payment_platform.py").read_text()
    stripe = _slice(main, "async def stripe_webhook", "async def paypal_webhook")
    paypal = _slice(main, "async def paypal_webhook", "class MobilePurchaseIn")
    crypto = _slice(main, "async def crypto_webhook", "async def stripe_webhook")
    assert "StripePlatform().verify_succeeded" in stripe
    assert "PayPalPlatform().verify_succeeded" in paypal
    assert "CryptoGatewayPlatform().verify_succeeded" in crypto
    assert "Invalid crypto webhook" in crypto
    assert '"crypto":CryptoGatewayPlatform()' in _slice(main, "async def reconciliation_scheduler", "async def subscription_lifecycle_scheduler")
    assert "async def verify_succeeded" in platform
    assert "def verify_webhook" in platform
    assert "timestamp.encode()+b'.'+body" in platform


def test_admin_retry_refuses_an_unpaid_payment():
    main = main_source()
    retry = _slice(main, "async def retry_payment", "# ---------- V32 Operations")
    assert 'raise HTTPException(409,"Payment is not confirmed")' in retry


def test_buyer_cannot_exempt_their_own_invoice():
    main = main_source()
    tax = _slice(main, "async def set_tax_profile", "async def payment_invoice")
    assert "row.tax_exempt=False" in tax
    assert "row.reverse_charge=False" in tax
    assert "payload.tax_exempt" not in tax


def test_panel_refresh_does_not_extend_paid_expiry():
    shop = (ROOT / "backend/app/remnawave_shop_api.py").read_text()
    refresh = _slice(shop, "async def refresh_my_remnawave_subscription", '@router.get("/admin/remnawave/shop")')
    assert "sub.expires_at" not in refresh


def test_sandbox_confirmation_requires_the_exact_order_id():
    payments = (ROOT / "backend/app/payments.py").read_text()
    sandbox = payments[payments.index("class SandboxProvider"):]
    verify = sandbox[sandbox.index("async def verify_succeeded"): sandbox.index("async def get_payment_status")]
    assert "expected_order_id not in payment_id" not in verify
    assert 'f"sandbox-{expected_order_id}"' in verify
    assert "Decimal(str(expected_amount)) <= 0" in verify
