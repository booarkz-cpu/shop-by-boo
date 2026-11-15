"""Immutable multilevel referral snapshots and reversible extra-level rewards."""
from alembic import op
import sqlalchemy as sa

revision = '0054_referral_levels'
down_revision = '0053_admin_passkeys'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('payments', sa.Column('referral_terms_snapshot', sa.JSON()))
    op.create_table('referral_level_rewards',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('referrer_id', sa.Integer(), nullable=False),
        sa.Column('referred_user_id', sa.Integer(), nullable=False),
        sa.Column('payment_id', sa.Integer(), nullable=False),
        sa.Column('level', sa.Integer(), nullable=False),
        sa.Column('amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('status', sa.String(32), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('payment_id', 'level', name='uq_referral_level_payment'),
        sa.UniqueConstraint('payment_id', 'referrer_id', name='uq_referral_level_beneficiary'))
    op.add_column('referral_ledger', sa.Column('referral_level_reward_id', sa.Integer()))
    op.create_foreign_key('fk_referral_ledger_level_reward', 'referral_ledger', 'referral_level_rewards', ['referral_level_reward_id'], ['id'], ondelete='RESTRICT')
    op.create_index('ix_referral_ledger_referral_level_reward_id', 'referral_ledger', ['referral_level_reward_id'])
    for field in ('referrer_id', 'referred_user_id', 'payment_id'):
        op.create_index(f'ix_referral_level_rewards_{field}', 'referral_level_rewards', [field])


def downgrade():
    if op.get_bind().dialect.name == 'postgresql':
        op.execute('LOCK TABLE referral_level_rewards, payments IN ACCESS EXCLUSIVE MODE')
    if op.get_bind().execute(sa.text('SELECT 1 FROM referral_level_rewards LIMIT 1')).first():
        raise RuntimeError('Referral financial history exists; use a forward fix or restore a consistent backup')
    op.drop_index('ix_referral_ledger_referral_level_reward_id', 'referral_ledger')
    op.drop_constraint('fk_referral_ledger_level_reward', 'referral_ledger', type_='foreignkey')
    op.drop_column('referral_ledger', 'referral_level_reward_id')
    op.drop_table('referral_level_rewards')
    op.drop_column('payments', 'referral_terms_snapshot')
