"""Customer discoverable WebAuthn credentials with separate challenges."""
from alembic import op
import sqlalchemy as sa

revision = '0055_customer_passkeys'
down_revision = '0054_referral_levels'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('passkey_user_handle', sa.String(64)))
    op.create_unique_constraint('uq_users_passkey_user_handle', 'users', ['passkey_user_handle'])
    op.create_table('customer_passkeys',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('credential_id', sa.String(1024), nullable=False, unique=True),
        sa.Column('public_key', sa.Text(), nullable=False),
        sa.Column('sign_count', sa.BigInteger(), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('last_used_at', sa.DateTime()))
    op.create_index('ix_customer_passkeys_user_id', 'customer_passkeys', ['user_id'])
    op.create_table('customer_passkey_challenges',
        sa.Column('ticket_hash', sa.String(64), primary_key=True),
        sa.Column('binding_hash', sa.String(64), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE')),
        sa.Column('purpose', sa.String(24), nullable=False),
        sa.Column('challenge', sa.String(128), nullable=False),
        sa.Column('context', sa.JSON(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False))
    op.create_index('ix_customer_passkey_challenges_expires_at', 'customer_passkey_challenges', ['expires_at'])


def downgrade():
    if op.get_bind().dialect.name == 'postgresql':
        op.execute('LOCK TABLE customer_passkeys, users IN ACCESS EXCLUSIVE MODE')
    if op.get_bind().execute(sa.text('SELECT 1 FROM customer_passkeys LIMIT 1')).first():
        raise RuntimeError('Remove customer passkeys before downgrade; preserve credential identities')
    op.drop_table('customer_passkey_challenges')
    op.drop_table('customer_passkeys')
    op.drop_constraint('uq_users_passkey_user_handle', 'users', type_='unique')
    op.drop_column('users', 'passkey_user_handle')
