"""v28.50: pauses of paid subscriptions (subscription_freeze.py)."""
from alembic import op
import sqlalchemy as sa

revision = "0084_subscription_freeze"
down_revision = "0083_corporate_seats"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "subscription_freezes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("subscription_id", sa.Integer, nullable=False),
        sa.Column("user_id", sa.Integer, nullable=False),
        sa.Column("started_at", sa.DateTime, nullable=False),
        sa.Column("until", sa.DateTime, nullable=False),
        sa.Column("days", sa.Integer, nullable=False),
        sa.Column("expires_before", sa.DateTime),
        sa.Column("ended_at", sa.DateTime),
    )
    op.create_index("ix_subscription_freezes_subscription_id", "subscription_freezes", ["subscription_id"])
    op.create_index("ix_subscription_freezes_user_id", "subscription_freezes", ["user_id"])
    op.create_index("ix_subscription_freezes_until", "subscription_freezes", ["until"])


def downgrade():
    # A frozen subscription keeps its paid days only through this table: refuse while a freeze is running.
    if op.get_bind().execute(sa.text("SELECT 1 FROM subscription_freezes WHERE ended_at IS NULL LIMIT 1")).first():
        raise RuntimeError("Есть замороженные подписки: разморозьте их перед откатом миграции 0084")
    op.drop_table("subscription_freezes")
