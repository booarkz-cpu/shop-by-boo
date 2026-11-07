"""20.0.2 audit: gift cards cannot credit a foreign currency."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


# Store receipts and Stripe/PayPal amounts are covered by behaviour tests:
# tests/test_behaviour_store_and_webhooks.py (they call the real verification code).
# Gift cards in another currency: tests/test_behaviour_gift_cards.py (BACKLOG A1).
