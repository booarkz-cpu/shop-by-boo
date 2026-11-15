"""Keep machine delivery identity when canonical support messages move."""
from alembic import op
import sqlalchemy as sa
revision='0062_support_delivery_identity'
down_revision='0061_menu_hierarchy'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('support_tickets',sa.Column('topology_version',sa.Integer(),nullable=False,server_default='0'))
    op.add_column('support_messages',sa.Column('delivery_key',sa.String(128)))
    op.execute('UPDATE support_messages SET delivery_key=idempotency_key WHERE idempotency_key IS NOT NULL')

def downgrade():
    if op.get_bind().dialect.name=='postgresql':op.execute('LOCK TABLE support_tickets,support_messages IN ACCESS EXCLUSIVE MODE')
    moved=op.get_bind().execute(sa.text('SELECT 1 FROM support_messages WHERE delivery_key IS NOT NULL AND (idempotency_key IS NULL OR delivery_key<>idempotency_key) LIMIT 1')).first()
    changed=op.get_bind().execute(sa.text('SELECT 1 FROM support_tickets WHERE topology_version<>0 LIMIT 1')).first()
    if moved or changed:raise RuntimeError('Moved support delivery identities prevent downgrade')
    op.drop_column('support_messages','delivery_key')
    op.drop_column('support_tickets','topology_version')
