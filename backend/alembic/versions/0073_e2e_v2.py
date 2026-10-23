"""Staging E2E v2: runs, provider cases and encrypted webhook captures for replay."""
from alembic import op
import sqlalchemy as sa

revision = "0073_e2e_v2"
down_revision = "0072_traffic_analysis"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "e2e_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("nonce", sa.String(128), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("active", sa.Boolean()),
        sa.Column("providers", sa.JSON(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("buyer_user_id", sa.Integer()),
        sa.Column("admin_id", sa.Integer(), nullable=False),
        sa.Column("admin_email", sa.String(320), nullable=False),
        sa.Column("payment_timeout_seconds", sa.Integer(), nullable=False, server_default="1800"),
        sa.Column("distribution_tag", sa.String(32), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("attestation", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime()),
        sa.Column("finished_at", sa.DateTime()),
        sa.Column("heartbeat_at", sa.DateTime()),
    )
    op.create_index("uq_e2e_runs_active", "e2e_runs", ["active"], unique=True,
                    postgresql_where=sa.text("active"), sqlite_where=sa.text("active"))
    op.create_table(
        "e2e_cases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("e2e_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("stage", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("checks", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(128)),
        sa.Column("payment_id", sa.Integer()),
        sa.Column("order_id", sa.String(255)),
        sa.Column("provider_payment_id", sa.String(255)),
        sa.Column("amount", sa.Numeric(12, 2)),
        sa.Column("currency", sa.String(3)),
        sa.Column("checkout_url", sa.Text()),
        sa.Column("webhook_event_id", sa.String(255)),
        sa.Column("subscription_id", sa.Integer()),
        sa.Column("remote_user_id", sa.String(255)),
        sa.Column("refund_id", sa.Integer()),
        sa.Column("provider_refund_id", sa.String(255)),
        sa.Column("error", sa.Text()),
        sa.Column("checkout_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("run_id", "provider", name="uq_e2e_cases_run_provider"),
    )
    op.create_index("ix_e2e_cases_run_id", "e2e_cases", ["run_id"])
    op.create_index("ix_e2e_cases_payment_id", "e2e_cases", ["payment_id"])
    op.create_table(
        "e2e_webhook_captures",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("case_id", sa.Integer(), sa.ForeignKey("e2e_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("path", sa.String(128), nullable=False),
        sa.Column("body_sha256", sa.String(64), nullable=False),
        sa.Column("data_encrypted", sa.Text()),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("case_id", name="uq_e2e_webhook_captures_case"),
    )


def downgrade():
    op.drop_table("e2e_webhook_captures")
    op.drop_index("ix_e2e_cases_payment_id", table_name="e2e_cases")
    op.drop_index("ix_e2e_cases_run_id", table_name="e2e_cases")
    op.drop_table("e2e_cases")
    op.drop_index("uq_e2e_runs_active", table_name="e2e_runs")
    op.drop_table("e2e_runs")
