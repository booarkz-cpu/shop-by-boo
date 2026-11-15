"""Traffic analysis: detection kind per counter (Xray routing, built-in classifier, nDPI, heuristic)."""
from alembic import op
import sqlalchemy as sa

revision = "0072_traffic_analysis"
down_revision = "0071_torrent_detection"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("torrent_detections") as batch:
        batch.add_column(sa.Column("kind", sa.String(16), nullable=False, server_default="xray"))
        batch.drop_constraint("uq_torrent_detections_bucket", type_="unique")
        batch.create_unique_constraint("uq_torrent_detections_bucket_kind", ["hour", "agent_id", "client", "kind"])


def downgrade():
    # Counters only: rows of other kinds would collide in the old bucket, so they go.
    op.execute("DELETE FROM torrent_detections WHERE kind <> 'xray'")
    with op.batch_alter_table("torrent_detections") as batch:
        batch.drop_constraint("uq_torrent_detections_bucket_kind", type_="unique")
        batch.create_unique_constraint("uq_torrent_detections_bucket", ["hour", "agent_id", "client"])
        batch.drop_column("kind")
