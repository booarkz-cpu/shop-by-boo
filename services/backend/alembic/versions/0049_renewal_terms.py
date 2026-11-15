"""Preserve constructor renewal choices independently of mutable plan defaults."""
from alembic import op
import sqlalchemy as sa
revision='0049_renewal_terms'
down_revision='0048_support_bridge'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('subscriptions',sa.Column('renewal_terms',sa.JSON(),nullable=True))

def downgrade():
    if op.get_bind().execute(sa.text('SELECT count(*) FROM subscriptions WHERE renewal_terms IS NOT NULL')).scalar():
        raise RuntimeError('Renewal snapshots exist; restore a coordinated backup instead of losing purchased choices')
    op.drop_column('subscriptions','renewal_terms')
