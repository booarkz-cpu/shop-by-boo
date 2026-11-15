"""Teams, durable outbox, sessions, portal and incidents."""
from alembic import op
import sqlalchemy as sa
revision='0004'
down_revision='0003'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('teams',
        sa.Column('id',sa.Integer(),primary_key=True,nullable=False),
        sa.Column('name',sa.String(length=120),primary_key=False,nullable=False,unique=True),
        sa.Column('calendar',sa.JSON(),primary_key=False,nullable=False),
    )
    op.create_table('work_items',
        sa.Column('id',sa.Integer(),primary_key=True,nullable=False),
        sa.Column('key',sa.String(length=250),primary_key=False,nullable=False,unique=True),
        sa.Column('kind',sa.String(length=30),primary_key=False,nullable=False),
        sa.Column('event',sa.String(length=50),primary_key=False,nullable=False),
        sa.Column('ticket_id',sa.Integer(),sa.ForeignKey('tickets.id'),primary_key=False,nullable=True),
        sa.Column('target_id',sa.Integer(),primary_key=False,nullable=True),
        sa.Column('payload',sa.JSON(),primary_key=False,nullable=False),
        sa.Column('state',sa.String(length=20),primary_key=False,nullable=False),
        sa.Column('attempts',sa.Integer(),primary_key=False,nullable=False),
        sa.Column('due_at',sa.DateTime(timezone=True),primary_key=False,nullable=False),
        sa.Column('error',sa.Text(),primary_key=False,nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),primary_key=False,nullable=False),
    )
    op.create_table('saved_views',
        sa.Column('id',sa.Integer(),primary_key=True,nullable=False),
        sa.Column('operator_id',sa.Integer(),sa.ForeignKey('operators.id'),primary_key=False,nullable=False),
        sa.Column('name',sa.String(length=100),primary_key=False,nullable=False),
        sa.Column('query',sa.String(length=2000),primary_key=False,nullable=False),
    )
    op.create_table('login_sessions',
        sa.Column('id',sa.String(length=100),primary_key=True,nullable=False),
        sa.Column('operator_id',sa.Integer(),sa.ForeignKey('operators.id'),primary_key=False,nullable=False),
        sa.Column('device',sa.String(length=300),primary_key=False,nullable=False),
        sa.Column('revoked',sa.Boolean(),primary_key=False,nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),primary_key=False,nullable=False),
    )
    op.create_table('portal_access',
        sa.Column('token_hash',sa.String(length=64),primary_key=True,nullable=False),
        sa.Column('client_id',sa.BigInteger(),primary_key=False,nullable=False),
        sa.Column('expires_at',sa.DateTime(timezone=True),primary_key=False,nullable=False),
        sa.Column('revoked',sa.Boolean(),primary_key=False,nullable=False),
    )
    op.create_table('incidents',
        sa.Column('id',sa.Integer(),primary_key=True,nullable=False),
        sa.Column('team_id',sa.Integer(),sa.ForeignKey('teams.id'),primary_key=False,nullable=True),
        sa.Column('title',sa.String(length=255),primary_key=False,nullable=False),
        sa.Column('draft',sa.Text(),primary_key=False,nullable=False),
        sa.Column('status',sa.String(length=20),primary_key=False,nullable=False),
        sa.Column('revision',sa.Integer(),primary_key=False,nullable=False),
    )
    op.create_table('incident_tickets',
        sa.Column('id',sa.Integer(),primary_key=True,nullable=False),
        sa.Column('incident_id',sa.Integer(),sa.ForeignKey('incidents.id'),primary_key=False,nullable=False),
        sa.Column('ticket_id',sa.Integer(),sa.ForeignKey('tickets.id'),primary_key=False,nullable=False),
        sa.UniqueConstraint('incident_id','ticket_id'),
    )
    op.add_column('operators',sa.Column('team_id',sa.Integer(),nullable=True))
    op.add_column('tickets',sa.Column('team_id',sa.Integer(),nullable=True))
    op.add_column('tickets',sa.Column('channel',sa.String(20),nullable=False,server_default='telegram'))
    op.add_column('tickets',sa.Column('tags',sa.String(500),nullable=False,server_default=''))
    op.add_column('tickets',sa.Column('paused_at',sa.DateTime(timezone=True),nullable=True))
    op.add_column('tickets',sa.Column('paused_seconds',sa.Integer(),nullable=False,server_default='0'))
    op.create_index('ix_work_items_state','work_items',['state','due_at'])
    op.create_index('ix_tickets_team_id','tickets',['team_id'])
    if op.get_bind().dialect.name == 'postgresql':
        op.create_foreign_key('fk_operators_team','operators','teams',['team_id'],['id'])
        op.create_foreign_key('fk_tickets_team','tickets','teams',['team_id'],['id'])
        op.execute("CREATE INDEX ix_messages_fts ON messages USING gin (to_tsvector('russian', coalesce(text,'')))")
        op.execute("CREATE INDEX ix_tickets_fts ON tickets USING gin (to_tsvector('russian', coalesce(subject,'')))")

def downgrade():
    if op.get_bind().dialect.name == 'postgresql':
        op.drop_constraint('fk_operators_team','operators',type_='foreignkey')
        op.drop_constraint('fk_tickets_team','tickets',type_='foreignkey')
        op.execute('DROP INDEX IF EXISTS ix_messages_fts')
        op.execute('DROP INDEX IF EXISTS ix_tickets_fts')
    op.drop_index('ix_tickets_team_id',table_name='tickets')
    for c in ['paused_seconds','paused_at','tags','channel','team_id']: op.drop_column('tickets',c)
    op.drop_column('operators','team_id')
    for name in ['incident_tickets','incidents','portal_access','login_sessions','saved_views','work_items','teams']: op.drop_table(name)
