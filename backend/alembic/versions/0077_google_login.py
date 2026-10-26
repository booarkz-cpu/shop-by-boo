"""Google sign-in for the apps and the cabinet: users.google_id and its merge alias."""
from alembic import op
import sqlalchemy as sa

revision = "0077_google_login"
down_revision = "0076_growth"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("google_id", sa.String(255), nullable=True))
        batch.create_index("ix_users_google_id", ["google_id"], unique=True)
    with op.batch_alter_table("account_merge_aliases") as batch:
        batch.add_column(sa.Column("google_id", sa.String(255), nullable=True))
        batch.create_index("ix_account_merge_aliases_google_id", ["google_id"], unique=True)


def downgrade():
    with op.batch_alter_table("account_merge_aliases") as batch:
        batch.drop_index("ix_account_merge_aliases_google_id")
        batch.drop_column("google_id")
    with op.batch_alter_table("users") as batch:
        batch.drop_index("ix_users_google_id")
        batch.drop_column("google_id")
