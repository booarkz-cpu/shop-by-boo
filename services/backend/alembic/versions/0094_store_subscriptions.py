"""v28.89.0: subscriptions bought in Google Play and App Store (BACKLOG A5).

A row links the store's subscription (Apple ``originalTransactionId`` or the SHA-256 of Google's purchase token) to the
shop customer, the shop subscription and the plan, so renewals and refunds from the stores' notifications reach the
right customer."""
from alembic import op
import sqlalchemy as sa

revision = "0094_store_subscriptions"
down_revision = "0093_ssh_key_rotation"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "store_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("chain_key", sa.String(255), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("subscription_id", sa.Integer()),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.String(255), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="active"),
        sa.Column("last_order_id", sa.String(255)),
        sa.Column("expires_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("provider", "chain_key", name="uq_store_subscription_chain"),
    )
    op.create_index("ix_store_subscriptions_user_id", "store_subscriptions", ["user_id"])


def downgrade():
    op.drop_index("ix_store_subscriptions_user_id", table_name="store_subscriptions")
    op.drop_table("store_subscriptions")
