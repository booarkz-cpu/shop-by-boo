"""Immutable legacy support import identities."""
from alembic import op
import sqlalchemy as sa
revision='0048_support_bridge'
down_revision='0047_support_attachments'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('support_import_links',sa.Column('source_key',sa.String(80),primary_key=True),sa.Column('completed',sa.Boolean(),nullable=False,server_default=sa.false()),
        sa.Column('ticket_id',sa.Integer(),sa.ForeignKey('support_tickets.id',ondelete='CASCADE'),nullable=False,unique=True))

    op.create_index('ix_support_tickets_updated','support_tickets',['updated_at','id'])

def downgrade():
    if op.get_bind().execute(sa.text('SELECT count(*) FROM support_import_links')).scalar():
        raise RuntimeError('Imported support links exist; downgrade would lose retry identities')
    op.drop_index('ix_support_tickets_updated',table_name='support_tickets')
    op.drop_table('support_import_links')
