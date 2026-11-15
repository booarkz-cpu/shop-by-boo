"""Canonical shop conversation links and durable scan progress."""
from alembic import op
import sqlalchemy as sa
revision='0005'
down_revision='0004'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('tickets',sa.Column('shop_import_until_id',sa.Integer(),nullable=True))
    op.add_column('tickets',sa.Column('shop_import_complete',sa.Boolean(),nullable=False,server_default=sa.false()))
    op.add_column('tickets',sa.Column('shop_ticket_id',sa.Integer(),nullable=True))
    op.add_column('tickets',sa.Column('shop_last_message_id',sa.Integer(),nullable=False,server_default='0'))
    op.add_column('tickets',sa.Column('shop_initial_loaded',sa.Boolean(),nullable=False,server_default=sa.false()))
    op.create_index('uq_tickets_shop_ticket','tickets',['shop_ticket_id'],unique=True)
    op.add_column('attachments',sa.Column('shop_attachment_id',sa.Integer(),nullable=True))
    op.create_index('uq_attachments_shop_id','attachments',['shop_attachment_id'],unique=True)
    op.create_table('shop_sync_state',sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('origin',sa.String(1000),nullable=False),sa.Column('instance',sa.String(40),nullable=False),
        sa.Column('after_id',sa.Integer(),nullable=False,server_default='0'),
        sa.Column('last_success',sa.DateTime(timezone=True)),sa.Column('error',sa.String(500),nullable=False,server_default=''))

    op.execute("INSERT INTO shop_sync_state (id,origin,instance,after_id,error) VALUES (1,'','',0,'')")

def downgrade():
    # Removing links while replies are still queued would reroute them to Telegram.
    n=op.get_bind().execute(sa.text("SELECT count(*) FROM tickets WHERE shop_ticket_id IS NOT NULL")).scalar()
    if n:raise RuntimeError('Shop-linked tickets exist; archive or reconcile them before downgrading the bridge')
    op.drop_table('shop_sync_state')
    op.drop_index('uq_attachments_shop_id',table_name='attachments');op.drop_column('attachments','shop_attachment_id')
    op.drop_index('uq_tickets_shop_ticket',table_name='tickets')
    for name in ('shop_initial_loaded','shop_last_message_id','shop_ticket_id','shop_import_complete','shop_import_until_id'):op.drop_column('tickets',name)
