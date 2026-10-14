"""Add typed, versioned runtime settings with encrypted change payloads."""

from alembic import op
import sqlalchemy as sa


revision = "0064_runtime_settings"
down_revision = "0063_account_merge"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "runtime_setting_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.execute(
        sa.text(
            "INSERT INTO runtime_setting_state (id, version, updated_at) "
            "VALUES (1, 0, CURRENT_TIMESTAMP)"
        )
    )
    op.create_table(
        "runtime_setting_changes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("base_version", sa.Integer(), nullable=False),
        sa.Column("target_version", sa.Integer()),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("keys", sa.JSON(), nullable=False),
        sa.Column("payload_encrypted", sa.Text(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("actor", sa.String(320), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("source_change_id", sa.String(36)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("applied_at", sa.DateTime()),
        sa.ForeignKeyConstraint(
            ["source_change_id"],
            ["runtime_setting_changes.id"],
            name="fk_runtime_setting_change_source",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("fingerprint", name="uq_runtime_setting_change_fingerprint"),
    )
    op.create_index(
        "ix_runtime_setting_changes_status",
        "runtime_setting_changes",
        ["status"],
    )


def downgrade():
    history = op.get_bind().execute(
        sa.text("SELECT 1 FROM runtime_setting_changes LIMIT 1")
    ).first()
    if history:
        raise RuntimeError("Runtime setting history prevents downgrade")
    op.drop_index(
        "ix_runtime_setting_changes_status",
        table_name="runtime_setting_changes",
    )
    op.drop_table("runtime_setting_changes")
    op.drop_table("runtime_setting_state")
