"""Private binary attachments in the shared support conversation."""
from alembic import op
import sqlalchemy as sa
revision='0047_support_attachments'
down_revision='0046_gift_snapshots'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('support_attachments',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('ticket_id',sa.Integer(),sa.ForeignKey('support_tickets.id',ondelete='CASCADE'),nullable=False),
        sa.Column('message_id',sa.Integer(),sa.ForeignKey('support_messages.id',ondelete='CASCADE'),nullable=True),
        sa.Column('actor',sa.String(350),nullable=False),sa.Column('idempotency_key',sa.String(128),nullable=False),
        sa.Column('name',sa.String(180),nullable=False),sa.Column('mime',sa.String(64),nullable=False),
        sa.Column('data',sa.LargeBinary(),nullable=False),sa.Column('size',sa.Integer(),nullable=False),
        sa.Column('sha256',sa.String(64),nullable=False),sa.Column('created_at',sa.DateTime(),nullable=False,server_default=sa.func.now()),
        sa.UniqueConstraint('ticket_id','actor','idempotency_key',name='uq_support_attachment_retry'))
    op.create_index('ix_support_attachments_ticket_id','support_attachments',['ticket_id'])
    op.create_index('ix_support_attachments_message_id','support_attachments',['message_id'])

def downgrade():op.drop_table('support_attachments')
