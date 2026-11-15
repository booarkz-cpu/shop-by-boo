"""Torrent detection: hourly per-client counts from the Xray access log, without destinations."""
from alembic import op
import sqlalchemy as sa

revision = "0071_torrent_detection"
down_revision = "0070_node_terminal"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "torrent_detections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("hour", sa.DateTime(), nullable=False),
        sa.Column("agent_id", sa.Integer(), nullable=False),
        sa.Column("client", sa.String(128), nullable=False),
        sa.Column("user_id", sa.Integer()),
        sa.Column("events", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("hour", "agent_id", "client", name="uq_torrent_detections_bucket"),
    )
    op.create_index("ix_torrent_detections_hour", "torrent_detections", ["hour"])
    op.create_index("ix_torrent_detections_agent_id", "torrent_detections", ["agent_id"])
    op.create_index("ix_torrent_detections_user_id", "torrent_detections", ["user_id"])


def downgrade():
    # Counters only, kept for at most 30 days and re-collected from new traffic.
    op.drop_table("torrent_detections")
