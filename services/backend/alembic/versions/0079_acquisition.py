"""Where a customer came from: users.acquisition_source (first touch: bot /start src_…, cabinet ?utm_source=…)."""
from alembic import op
import sqlalchemy as sa

revision = "0079_acquisition"
down_revision = "0078_campaign_ab"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("acquisition_source", sa.String(48)))
    op.create_index("ix_users_acquisition_source", "users", ["acquisition_source"])


def downgrade():
    op.drop_index("ix_users_acquisition_source", table_name="users")
    op.drop_column("users", "acquisition_source")
