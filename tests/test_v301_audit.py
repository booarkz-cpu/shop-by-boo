"""3.0.1 critical audit contracts."""
from main_source import main_source
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_release_301_is_current_and_documented():
    main = main_source()
    notes = (ROOT / "docs/archive/root/RELEASE_NOTES_V3_0_1.md").read_text()
    readme = (ROOT / "docs/archive/README_BEFORE_WORKSPACE.md").read_text()
    security = (ROOT / "docs/archive/SECURITY_BEFORE_ALPHA_6.md").read_text()
    instruction = (ROOT / "docs/archive/INSTRUCTION_BEFORE_ALPHA_6.md").read_text()
    assert "3.0.1" in notes and "Русский" in notes and "English" in notes
    assert "3.0.1" in readme and "3.0.0-realise" in readme
    assert "3.0.1" in security and "decrypt_secret" in security
    assert "9.13" in instruction
    assert "backend.app.security" not in main


def test_gift_lock_order_and_checkout_intent_lock():
    # The wallet key and one debit: tests/test_behaviour_gift_cards.py (BACKLOG A1).
    main = main_source()
    gift = (ROOT / "backend/app/gift_orders.py").read_text()
    assert gift.index("with_for_update") < gift.index("code='GIFT_'")
    create = main[main.index("async def create_payment"): main.index("async def _renew_redis_lock")]
    assert "lock:checkout-intent:" in create
    assert 'if existing.plan_id != plan_id' in create
