"""v28.67: Domain Manager (stage 11) — domains of the subscription portal, Remnawave panels and nodes.

See docs/ru/new/SUBSCRIPTION_DOMAIN.md. Only checks and their results; certificates live in Caddy's storage."""
from alembic import op
import sqlalchemy as sa

revision = "0091_remnawave_domains"
down_revision = "0090_remnawave_installer"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "remnawave_domains",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("domain", sa.String(253), nullable=False, unique=True),
        sa.Column("purpose", sa.String(24), nullable=False),
        sa.Column("served_by", sa.String(16), nullable=False),
        sa.Column("server_id", sa.Integer()),
        sa.Column("expected_ip", sa.String(64)),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("dns_status", sa.String(16), nullable=False, server_default="unknown"),
        sa.Column("dns_records", sa.JSON()),
        sa.Column("dns_checked_at", sa.DateTime()),
        sa.Column("cert_status", sa.String(16), nullable=False, server_default="unknown"),
        sa.Column("cert_issuer", sa.String(200)),
        sa.Column("cert_expires_at", sa.DateTime()),
        sa.Column("cert_checked_at", sa.DateTime()),
        sa.Column("http_status", sa.Integer()),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_by", sa.String(320), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade():
    op.drop_table("remnawave_domains")
