from main_source import main_source
from pathlib import Path
ROOT=Path(__file__).parents[1]
MAIN=main_source()
MODELS=(ROOT/'backend/app/models.py').read_text()
MIG=(ROOT/'backend/alembic/versions/0027_v44_5_10_financial_integrity.py').read_text()

# v28.32.0: the user lock, the webhook order and the provider-scoped event claim are run in
# tests/test_behaviour_payments_v2.py instead of being looked up in the source.
def test_v23_provisioning_operation_and_event_constraint():
    assert 'class ProvisioningOperation' in MODELS
    assert 'get_user_by_username' in MAIN
    assert 'uq_payment_provider_events_provider_event' in MIG

def test_v23_tar_restore_safety_and_recovery_mode():
    assert 'posix.is_absolute() or ".." in parts' in MAIN
    assert '_safe_extract_members(tar,{name},work)' in MAIN
    assert 'set_setting(fail_db,"restore_state","failed")' in MAIN

def test_v23_security_and_recovery_contracts():
    assert 'Metrics authentication is not configured' in MAIN
    assert 'WorkerState' in MAIN
    assert '/api/admin/recovery' in MAIN
    assert '/api/admin/incident-mode' in MAIN
    assert '/api/admin/referrals/reconcile' in MAIN
