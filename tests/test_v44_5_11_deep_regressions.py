from main_source import main_source
from pathlib import Path

MAIN=main_source()
WORKER=Path("backend/worker.py").read_text()
PAYMENTS=Path("backend/app/payments.py").read_text()
MODELS=Path("backend/app/models.py").read_text()

def test_webhook_event_conflict_target_matches_database_constraint():
    assert "ON CONFLICT (provider,event_id) DO UPDATE" in MAIN
    assert 'UniqueConstraint("provider", "event_id", name="uq_payment_provider_events_provider_event")' in MODELS

def test_creation_unknown_is_reconciled_without_new_idempotency_key():
    assert 'Payment.status=="creation_unknown"' in MAIN
    assert 'find_by_order_id(p.order_id, p.created_at)' in MAIN
    assert 'provider.create(Decimal(str(p.amount)),p.order_id' not in MAIN
    assert 'p.status="pending"; p.fulfillment_terminal=False' in MAIN
    start = PAYMENTS.index("class YooKassaProvider")
    create = PAYMENTS[start:PAYMENTS.index("async def get_payment_status", start)]
    assert 'idempotence_key = str(metadata.get("order_id") or uuid.uuid4())' in create
    assert 'idempotence_key = str(uuid.uuid4())' not in create

def test_idempotent_retry_uses_immutable_payment_snapshot_before_promo_validation():
    marker='Resolve an existing durable intent before re-validating mutable commercial state.'
    assert marker in MAIN
    assert MAIN.index(marker) < MAIN.index('promo, promo_discount_amount=await promo_discount')

def test_trial_worker_uses_trial_snapshots_for_existing_and_new_remote_users():
    assert 'await rw.update_entitlements(remote_id,trial.traffic_limit_gb_snapshot,trial.remnawave_profile_id_snapshot)' in WORKER
    assert 'traffic=trial.traffic_limit_gb_snapshot*1024**3' in WORKER
    assert 'active_internal_squads=[trial.remnawave_profile_id_snapshot]' in WORKER

def test_yookassa_recovery_helper_uses_provider_metadata_order_id():
    assert 'async def find_by_order_id(self, order_id: str' in PAYMENTS
    assert 'metadata") or {}).get("order_id")' in PAYMENTS
