"""v28.38: subscription proxy log, panel user change journal, panel API stats, VPN sessions, WireGuard pool,
term from the first connection, grace squads."""
from alembic import op
import sqlalchemy as sa

revision = "0081_subscription_proxy"
down_revision = "0080_reconciliation"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "sub_requests",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("short_uuid", sa.String(64), nullable=False, server_default=""),
        sa.Column("user_id", sa.Integer),
        sa.Column("app", sa.String(40), nullable=False, server_default=""),
        sa.Column("app_version", sa.String(40), nullable=False, server_default=""),
        sa.Column("os", sa.String(40), nullable=False, server_default=""),
        sa.Column("model", sa.String(80), nullable=False, server_default=""),
        sa.Column("hwid", sa.String(128), nullable=False, server_default=""),
        sa.Column("ip", sa.String(64), nullable=False, server_default=""),
        sa.Column("user_agent", sa.String(255), nullable=False, server_default=""),
        sa.Column("decision", sa.String(24), nullable=False),
        sa.Column("status", sa.Integer, nullable=False, server_default="0"),
        sa.Column("bytes", sa.Integer, nullable=False, server_default="0"),
        sa.Column("ms", sa.Integer, nullable=False, server_default="0"),
        sa.Column("outdated", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_sub_requests_created_at", "sub_requests", ["created_at"])
    op.create_index("ix_sub_requests_short_created", "sub_requests", ["short_uuid", "created_at"])
    op.create_table(
        "panel_user_changes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("panel_user", sa.String(64), nullable=False),
        sa.Column("user_id", sa.Integer),
        sa.Column("event", sa.String(64), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("changed", sa.JSON, nullable=False),
        sa.Column("snapshot", sa.JSON, nullable=False),
    )
    op.create_index("ix_panel_user_changes_created_at", "panel_user_changes", ["created_at"])
    op.create_index("ix_panel_user_changes_user_created", "panel_user_changes", ["panel_user", "created_at"])
    op.create_table(
        "panel_api_stats",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("hour", sa.DateTime, nullable=False),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("method", sa.String(8), nullable=False),
        sa.Column("path", sa.String(160), nullable=False),
        sa.Column("calls", sa.Integer, nullable=False),
        sa.Column("errors", sa.Integer, nullable=False),
        sa.Column("total_ms", sa.Integer, nullable=False),
        sa.UniqueConstraint("hour", "source", "method", "path", name="uq_panel_api_stats"),
    )
    op.create_index("ix_panel_api_stats_hour", "panel_api_stats", ["hour"])
    op.create_table(
        "vpn_sessions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("panel_user", sa.String(64), nullable=False),
        sa.Column("user_id", sa.Integer),
        sa.Column("node", sa.String(120), nullable=False, server_default=""),
        sa.Column("ip", sa.String(64), nullable=False),
        sa.Column("asn", sa.String(16), nullable=False, server_default=""),
        sa.Column("isp", sa.String(120), nullable=False, server_default=""),
        sa.Column("country", sa.String(2), nullable=False, server_default=""),
        sa.Column("first_seen", sa.DateTime, nullable=False),
        sa.Column("last_seen", sa.DateTime, nullable=False),
    )
    op.create_index("ix_vpn_sessions_last_seen", "vpn_sessions", ["last_seen"])
    op.create_index("ix_vpn_sessions_user_last", "vpn_sessions", ["panel_user", "last_seen"])
    op.create_table(
        "wg_configs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("config", sa.Text, nullable=False),
        sa.Column("subscription_id", sa.Integer),
        sa.Column("hwid", sa.String(128), nullable=False, server_default=""),
        sa.Column("assigned_at", sa.DateTime),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_wg_configs_subscription_id", "wg_configs", ["subscription_id"])
    op.create_table(
        "first_connect_waits",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("subscription_id", sa.Integer, nullable=False, unique=True),
        sa.Column("days", sa.Integer, nullable=False),
        sa.Column("deadline", sa.DateTime, nullable=False),
        sa.Column("started_at", sa.DateTime),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_first_connect_waits_deadline", "first_connect_waits", ["deadline"])
    op.create_table(
        "grace_squads",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("subscription_id", sa.Integer, nullable=False, unique=True),
        sa.Column("squads", sa.JSON, nullable=False),
        sa.Column("until", sa.DateTime, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )


def downgrade():
    for table in ("grace_squads", "first_connect_waits", "wg_configs", "vpn_sessions", "panel_api_stats",
                  "panel_user_changes", "sub_requests"):
        op.drop_table(table)
