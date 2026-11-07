"""3.0.1 critical audit contracts."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_release_301_is_current_and_documented():
    notes = (ROOT / "docs/archive/root/RELEASE_NOTES_V3_0_1.md").read_text()
    readme = (ROOT / "docs/archive/README_BEFORE_WORKSPACE.md").read_text()
    security = (ROOT / "docs/archive/SECURITY_BEFORE_ALPHA_6.md").read_text()
    instruction = (ROOT / "docs/archive/INSTRUCTION_BEFORE_ALPHA_6.md").read_text()
    assert "3.0.1" in notes and "Русский" in notes and "English" in notes
    assert "3.0.1" in readme and "3.0.0-realise" in readme
    assert "3.0.1" in security and "decrypt_secret" in security
    assert "9.13" in instruction
    import sys
    import app.main  # noqa: F401
    assert "backend.app.security" not in sys.modules  # the app imports its own package, never a second copy


def test_gift_lock_order():
    # The wallet key and one debit: tests/test_behaviour_gift_cards.py; the checkout key for another plan:
    # tests/test_behaviour_payments_v2.py (BACKLOG A1).
    gift = (ROOT / "backend/app/gift_orders.py").read_text()
    assert gift.index("with_for_update") < gift.index("code='GIFT_'")
