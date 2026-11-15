"""External helpdesk bridge (Zendesk/Freshdesk): sync cursor per provider and external id links."""
from alembic import op
import sqlalchemy as sa
revision='0008'
down_revision='0007'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('helpdesk_state',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('provider',sa.String(20),nullable=False),
        sa.Column('cursor',sa.Text(),nullable=False,server_default=''),
        sa.Column('last_success',sa.DateTime(timezone=True)),
        sa.Column('last_error_at',sa.DateTime(timezone=True)),
        sa.Column('paused_until',sa.DateTime(timezone=True)),
        sa.Column('error',sa.String(500),nullable=False,server_default=''),
        sa.Column('imported_tickets',sa.Integer(),nullable=False,server_default='0'),
        sa.Column('imported_comments',sa.Integer(),nullable=False,server_default='0'),
        sa.UniqueConstraint('provider',name='uq_helpdesk_state_provider'))
    op.create_table('helpdesk_links',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('provider',sa.String(20),nullable=False),
        sa.Column('kind',sa.String(10),nullable=False),
        sa.Column('external_id',sa.String(64),nullable=False),
        sa.Column('ticket_id',sa.Integer(),sa.ForeignKey('tickets.id',ondelete='CASCADE'),nullable=False),
        sa.Column('message_row_id',sa.Integer(),sa.ForeignKey('messages.id',ondelete='SET NULL')),
        sa.Column('erased',sa.Boolean(),nullable=False,server_default=sa.false()),
        sa.Column('created_at',sa.DateTime(timezone=True)),
        sa.UniqueConstraint('provider','kind','external_id',name='uq_helpdesk_links_external'))
    op.create_index('ix_helpdesk_links_ticket_id','helpdesk_links',['ticket_id'])

def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM tickets WHERE channel IN ('zendesk','freshdesk') LIMIT 1")).first():
        raise RuntimeError('Helpdesk tickets exist; downgrade would re-import them as duplicates')
    op.drop_index('ix_helpdesk_links_ticket_id',table_name='helpdesk_links')
    op.drop_table('helpdesk_links')
    op.drop_table('helpdesk_state')
