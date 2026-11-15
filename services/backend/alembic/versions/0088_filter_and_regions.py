"""v28.54: the ad / children's filter of a subscription and the region of a VPN session."""
from alembic import op
import sqlalchemy as sa

revision = "0088_filter_and_regions"
down_revision = "0087_speed_tests"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("subscriptions", sa.Column("dns_filter", sa.String(8)))
    op.add_column("vpn_sessions", sa.Column("region", sa.String(64), nullable=False, server_default=""))


def downgrade():
    # The squads of filtered customers stay in the panel; the shop forgets only the choice and the regions.
    op.drop_column("vpn_sessions", "region")
    op.drop_column("subscriptions", "dns_filter")
