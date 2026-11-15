"""v19 Corgi Commerce marketplace and reseller foundation."""
from alembic import op
import sqlalchemy as sa

revision = "0039_v19_marketplace"
down_revision = "0038_v2_6_0_platform"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("payments", sa.Column("reseller_id", sa.Integer(), nullable=True))
    op.create_index("ix_payments_reseller_id", "payments", ["reseller_id"])
    op.create_table(
        "resellers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("api_key_hash", sa.String(128), nullable=False),
        sa.Column("commission_percent", sa.Numeric(5, 2), nullable=False, server_default="20"),
        sa.Column("plan_ids", sa.JSON(), nullable=True),
        sa.Column("branding", sa.JSON(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_resellers_slug", "resellers", ["slug"], unique=True)
    op.create_index("ix_resellers_api_key_hash", "resellers", ["api_key_hash"], unique=True)

def downgrade():
    op.drop_index("ix_payments_reseller_id", table_name="payments")
    op.drop_column("payments", "reseller_id")
    op.drop_index("ix_resellers_api_key_hash", table_name="resellers")
    op.drop_index("ix_resellers_slug", table_name="resellers")
    op.drop_table("resellers")
