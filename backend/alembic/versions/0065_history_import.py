"""Versioned historical import of subscriptions and payments with a rollback journal."""
from alembic import op
import sqlalchemy as sa

revision = "0065_history_import"
down_revision = "0064_runtime_settings"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "history_import_jobs",
        sa.Column("id", sa.String(48), primary_key=True),
        sa.Column("namespace", sa.String(64), nullable=False),
        sa.Column("adapter", sa.String(48), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("actor", sa.String(320), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("payload_encrypted", sa.Text(), nullable=False),
        sa.Column("control", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("result", sa.JSON()),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("applied_at", sa.DateTime()),
        sa.Column("rolled_back_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_history_import_jobs_expires_at", "history_import_jobs", ["expires_at"])
    op.create_table(
        "imported_payments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_key", sa.String(64), nullable=False),
        sa.Column("job_id", sa.String(48), sa.ForeignKey("history_import_jobs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_payment_id", sa.String(128), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("paid_at", sa.DateTime()),
        sa.Column("description", sa.String(255)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("source_key", name="uq_imported_payments_source_key"),
    )
    op.create_index("ix_imported_payments_job_id", "imported_payments", ["job_id"])
    op.create_index("ix_imported_payments_user_id", "imported_payments", ["user_id"])
    op.create_table(
        "imported_subscription_links",
        sa.Column("source_key", sa.String(64), primary_key=True),
        sa.Column("job_id", sa.String(48), sa.ForeignKey("history_import_jobs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("subscription_id", sa.Integer(), sa.ForeignKey("subscriptions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("subscription_id", name="uq_imported_subscription_links_subscription"),
    )
    op.create_index("ix_imported_subscription_links_job_id", "imported_subscription_links", ["job_id"])
    op.create_index("ix_imported_subscription_links_user_id", "imported_subscription_links", ["user_id"])


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("LOCK TABLE history_import_jobs, imported_payments, imported_subscription_links IN ACCESS EXCLUSIVE MODE")
    for table in ("history_import_jobs", "imported_payments", "imported_subscription_links"):
        if bind.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError("Historical import journal prevents downgrade")
    op.drop_table("imported_subscription_links")
    op.drop_table("imported_payments")
    op.drop_index("ix_history_import_jobs_expires_at", table_name="history_import_jobs")
    op.drop_table("history_import_jobs")
