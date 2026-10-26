"""20.0.2 audit: store receipts and card webhooks cannot grant a free plan."""
from main_source import main_source
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_apple_receipt_is_not_accepted_from_the_client_alone():
    platform = (ROOT / "backend/app/payment_platform.py").read_text()
    verify = platform[platform.index("async def verify_transaction"): platform.index("async def get_transaction")]
    assert "Apple transaction id is required" in verify
    assert "Apple App Store Server API credentials are not configured" in verify
    assert "signedTransactionInfo" in verify
    assert "return payload" not in verify
    assert "return data" not in verify
    assert "Apple transaction is revoked" in verify
    main = main_source()
    mobile = main[main.index("async def verify_mobile_purchase"): main.index("async def admin_chargebacks")]
    assert "uuid.uuid4()" not in mobile
    assert "store_product_plan_id" in mobile
    assert "Store product does not match the selected plan" in mobile
    assert "MOBILE_STORE_PRODUCTS" in (ROOT / "backend/app/config.py").read_text()


def test_stripe_and_paypal_webhooks_require_the_paid_amount():
    main = main_source()
    stripe = main[main.index("async def stripe_webhook"): main.index("async def paypal_webhook")]
    paypal = main[main.index("async def paypal_webhook"): main.index("class MobilePurchaseIn")]
    assert "confirmed_amount" in stripe
    assert "captured_amount" in paypal
    platform = (ROOT / "backend/app/payment_platform.py").read_text()
    assert "payment_status" in platform
    assert "def confirmed_amount" in platform
    assert "def captured_amount" in platform


def test_gift_card_cannot_credit_a_foreign_currency():
    main = main_source()
    redeem = main[main.index("async def redeem_gift_card"): main.index("async def list_gift_cards")]
    assert "Gift card currency does not match the shop currency" in redeem
    assert "with_for_update" in redeem
