"""Add verified, journaled customer account merging."""

from alembic import op
import sqlalchemy as sa


revision = '0063_account_merge'
down_revision = '0062_support_delivery_identity'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users') as batch:
        batch.add_column(sa.Column('merged_into_user_id', sa.Integer()))
        batch.add_column(sa.Column('merged_at', sa.DateTime()))
        batch.create_foreign_key('fk_users_merged_into', 'users', ['merged_into_user_id'], ['id'], ondelete='RESTRICT')
        batch.create_index('ix_users_merged_into_user_id', ['merged_into_user_id'])

    op.create_table(
        'account_merge_aliases',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('source_user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('target_user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('telegram_id', sa.BigInteger()),
        sa.Column('yandex_id', sa.String(255)),
        sa.Column('vk_id', sa.String(255)),
        sa.Column('email', sa.String(320)),
        sa.Column('email_password_hash', sa.String(512)),
        sa.Column('email_verified_at', sa.DateTime()),
        sa.Column('referral_code', sa.String(32), nullable=False),
        sa.Column('merged_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('source_user_id', name='uq_account_merge_alias_source'),
        sa.UniqueConstraint('telegram_id', name='uq_account_merge_alias_telegram'),
        sa.UniqueConstraint('yandex_id', name='uq_account_merge_alias_yandex'),
        sa.UniqueConstraint('vk_id', name='uq_account_merge_alias_vk'),
        sa.UniqueConstraint('email', name='uq_account_merge_alias_email'),
        sa.UniqueConstraint('referral_code', name='uq_account_merge_alias_referral'),
    )
    op.create_index('ix_account_merge_aliases_source_user_id', 'account_merge_aliases', ['source_user_id'])
    op.create_index('ix_account_merge_aliases_target_user_id', 'account_merge_aliases', ['target_user_id'])
    op.create_index('ix_account_merge_aliases_telegram_id', 'account_merge_aliases', ['telegram_id'])
    op.create_index('ix_account_merge_aliases_yandex_id', 'account_merge_aliases', ['yandex_id'])
    op.create_index('ix_account_merge_aliases_vk_id', 'account_merge_aliases', ['vk_id'])
    op.create_index('ix_account_merge_aliases_email', 'account_merge_aliases', ['email'])
    op.create_index('ix_account_merge_aliases_referral_code', 'account_merge_aliases', ['referral_code'])

    op.create_table(
        'account_merge_authorizations',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('source_user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('token_hash', sa.String(64), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('used_at', sa.DateTime()),
        sa.Column('target_user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='RESTRICT')),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('token_hash', name='uq_account_merge_authorization_token'),
    )
    op.create_index('ix_account_merge_authorizations_source_user_id', 'account_merge_authorizations', ['source_user_id'])
    op.create_index('ix_account_merge_authorizations_token_hash', 'account_merge_authorizations', ['token_hash'])
    op.create_index('ix_account_merge_authorizations_expires_at', 'account_merge_authorizations', ['expires_at'])

    op.create_table(
        'account_merge_operations',
        sa.Column('key', sa.String(64), primary_key=True),
        sa.Column('fingerprint', sa.String(64), nullable=False),
        sa.Column('authorization_id', sa.Integer(), sa.ForeignKey('account_merge_authorizations.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('source_user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('target_user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('result', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_account_merge_operations_source_user_id', 'account_merge_operations', ['source_user_id'])
    op.create_index('ix_account_merge_operations_target_user_id', 'account_merge_operations', ['target_user_id'])

    with op.batch_alter_table('customer_passkeys') as batch:
        batch.add_column(sa.Column('user_handle', sa.String(64)))
    op.execute(sa.text(
        'UPDATE customer_passkeys SET user_handle = '
        '(SELECT passkey_user_handle FROM users WHERE users.id = customer_passkeys.user_id) '
        'WHERE user_handle IS NULL'
    ))


def downgrade():
    bind = op.get_bind()
    merged = bind.execute(sa.text('SELECT 1 FROM account_merge_aliases LIMIT 1')).first()
    operations = bind.execute(sa.text('SELECT 1 FROM account_merge_operations LIMIT 1')).first()
    if merged or operations:
        raise RuntimeError('Account merge history prevents downgrade')
    with op.batch_alter_table('customer_passkeys') as batch:
        batch.drop_column('user_handle')
    op.drop_index('ix_account_merge_operations_target_user_id', table_name='account_merge_operations')
    op.drop_index('ix_account_merge_operations_source_user_id', table_name='account_merge_operations')
    op.drop_table('account_merge_operations')
    op.drop_index('ix_account_merge_authorizations_expires_at', table_name='account_merge_authorizations')
    op.drop_index('ix_account_merge_authorizations_token_hash', table_name='account_merge_authorizations')
    op.drop_index('ix_account_merge_authorizations_source_user_id', table_name='account_merge_authorizations')
    op.drop_table('account_merge_authorizations')
    op.drop_index('ix_account_merge_aliases_referral_code', table_name='account_merge_aliases')
    op.drop_index('ix_account_merge_aliases_email', table_name='account_merge_aliases')
    op.drop_index('ix_account_merge_aliases_vk_id', table_name='account_merge_aliases')
    op.drop_index('ix_account_merge_aliases_yandex_id', table_name='account_merge_aliases')
    op.drop_index('ix_account_merge_aliases_telegram_id', table_name='account_merge_aliases')
    op.drop_index('ix_account_merge_aliases_target_user_id', table_name='account_merge_aliases')
    op.drop_index('ix_account_merge_aliases_source_user_id', table_name='account_merge_aliases')
    op.drop_table('account_merge_aliases')
    with op.batch_alter_table('users') as batch:
        batch.drop_index('ix_users_merged_into_user_id')
        batch.drop_constraint('fk_users_merged_into', type_='foreignkey')
        batch.drop_column('merged_at')
        batch.drop_column('merged_into_user_id')
