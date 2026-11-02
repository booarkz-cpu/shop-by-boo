"""v28.58: duplicate indexes, missing foreign-key indexes and gift_redemptions.operation_key NOT NULL.

* 26 indexes repeat a unique constraint on the same column (on ``payments.order_id`` there were three).
  An index is dropped only when a constraint-backed unique index on exactly the same columns exists,
  so an installation whose history differs keeps whatever it needs.
* Six foreign keys had no index (deleting the parent row scanned the child table), and six columns the
  models index never got their index from the migrations.
* ``gift_redemptions.operation_key`` was added as nullable in 0032 while the model requires it; rows
  without a key get ``legacy:<id>`` (the key is unique and only compared on new redemptions).
"""
from alembic import op
import sqlalchemy as sa

revision = "0089_index_cleanup"
down_revision = "0088_filter_and_regions"
branch_labels = None
depends_on = None

# (table, redundant index, its columns) — the unique constraint on the same columns stays.
DUPLICATES = [
    ("account_merge_aliases", "ix_account_merge_aliases_referral_code", ["referral_code"], False),
    ("account_merge_aliases", "ix_account_merge_aliases_source_user_id", ["source_user_id"], False),
    ("account_merge_aliases", "ix_account_merge_aliases_telegram_id", ["telegram_id"], False),
    ("account_merge_aliases", "ix_account_merge_aliases_yandex_id", ["yandex_id"], False),
    ("account_merge_aliases", "ix_account_merge_aliases_vk_id", ["vk_id"], False),
    ("account_merge_aliases", "ix_account_merge_aliases_email", ["email"], False),
    ("account_merge_authorizations", "ix_account_merge_authorizations_token_hash", ["token_hash"], False),
    ("admin_users", "ix_admin_users_telegram_id", ["telegram_id"], False),
    ("admin_users", "ix_admin_users_email", ["email"], False),
    ("auth_exchange_codes", "ix_auth_exchange_codes_code_hash", ["code_hash"], False),
    ("auto_renew_methods", "ix_auto_renew_methods_user_id", ["user_id"], False),
    ("cabinet_menu_items", "ix_cabinet_menu_items_slug", ["slug"], False),
    ("feature_flags", "ix_feature_flags_key", ["key"], True),
    ("gift_codes", "ix_gift_codes_code", ["code"], True),
    ("payment_provider_health", "ix_payment_provider_health_provider", ["provider"], True),
    ("payments", "ix_payments_provider_payment_id", ["provider_payment_id"], False),
    ("payments", "uq_payments_order_id", ["order_id"], True),
    ("payments", "ix_payments_order_id", ["order_id"], False),
    ("promo_reservations", "ix_promo_reservations_order_id", ["order_id"], False),
    ("promo_reservations", "ix_promo_reservations_payment_id", ["payment_id"], False),
    ("referral_ledger", "ix_referral_ledger_payment_id", ["payment_id"], False),
    ("user_sessions", "ix_user_sessions_jti_hash", ["jti_hash"], True),
    ("users", "ix_users_telegram_id", ["telegram_id"], False),
    ("users", "ix_users_referral_code", ["referral_code"], False),
    ("webauthn_credentials", "ix_webauthn_credentials_credential_id", ["credential_id"], True),
    ("worker_states", "ix_worker_states_worker_id", ["worker_id"], True),
]

# Foreign keys without an index, and columns the models index but the migrations never did.
FK_INDEXES = [
    ("account_merge_authorizations", "target_user_id"),
    ("account_merge_operations", "authorization_id"),
    ("customer_passkey_challenges", "user_id"),
    ("promo_audiences", "group_id"),
    ("runtime_setting_changes", "source_change_id"),
    ("webauthn_challenges", "admin_id"),
    ("payment_chargebacks", "status"),
    ("payments", "idempotency_key"),
    ("payout_transactions", "status"),
    ("promo_redemptions", "user_id"),
    ("referral_rewards", "referred_user_id"),
    ("users", "referred_by_id"),
]

# The index named here exists, does not back a constraint itself, and a constraint-backed unique
# index on the same table covers exactly the same columns in the same order.
_COVERED = sa.text("""
SELECT 1
  FROM pg_index dup
  JOIN pg_class dc ON dc.oid = dup.indexrelid
  JOIN pg_namespace ns ON ns.oid = dc.relnamespace AND ns.nspname = current_schema()
 WHERE dc.relname = :name
   AND dup.indrelid = to_regclass(:tbl)
   AND NOT EXISTS (SELECT 1 FROM pg_constraint c WHERE c.conindid = dup.indexrelid)
   AND EXISTS (SELECT 1 FROM pg_index keep
                 JOIN pg_constraint c ON c.conindid = keep.indexrelid AND c.contype IN ('u', 'p')
                WHERE keep.indrelid = dup.indrelid AND keep.indexrelid <> dup.indexrelid
                  AND keep.indkey::text = dup.indkey::text AND keep.indpred IS NULL)
""")


def upgrade():
    bind = op.get_bind()
    postgres = bind.dialect.name == "postgresql"
    for table, name, _cols, _unique in DUPLICATES:
        if not postgres:
            continue  # SQLite installations are created from the models, which no longer declare these
        if bind.execute(_COVERED, {"name": name, "tbl": table}).first():
            op.drop_index(name, table_name=table)
    existing = {(t, i["name"]) for t, _ in FK_INDEXES for i in sa.inspect(bind).get_indexes(t)}
    for table, column in FK_INDEXES:
        name = f"ix_{table}_{column}"
        if (table, name) not in existing:
            op.create_index(name, table, [column])
    op.execute(sa.text("UPDATE gift_redemptions SET operation_key = 'legacy:' || id WHERE operation_key IS NULL"))
    with op.batch_alter_table("gift_redemptions") as batch:
        batch.alter_column("operation_key", existing_type=sa.String(128), nullable=False)


def downgrade():
    with op.batch_alter_table("gift_redemptions") as batch:
        batch.alter_column("operation_key", existing_type=sa.String(128), nullable=True)
    for table, column in FK_INDEXES:
        op.execute(sa.text(f'DROP INDEX IF EXISTS "ix_{table}_{column}"'))
    if op.get_bind().dialect.name != "postgresql":
        return
    existing = {(t, i["name"]) for t, *_ in DUPLICATES for i in sa.inspect(op.get_bind()).get_indexes(t)}
    for table, name, cols, unique in DUPLICATES:
        if (table, name) not in existing:
            op.create_index(name, table, cols, unique=unique)
