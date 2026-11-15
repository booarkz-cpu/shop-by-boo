"""v28.53: speed measurements from the apps (speed_test.py)."""
from alembic import op
import sqlalchemy as sa

revision = "0087_speed_tests"
down_revision = "0086_feedback"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "speed_tests",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, nullable=False),
        sa.Column("server", sa.String(120), nullable=False),
        sa.Column("vpn", sa.Boolean, nullable=False),
        sa.Column("download_mbps", sa.Numeric(10, 2), nullable=False),
        sa.Column("ping_ms", sa.Integer),
        sa.Column("network", sa.String(16)),
        sa.Column("platform", sa.String(16)),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_speed_tests_user_id", "speed_tests", ["user_id"])
    op.create_index("ix_speed_tests_created_at", "speed_tests", ["created_at"])


def downgrade():
    # 30-day measurements: re-collected by the apps.
    op.drop_table("speed_tests")
