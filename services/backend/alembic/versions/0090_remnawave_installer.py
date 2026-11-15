"""v28.66: Remnawave installation wizard (stage 10) — server registry, installations and their steps.

See docs/ru/new/REMNAWAVE_DATA_MODEL.md. The SSH secret and the generated panel secrets are stored encrypted."""
from alembic import op
import sqlalchemy as sa

revision = "0090_remnawave_installer"
down_revision = "0089_index_cleanup"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "remnawave_servers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False, unique=True),
        sa.Column("host", sa.String(255), nullable=False),
        sa.Column("ssh_port", sa.Integer(), nullable=False, server_default="22"),
        sa.Column("ssh_user", sa.String(64), nullable=False),
        sa.Column("auth_method", sa.String(16), nullable=False),
        sa.Column("ssh_secret", sa.Text(), nullable=False),
        sa.Column("host_key_fingerprint", sa.String(64), nullable=False),
        sa.Column("roles", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="new"),
        sa.Column("os", sa.String(64)),
        sa.Column("arch", sa.String(32)),
        sa.Column("cpu_cores", sa.Integer()),
        sa.Column("ram_mb", sa.Integer()),
        sa.Column("disk_gb", sa.Integer()),
        sa.Column("preflight", sa.JSON()),
        sa.Column("last_checked_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "remnawave_installations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("action", sa.String(16), nullable=False, server_default="install"),
        sa.Column("mode", sa.String(32), nullable=False),
        sa.Column("server_ids", sa.JSON(), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("plan", sa.JSON(), nullable=False),
        sa.Column("plan_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="planned"),
        sa.Column("secrets", sa.Text()),
        sa.Column("result", sa.JSON()),
        sa.Column("error", sa.Text()),
        sa.Column("created_by", sa.String(320), nullable=False),
        sa.Column("approved_by", sa.String(320)),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("source_installation_id", sa.Integer()),
        sa.Column("worker_id", sa.String(128)),
        sa.Column("heartbeat_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime()),
        sa.Column("finished_at", sa.DateTime()),
    )
    op.create_index("ix_remnawave_installations_status", "remnawave_installations", ["status"])
    op.create_table(
        "remnawave_deployment_steps",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("installation_id", sa.Integer(), sa.ForeignKey("remnawave_installations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("server_id", sa.Integer()),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(48), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("log_tail", sa.Text()),
        sa.Column("started_at", sa.DateTime()),
        sa.Column("finished_at", sa.DateTime()),
    )
    op.create_index("ix_remnawave_deployment_steps_installation_id", "remnawave_deployment_steps", ["installation_id"])


def downgrade():
    op.drop_index("ix_remnawave_deployment_steps_installation_id", table_name="remnawave_deployment_steps")
    op.drop_table("remnawave_deployment_steps")
    op.drop_index("ix_remnawave_installations_status", table_name="remnawave_installations")
    op.drop_table("remnawave_installations")
    op.drop_table("remnawave_servers")
