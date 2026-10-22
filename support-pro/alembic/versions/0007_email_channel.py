"""Email support channel: IMAP cursor, Message-ID links and unique channel identities."""
from alembic import op
import sqlalchemy as sa
revision='0007'
down_revision='0006'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('email_channel_state',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('uidvalidity',sa.BigInteger(),nullable=False,server_default='0'),
        sa.Column('last_uid',sa.BigInteger(),nullable=False,server_default='0'),
        sa.Column('stuck_uid',sa.BigInteger(),nullable=False,server_default='0'),
        sa.Column('stuck_attempts',sa.Integer(),nullable=False,server_default='0'),
        sa.Column('last_success',sa.DateTime(timezone=True)),
        sa.Column('last_error_at',sa.DateTime(timezone=True)),
        sa.Column('error',sa.String(500),nullable=False,server_default=''),
        sa.Column('received',sa.Integer(),nullable=False,server_default='0'),
        sa.Column('skipped',sa.Integer(),nullable=False,server_default='0'))
    op.create_table('email_links',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('message_id_hash',sa.String(64),nullable=False),
        sa.Column('message_id',sa.String(255),nullable=False),
        sa.Column('direction',sa.String(3),nullable=False),
        sa.Column('ticket_id',sa.Integer(),sa.ForeignKey('tickets.id',ondelete='CASCADE'),nullable=False),
        sa.Column('message_row_id',sa.Integer(),sa.ForeignKey('messages.id',ondelete='SET NULL')),
        sa.Column('auth',sa.String(10),nullable=False,server_default='none'),
        sa.Column('created_at',sa.DateTime(timezone=True)),
        sa.UniqueConstraint('message_id_hash',name='uq_email_links_message_id_hash'))
    op.create_index('ix_email_links_ticket_id','email_links',['ticket_id'])
    # Earlier releases never wrote channel identities; keep the newest row if any duplicates exist.
    op.execute("DELETE FROM channel_identities WHERE id NOT IN (SELECT max(id) FROM channel_identities GROUP BY channel, external_id)")
    with op.batch_alter_table('channel_identities') as batch:
        batch.create_unique_constraint('uq_channel_identity_external',['channel','external_id'])

def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM tickets WHERE channel='email' LIMIT 1")).first():
        raise RuntimeError('Email tickets exist; downgrade would orphan their threading history')
    with op.batch_alter_table('channel_identities') as batch:
        batch.drop_constraint('uq_channel_identity_external',type_='unique')
    op.drop_index('ix_email_links_ticket_id',table_name='email_links')
    op.drop_table('email_links')
    op.drop_table('email_channel_state')
