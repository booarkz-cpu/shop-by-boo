"""Journaled support merge and split with source redirect metadata."""
from alembic import op
import sqlalchemy as sa

revision = '0056_support_topology'
down_revision = '0055_customer_passkeys'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('support_tickets', sa.Column('merged_into_id', sa.Integer()))
    op.create_foreign_key('fk_support_merged_into', 'support_tickets', 'support_tickets', ['merged_into_id'], ['id'], ondelete='RESTRICT')
    op.create_index('ix_support_tickets_merged_into_id', 'support_tickets', ['merged_into_id'])
    op.create_table('support_topology_operations',
        sa.Column('key', sa.String(64), primary_key=True),
        sa.Column('fingerprint', sa.String(64), nullable=False),
        sa.Column('result', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False))


def downgrade():
    if op.get_bind().dialect.name == 'postgresql':
        op.execute('LOCK TABLE support_topology_operations, support_tickets IN ACCESS EXCLUSIVE MODE')
    if op.get_bind().execute(sa.text('SELECT 1 FROM support_topology_operations LIMIT 1')).first():
        raise RuntimeError('Support topology history cannot be discarded by downgrade')
    op.drop_table('support_topology_operations')
    op.drop_index('ix_support_tickets_merged_into_id', 'support_tickets')
    op.drop_constraint('fk_support_merged_into', 'support_tickets', type_='foreignkey')
    op.drop_column('support_tickets', 'merged_into_id')
