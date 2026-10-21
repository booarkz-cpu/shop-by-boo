"""Native mobile push: device registry bound to user sessions and per-device delivery queue."""
from alembic import op
import sqlalchemy as sa

revision = "0066_push_notifications"
down_revision = "0065_history_import"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("notifications", sa.Column("push_fanout_at", sa.DateTime(), nullable=True))
    op.create_index("ix_notifications_push_fanout_at", "notifications", ["push_fanout_at"])
    # Existing notifications were already delivered in-app; never push them retroactively.
    op.execute("UPDATE notifications SET push_fanout_at = created_at")
    op.create_table(
        "push_devices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("user_sessions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("platform", sa.String(16), nullable=False),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("token_encrypted", sa.Text(), nullable=False),
        sa.Column("app_version", sa.String(32)),
        sa.Column("locale", sa.String(8)),
        sa.Column("failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime()),
        sa.Column("revoke_reason", sa.String(32)),
        sa.UniqueConstraint("token_hash", name="uq_push_devices_token_hash"),
    )
    op.create_index("ix_push_devices_user_id", "push_devices", ["user_id"])
    op.create_index("ix_push_devices_session_id", "push_devices", ["session_id"])
    op.create_index("ix_push_devices_revoked_at", "push_devices", ["revoked_at"])
    op.create_table(
        "push_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("notification_id", sa.Integer(), sa.ForeignKey("notifications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("device_id", sa.Integer(), sa.ForeignKey("push_devices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=False),
        sa.Column("last_error", sa.String(255)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("sent_at", sa.DateTime()),
        sa.UniqueConstraint("notification_id", "device_id", name="uq_push_deliveries_notification_device"),
    )
    op.create_index("ix_push_deliveries_notification_id", "push_deliveries", ["notification_id"])
    op.create_index("ix_push_deliveries_device_id", "push_deliveries", ["device_id"])
    op.create_index("ix_push_deliveries_status", "push_deliveries", ["status"])
    op.create_index("ix_push_deliveries_next_attempt_at", "push_deliveries", ["next_attempt_at"])


def downgrade():
    op.drop_table("push_deliveries")
    op.drop_table("push_devices")
    op.drop_index("ix_notifications_push_fanout_at", table_name="notifications")
    op.drop_column("notifications", "push_fanout_at")
