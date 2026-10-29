"""v28.51: loyalty levels reached by customers (loyalty.py)."""
from alembic import op
import sqlalchemy as sa

revision = "0085_loyalty"
down_revision = "0084_subscription_freeze"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "loyalty_members",
        sa.Column("user_id", sa.Integer, primary_key=True, autoincrement=False),
        sa.Column("level", sa.String(24), nullable=False),
        sa.Column("reached_at", sa.DateTime, nullable=False),
    )


def downgrade():
    # Re-creatable: the next loyalty pass computes every level again (bonus days are kept once by their job keys).
    op.drop_table("loyalty_members")
