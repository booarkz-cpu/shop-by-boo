"""v28.47: customers subscribed to outage news of the public status page."""
from alembic import op
import sqlalchemy as sa

revision = "0082_status_subscribers"
down_revision = "0081_subscription_proxy"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "status_subscribers",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )


def downgrade():
    op.drop_table("status_subscribers")
