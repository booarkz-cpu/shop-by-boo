"""Support Pro 3.0. Existing messages retain an honest unknown delivery state."""
from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    changes = {
        'operators': [sa.Column('available', sa.Boolean, nullable=False, server_default=sa.true()),
                      sa.Column('capacity', sa.Integer, nullable=False, server_default='20'),
                      sa.Column('auth_version', sa.Integer, nullable=False, server_default='1'),
                      sa.Column('last_totp_step', sa.BigInteger, nullable=False, server_default='0')],
        'tickets': [sa.Column(x, sa.DateTime(timezone=True)) for x in
                    ('first_response_due', 'first_response_at', 'closed_at', 'waiting_since')] + [
                    sa.Column('last_customer_message_id', sa.Integer, nullable=False, server_default='0'),
                    sa.Column('rating', sa.Integer),
                    sa.Column('rating_requested', sa.Boolean, nullable=False, server_default=sa.false())],
        'messages': [sa.Column('operator_id', sa.Integer), sa.Column('delivery_state', sa.String(30), nullable=False, server_default='legacy'),
                     sa.Column('source_key', sa.String(160)), sa.Column('attempts', sa.Integer, nullable=False, server_default='0'),
                     sa.Column('next_attempt_at', sa.DateTime(timezone=True)), sa.Column('claimed_at', sa.DateTime(timezone=True)),
                     sa.Column('error', sa.Text, nullable=False, server_default=''),
                     sa.Column('text_sent', sa.Boolean, nullable=False, server_default=sa.false()),
                     sa.Column('attachment_sent', sa.Boolean, nullable=False, server_default=sa.false()),
                     sa.Column('telegram_message_id', sa.BigInteger), sa.Column('sent_at', sa.DateTime(timezone=True))],
        'attachments': [sa.Column('state', sa.String(30), nullable=False, server_default='ready'),
                        sa.Column('error', sa.Text, nullable=False, server_default='')],
    }
    for table, columns in changes.items():
        with op.batch_alter_table(table) as batch:
            for column in columns:
                batch.add_column(column)
            if table == 'messages':
                batch.create_foreign_key('fk_messages_operator', 'operators', ['operator_id'], ['id'])
                batch.create_unique_constraint('uq_messages_source_key', ['source_key'])
                batch.create_index('ix_messages_delivery_state', ['delivery_state'])
    op.create_table('clients', sa.Column('telegram_user_id', sa.BigInteger, primary_key=True, autoincrement=False),
                    sa.Column('full_name', sa.String(255), nullable=False, server_default=''),
                    sa.Column('username', sa.String(255), nullable=False, server_default=''),
                    sa.Column('tags', sa.String(500), nullable=False, server_default=''),
                    sa.Column('notes', sa.Text, nullable=False, server_default=''),
                    sa.Column('current_ticket_id', sa.Integer))
    op.create_table('ticket_reads', sa.Column('id', sa.Integer, primary_key=True),
                    sa.Column('ticket_id', sa.Integer, sa.ForeignKey('tickets.id'), nullable=False),
                    sa.Column('operator_id', sa.Integer, sa.ForeignKey('operators.id'), nullable=False),
                    sa.Column('last_message_id', sa.Integer, nullable=False, server_default='0'),
                    sa.UniqueConstraint('ticket_id', 'operator_id'))
    op.create_table('notifications', sa.Column('id', sa.Integer, primary_key=True),
                    sa.Column('operator_id', sa.Integer, sa.ForeignKey('operators.id'), nullable=False),
                    sa.Column('ticket_id', sa.Integer, sa.ForeignKey('tickets.id'), nullable=False),
                    sa.Column('text', sa.String(500), nullable=False), sa.Column('dedupe_key', sa.String(200), unique=True),
                    sa.Column('seen', sa.Boolean, nullable=False, server_default=sa.false()),
                    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index('ix_notifications_operator_id', 'notifications', ['operator_id'])
    op.create_table('settings', sa.Column('id', sa.Integer, primary_key=True), sa.Column('data', sa.JSON, nullable=False))
    op.execute("UPDATE messages SET delivery_state='received' WHERE sender='user'")
    op.execute("UPDATE tickets SET last_customer_message_id=COALESCE((SELECT MAX(id) FROM messages WHERE ticket_id=tickets.id AND sender='user'),0)")
    op.execute("UPDATE tickets SET waiting_since=updated_at WHERE status IN ('new','open')")
    op.execute("UPDATE tickets SET closed_at=updated_at WHERE status='closed'")
    op.execute("INSERT INTO clients(telegram_user_id,full_name,username,tags,notes) SELECT t.telegram_user_id,COALESCE(t.full_name,''),COALESCE(t.username,''),'','' FROM tickets t WHERE t.id=(SELECT MAX(t2.id) FROM tickets t2 WHERE t2.telegram_user_id=t.telegram_user_id)")


def downgrade():
    raise RuntimeError('Downgrade removes operational history. Restore the pre-upgrade backup instead.')
