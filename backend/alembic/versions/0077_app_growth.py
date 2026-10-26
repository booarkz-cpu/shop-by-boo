"""App growth: anonymous app analytics events, segmented push campaigns and tax receipts (fiscal_receipts)."""
from alembic import op
import sqlalchemy as sa

revision = "0077_app_growth"
down_revision = "0076_growth"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "app_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("install_hash", sa.String(64), nullable=False),
        sa.Column("user_id", sa.Integer()),
        sa.Column("platform", sa.String(16), nullable=False),
        sa.Column("app_version", sa.String(32), nullable=False, server_default=""),
        sa.Column("event", sa.String(32), nullable=False),
        sa.Column("screen", sa.String(32), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for column in ("install_hash", "user_id", "event", "created_at"):
        op.create_index(f"ix_app_events_{column}", "app_events", [column])
    op.create_table(
        "push_campaigns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("segment", sa.String(32), nullable=False),
        sa.Column("days", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("status", sa.String(16), nullable=False, server_default="sent"),
        sa.Column("recipients", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("with_push", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.String(320), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_push_campaigns_created_at", "push_campaigns", ["created_at"])
    op.create_table(
        "fiscal_receipts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("payment_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("name", sa.String(128), nullable=False, server_default=""),
        sa.Column("external_id", sa.String(128)),
        sa.Column("receipt_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("fiscal_data", sa.JSON()),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(500)),
        sa.Column("next_attempt_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("payment_id", "kind", name="uq_fiscal_receipts_payment_kind"),
    )
    for column in ("payment_id", "status", "next_attempt_at"):
        op.create_index(f"ix_fiscal_receipts_{column}", "fiscal_receipts", [column])


def downgrade():
    # Receipts already registered with the tax service must stay traceable: refuse to drop them.
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT count(*) FROM fiscal_receipts WHERE status IN ('done','sent')")).scalar():
        raise RuntimeError("fiscal_receipts holds receipts registered with the tax service; export them before downgrading")
    for column in ("payment_id", "status", "next_attempt_at"):
        op.drop_index(f"ix_fiscal_receipts_{column}", table_name="fiscal_receipts")
    op.drop_table("fiscal_receipts")
    # Analytics events are re-collected by the apps and campaign rows are a send log; the
    # notifications a campaign created stay in «notifications».
    op.drop_index("ix_push_campaigns_created_at", table_name="push_campaigns")
    op.drop_table("push_campaigns")
    for column in ("install_hash", "user_id", "event", "created_at"):
        op.drop_index(f"ix_app_events_{column}", table_name="app_events")
    op.drop_table("app_events")
