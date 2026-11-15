"""Immutable partner commissions and reserve-backed withdrawals."""
from alembic import op
import sqlalchemy as sa

revision = '0057_partner_commissions'
down_revision = '0056_support_topology'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('payments', sa.Column('reseller_slug_snapshot', sa.String(64)))
    op.add_column('payments', sa.Column('reseller_percent_snapshot', sa.Numeric(5,2)))
    op.add_column('resellers', sa.Column('balance_currency', sa.String(3)))
    op.add_column('resellers', sa.Column('owner_user_id', sa.Integer()))
    op.create_foreign_key('fk_reseller_owner', 'resellers', 'users', ['owner_user_id'], ['id'], ondelete='RESTRICT')
    op.create_unique_constraint('uq_reseller_owner', 'resellers', ['owner_user_id'])
    op.add_column('resellers', sa.Column('balance', sa.Numeric(14,2), nullable=False, server_default='0'))
    op.alter_column('resellers', 'balance', server_default=None)
    op.create_table('partner_commissions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('payment_id', sa.Integer(), sa.ForeignKey('payments.id', ondelete='RESTRICT'), nullable=False, unique=True),
        sa.Column('reseller_id', sa.Integer(), sa.ForeignKey('resellers.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('amount', sa.Numeric(14,2), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('percent', sa.Numeric(5,2), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('reversed_at', sa.DateTime()))
    op.create_index('ix_partner_commissions_reseller_id', 'partner_commissions', ['reseller_id'])
    op.create_table('partner_withdrawals',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('reseller_id', sa.Integer(), sa.ForeignKey('resellers.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('idempotency_key', sa.String(128), nullable=False),
        sa.Column('amount', sa.Numeric(14,2), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('destination', sa.String(255), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('reference', sa.String(255)),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('reseller_id', 'idempotency_key', name='uq_partner_withdrawal_retry'))
    op.create_index('ix_partner_withdrawals_reseller_id', 'partner_withdrawals', ['reseller_id'])


def downgrade():
    if op.get_bind().dialect.name == 'postgresql':
        op.execute('LOCK TABLE partner_commissions, partner_withdrawals, resellers, payments IN ACCESS EXCLUSIVE MODE')
    for table in ('partner_commissions','partner_withdrawals'):
        if op.get_bind().execute(sa.text(f'SELECT 1 FROM {table} LIMIT 1')).first():
            raise RuntimeError('Partner financial history prevents downgrade')
    op.drop_table('partner_withdrawals');op.drop_table('partner_commissions')
    op.drop_constraint('uq_reseller_owner','resellers',type_='unique')
    op.drop_constraint('fk_reseller_owner','resellers',type_='foreignkey')
    op.drop_column('resellers','balance_currency')
    op.drop_column('resellers','owner_user_id');op.drop_column('resellers','balance')
    op.drop_column('payments','reseller_percent_snapshot');op.drop_column('payments','reseller_slug_snapshot')
