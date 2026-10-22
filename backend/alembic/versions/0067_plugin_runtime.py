"""Plugin runtime: trusted publishers, signed packages, installs with approved capabilities, signed deliveries."""
from alembic import op
import sqlalchemy as sa

revision = "0067_plugin_runtime"
down_revision = "0066_push_notifications"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "plugin_publishers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("public_key", sa.String(64), nullable=False),
        sa.Column("fingerprint", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime()),
        sa.UniqueConstraint("public_key", name="uq_plugin_publishers_public_key"),
        sa.UniqueConstraint("fingerprint", name="uq_plugin_publishers_fingerprint"),
    )
    op.create_table(
        "plugin_packages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("plugin_id", sa.String(64), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("manifest", sa.JSON(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("publisher_fingerprint", sa.String(16), nullable=False),
        sa.Column("uploaded_by", sa.String(320), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("plugin_id", "version", name="uq_plugin_packages_version"),
    )
    op.create_index("ix_plugin_packages_plugin_id", "plugin_packages", ["plugin_id"])
    op.create_table(
        "plugin_installs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("active_version", sa.String(32)),
        sa.Column("approved_capabilities", sa.JSON(), nullable=False),
        sa.Column("approved_events", sa.JSON(), nullable=False),
        sa.Column("settings_encrypted", sa.Text()),
        sa.Column("token_hash", sa.String(64)),
        sa.Column("signing_secret_encrypted", sa.Text()),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(255)),
        sa.Column("disabled_reason", sa.String(255)),
        sa.Column("enabled_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("token_hash", name="uq_plugin_installs_token_hash"),
    )
    op.create_table(
        "plugin_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("plugin_id", sa.String(64), sa.ForeignKey("plugin_installs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event", sa.String(64), nullable=False),
        sa.Column("event_key", sa.String(120), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=False),
        sa.Column("last_error", sa.String(255)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("sent_at", sa.DateTime()),
        sa.UniqueConstraint("plugin_id", "event_key", name="uq_plugin_deliveries_event"),
    )
    op.create_index("ix_plugin_deliveries_plugin_id", "plugin_deliveries", ["plugin_id"])
    op.create_index("ix_plugin_deliveries_status", "plugin_deliveries", ["status"])
    op.create_index("ix_plugin_deliveries_next_attempt_at", "plugin_deliveries", ["next_attempt_at"])
    op.create_table(
        "plugin_event_cursors",
        sa.Column("source", sa.String(32), primary_key=True),
        sa.Column("last_id", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade():
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT 1 FROM plugin_installs LIMIT 1")).first():
        raise RuntimeError("Installed plugins exist; uninstall them before downgrading")
    op.drop_table("plugin_event_cursors")
    op.drop_table("plugin_deliveries")
    op.drop_table("plugin_installs")
    op.drop_table("plugin_packages")
    op.drop_table("plugin_publishers")
