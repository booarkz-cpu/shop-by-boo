"""20.0.2 audit: gift cards cannot credit a foreign currency."""
from main_source import main_source
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


# Store receipts and Stripe/PayPal amounts are covered by behaviour tests:
# tests/test_behaviour_store_and_webhooks.py (they call the real verification code).


def test_gift_card_cannot_credit_a_foreign_currency():
    main = main_source()
    redeem = main[main.index("async def redeem_gift_card"): main.index("async def list_gift_cards")]
    assert "Gift card currency does not match the shop currency" in redeem
    assert "with_for_update" in redeem
