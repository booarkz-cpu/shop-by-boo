from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS = (ROOT / "backend/app/models.py").read_text()
MIGRATIONS = ROOT / "backend/alembic/versions"


# test_privacy_delete_blocks_indefinite_subscription_and_revokes_remote_access: replaced by the behaviour test
# tests/test_matrix_privacy.py::test_an_endless_subscription_blocks_deletion_and_a_panel_failure_stops_it (C1, stage 19).

# test_withdrawal_reject_cannot_restore_balance_after_payout_started: replaced by the behaviour test
# tests/test_behaviour_withdrawals.py (C1, stage 19).


def test_v44_5_16_migration_preserves_previous_head():
    path = MIGRATIONS / '0030_v44_5_16_privacy_and_refund_integrity.py'
    text = path.read_text()
    assert '0030_v44_5_16_privacy_and_refund_integrity' in text
    assert '0029_v44_5_15_safety_integrity' in text

