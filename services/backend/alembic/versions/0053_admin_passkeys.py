"""Persistent opaque user handles and single-use WebAuthn challenges."""
from alembic import op
import sqlalchemy as sa

revision = '0053_admin_passkeys'
down_revision = '0052_giveaways'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column('webauthn_credentials', 'sign_count', existing_type=sa.Integer(), type_=sa.BigInteger(), existing_nullable=False)
    op.add_column('admin_users', sa.Column('passkey_user_handle', sa.String(64)))
    op.create_unique_constraint('uq_admin_passkey_user_handle', 'admin_users', ['passkey_user_handle'])
    op.create_table('webauthn_challenges',
        sa.Column('ticket_hash', sa.String(64), primary_key=True),
        sa.Column('binding_hash', sa.String(64), nullable=False),
        sa.Column('purpose', sa.String(24), nullable=False),
        sa.Column('admin_id', sa.Integer(), sa.ForeignKey('admin_users.id', ondelete='CASCADE')),
        sa.Column('challenge', sa.String(128), nullable=False),
        sa.Column('context', sa.JSON(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False))
    op.create_index('ix_webauthn_challenges_expires_at', 'webauthn_challenges', ['expires_at'])


def downgrade():
    if op.get_bind().dialect.name == 'postgresql':
        op.execute('LOCK TABLE webauthn_credentials, admin_users IN ACCESS EXCLUSIVE MODE')
    if op.get_bind().execute(sa.text('SELECT 1 FROM webauthn_credentials LIMIT 1')).first():
        raise RuntimeError('Remove registered passkeys before downgrading: their opaque identities must be preserved')
    op.alter_column('webauthn_credentials', 'sign_count', existing_type=sa.BigInteger(), type_=sa.Integer(), existing_nullable=False)
    op.drop_table('webauthn_challenges')
    op.drop_constraint('uq_admin_passkey_user_handle', 'admin_users', type_='unique')
    op.drop_column('admin_users', 'passkey_user_handle')
