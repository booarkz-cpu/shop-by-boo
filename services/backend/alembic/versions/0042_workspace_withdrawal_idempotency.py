"""Preserve one referral withdrawal across retries from customer interfaces."""
from alembic import op
import sqlalchemy as sa

revision = "0042_workspace_withdrawals"
down_revision = "0041_enable_platform_modules"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("withdrawal_requests", sa.Column("idempotency_key", sa.String(128), nullable=True))
    op.create_unique_constraint("uq_withdrawal_user_idempotency", "withdrawal_requests", ["user_id", "idempotency_key"])


def downgrade():
    op.drop_constraint("uq_withdrawal_user_idempotency", "withdrawal_requests", type_="unique")
    op.drop_column("withdrawal_requests", "idempotency_key")
