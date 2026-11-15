"""Snapshot and safely apply tariff changes and traffic purchases."""
from alembic import op
import sqlalchemy as sa
revision = "0044_subscription_commerce"
down_revision = "0043_support_conversations"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("subscriptions",sa.Column("unit_price_per_day",sa.Numeric(18,8),nullable=True))
    op.create_table("traffic_packages",sa.Column("id",sa.Integer(),primary_key=True),
        sa.Column("name",sa.String(255),nullable=False),sa.Column("traffic_gb",sa.Integer(),nullable=False),
        sa.Column("price",sa.Numeric(12,2),nullable=False),sa.Column("plan_id",sa.Integer(),nullable=True),
        sa.Column("enabled",sa.Boolean(),nullable=False,server_default=sa.true()),
        sa.Column("sort_order",sa.Integer(),nullable=False,server_default="0"))
    op.create_table("entitlement_quotes",sa.Column("id",sa.String(64),primary_key=True),
        sa.Column("user_id",sa.Integer(),nullable=False),sa.Column("subscription_id",sa.Integer(),nullable=False),
        sa.Column("kind",sa.String(32),nullable=False),sa.Column("amount",sa.Numeric(12,2),nullable=False),
        sa.Column("currency",sa.String(3),nullable=False),sa.Column("before",sa.JSON(),nullable=False),
        sa.Column("after",sa.JSON(),nullable=False),sa.Column("expires_at",sa.DateTime(),nullable=False),
        sa.Column("created_at",sa.DateTime(),nullable=False))
    op.create_index("ix_entitlement_quotes_user_id","entitlement_quotes",["user_id"])
    op.create_table("entitlement_operations",sa.Column("id",sa.Integer(),primary_key=True),
        sa.Column("quote_id",sa.String(64),nullable=False,unique=True),sa.Column("payment_id",sa.Integer(),nullable=False,unique=True),
        sa.Column("user_id",sa.Integer(),nullable=False),sa.Column("subscription_id",sa.Integer(),nullable=False),
        sa.Column("kind",sa.String(32),nullable=False),sa.Column("before",sa.JSON(),nullable=False),sa.Column("after",sa.JSON(),nullable=False),
        sa.Column("status",sa.String(32),nullable=False,server_default="queued"),sa.Column("error",sa.Text()),
        sa.Column("created_at",sa.DateTime(),nullable=False),sa.Column("completed_at",sa.DateTime()))
    op.create_index("ix_entitlement_operations_user_id","entitlement_operations",["user_id"])
    op.create_index("ix_entitlement_operations_subscription_id","entitlement_operations",["subscription_id"])

def downgrade():
    op.drop_table("entitlement_operations")
    op.drop_table("entitlement_quotes")
    op.drop_table("traffic_packages")
    op.drop_column("subscriptions","unit_price_per_day")
