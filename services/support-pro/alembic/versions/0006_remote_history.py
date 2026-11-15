"""Stable remote message identity and durable history rescan state."""
from alembic import op
import sqlalchemy as sa
import re
revision='0006'
down_revision='0005'
branch_labels=None
depends_on=None

def upgrade():
    for name in ('shop_user_id','shop_merged_into_id'):op.add_column('tickets',sa.Column(name,sa.Integer()))
    for name in ('shop_history_version','shop_scan_version'):op.add_column('tickets',sa.Column(name,sa.String(80),nullable=False,server_default=''))
    op.add_column('tickets',sa.Column('shop_scan_after_id',sa.Integer(),nullable=False,server_default='0'))
    op.add_column('messages',sa.Column('shop_message_id',sa.Integer()))
    op.execute('UPDATE tickets SET shop_user_id=-telegram_user_id WHERE shop_ticket_id IS NOT NULL AND telegram_user_id<0')
    # Prefer the newest existing mirror when old topology already made duplicate
    # local copies. Preserve the earlier copies as history; never delete messages.
    seen=set()
    rows=op.get_bind().execute(sa.text("SELECT id,source_key FROM messages WHERE source_key LIKE 'shop:%' ORDER BY id DESC")).all()
    for mid,key in rows:
        match=re.fullmatch(r'shop:[0-9]+:([1-9][0-9]*)',key or '')
        if match and int(match[1]) not in seen:
            identifier=int(match[1]);seen.add(identifier)
            op.get_bind().execute(sa.text('UPDATE messages SET shop_message_id=:remote WHERE id=:mid'),{'remote':identifier,'mid':mid})
    op.create_index('uq_message_shop_identity','messages',['shop_message_id'],unique=True)
    op.execute('UPDATE tickets SET shop_initial_loaded=false,shop_last_message_id=0 WHERE shop_ticket_id IS NOT NULL')

def downgrade():
    if op.get_bind().dialect.name=='postgresql':op.execute('LOCK TABLE tickets,messages IN ACCESS EXCLUSIVE MODE')
    active=op.get_bind().execute(sa.text("SELECT 1 FROM tickets WHERE shop_merged_into_id IS NOT NULL OR shop_history_version<>'' OR shop_scan_version<>'' LIMIT 1")).first()
    if active:raise RuntimeError('Remote history mappings prevent downgrade')
    op.drop_index('uq_message_shop_identity',table_name='messages');op.drop_column('messages','shop_message_id')
    for name in ('shop_scan_after_id','shop_scan_version','shop_history_version','shop_merged_into_id','shop_user_id'):op.drop_column('tickets',name)
