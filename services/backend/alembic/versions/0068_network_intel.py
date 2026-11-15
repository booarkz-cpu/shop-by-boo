"""Network intelligence cache: ASN/registry and reputation per IP with freshness and source rate limits."""
from alembic import op
import sqlalchemy as sa

revision = "0068_network_intel"
down_revision = "0067_plugin_runtime"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "network_intel",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ip", sa.String(45), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("data", sa.JSON()),
        sa.Column("fetched_at", sa.DateTime()),
        sa.Column("expires_at", sa.DateTime()),
        sa.Column("error", sa.String(255)),
        sa.Column("error_at", sa.DateTime()),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime()),
        sa.UniqueConstraint("ip", "source", name="uq_network_intel_ip_source"),
    )
    op.create_index("ix_network_intel_ip", "network_intel", ["ip"])
    op.create_index("ix_network_intel_expires_at", "network_intel", ["expires_at"])
    op.create_table(
        "network_intel_sources",
        sa.Column("source", sa.String(16), primary_key=True),
        sa.Column("window_start", sa.DateTime()),
        sa.Column("used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("blocked_until", sa.DateTime()),
        sa.Column("last_error", sa.String(255)),
    )


def downgrade():
    # Cache only: every row can be fetched again from the sources.
    op.drop_table("network_intel_sources")
    op.drop_table("network_intel")
