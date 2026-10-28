"""v28.37: system error log, customer activity, smart cart, referral contests, connection quality reports,
infrastructure costs (P&L)."""
from alembic import op
import sqlalchemy as sa

revision = "0080_reconciliation"
down_revision = "0079_acquisition"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "system_errors",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("fingerprint", sa.String(64), nullable=False, unique=True),
        sa.Column("level", sa.String(16), nullable=False),
        sa.Column("logger", sa.String(120), nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("traceback", sa.Text, nullable=False, server_default=""),
        sa.Column("process", sa.String(32), nullable=False, server_default=""),
        sa.Column("count", sa.Integer, nullable=False, server_default="1"),
        sa.Column("resolved", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("first_seen", sa.DateTime, nullable=False),
        sa.Column("last_seen", sa.DateTime, nullable=False),
    )
    op.create_index("ix_system_errors_last_seen", "system_errors", ["last_seen"])
    op.create_table(
        "user_activity",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, nullable=False),
        sa.Column("surface", sa.String(16), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("detail", sa.JSON),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_user_activity_user_created", "user_activity", ["user_id", "created_at"])
    op.create_index("ix_user_activity_created_at", "user_activity", ["created_at"])
    op.create_table(
        "shop_carts",
        sa.Column("user_id", sa.Integer, primary_key=True),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("expires_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "referral_contests",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("starts_at", sa.DateTime, nullable=False),
        sa.Column("ends_at", sa.DateTime, nullable=False),
        sa.Column("metric", sa.String(16), nullable=False, server_default="paid"),
        sa.Column("prizes", sa.JSON, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("results", sa.JSON),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "connection_reports",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, nullable=False),
        sa.Column("platform", sa.String(16), nullable=False),
        sa.Column("carrier", sa.String(64), nullable=False, server_default=""),
        sa.Column("network", sa.String(16), nullable=False, server_default=""),
        sa.Column("country", sa.String(2), nullable=False, server_default=""),
        sa.Column("server", sa.String(255), nullable=False),
        sa.Column("ok", sa.Boolean, nullable=False),
        sa.Column("ms", sa.Integer),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_connection_reports_created_at", "connection_reports", ["created_at"])
    op.create_index("ix_connection_reports_carrier_server", "connection_reports", ["carrier", "server"])
    op.create_table(
        "infra_costs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("month", sa.String(7), nullable=False),
        sa.Column("category", sa.String(24), nullable=False),
        sa.Column("vendor", sa.String(80), nullable=False, server_default=""),
        sa.Column("node", sa.String(120), nullable=False, server_default=""),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("note", sa.String(200), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_infra_costs_month", "infra_costs", ["month"])


def downgrade():
    op.drop_index("ix_infra_costs_month", table_name="infra_costs")
    op.drop_table("infra_costs")
    op.drop_index("ix_connection_reports_carrier_server", table_name="connection_reports")
    op.drop_index("ix_connection_reports_created_at", table_name="connection_reports")
    op.drop_table("connection_reports")
    op.drop_table("referral_contests")
    op.drop_table("shop_carts")
    op.drop_index("ix_user_activity_created_at", table_name="user_activity")
    op.drop_index("ix_user_activity_user_created", table_name="user_activity")
    op.drop_table("user_activity")
    op.drop_index("ix_system_errors_last_seen", table_name="system_errors")
    op.drop_table("system_errors")
