"""Free contests and prize wheels with frozen budgets and unique participation."""
from alembic import op
import sqlalchemy as sa

revision = '0052_giveaways'
down_revision = '0051_surveys'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('giveaways',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('kind', sa.String(16), nullable=False),
        sa.Column('state', sa.String(16), nullable=False),
        sa.Column('starts_at', sa.DateTime(), nullable=False),
        sa.Column('ends_at', sa.DateTime(), nullable=False),
        sa.Column('max_entries', sa.Integer(), nullable=False),
        sa.Column('entry_count', sa.Integer(), nullable=False),
        sa.Column('winners_count', sa.Integer(), nullable=False),
        sa.Column('prizes', sa.JSON(), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('budget_limit', sa.Numeric(12, 2), nullable=False),
        sa.Column('budget_credited', sa.Numeric(12, 2), nullable=False),
        sa.Column('require_subscription', sa.Boolean(), nullable=False),
        sa.Column('drawn_at', sa.DateTime()),
        sa.Column('created_at', sa.DateTime(), nullable=False))
    op.create_table('giveaway_entries',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('giveaway_id', sa.Integer(), sa.ForeignKey('giveaways.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('outcome', sa.String(16), nullable=False),
        sa.Column('prize_index', sa.Integer()),
        sa.Column('reward_amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('giveaway_id', 'user_id', name='uq_giveaway_entries_owner'))
    op.create_index('ix_giveaway_entries_giveaway_id', 'giveaway_entries', ['giveaway_id'])
    op.create_index('ix_giveaway_entries_user_id', 'giveaway_entries', ['user_id'])


def downgrade():
    connection = op.get_bind()
    if connection.dialect.name == 'postgresql':
        connection.execute(sa.text('LOCK TABLE giveaway_entries IN ACCESS EXCLUSIVE MODE'))
    if connection.execute(sa.text('SELECT count(*) FROM giveaway_entries')).scalar():
        raise RuntimeError('Giveaway entries exist; downgrade would lose reward identities')
    op.drop_table('giveaway_entries')
    op.drop_table('giveaways')
