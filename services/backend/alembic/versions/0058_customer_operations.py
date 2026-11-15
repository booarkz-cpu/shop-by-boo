"""Encrypted customer import previews, identity dedupe and bulk journals."""
from alembic import op
import sqlalchemy as sa

revision = '0058_customer_operations'
down_revision = '0057_partner_commissions'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('customer_import_jobs',
        sa.Column('id', sa.String(48), primary_key=True),
        sa.Column('namespace', sa.String(64), nullable=False),
        sa.Column('source_sha256', sa.String(64), nullable=False),
        sa.Column('actor', sa.String(320), nullable=False),
        sa.Column('fingerprint', sa.String(64), nullable=False),
        sa.Column('payload_encrypted', sa.Text(), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('result', sa.JSON()),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False))
    op.create_index('ix_customer_import_jobs_expires_at', 'customer_import_jobs', ['expires_at'])
    op.create_table('customer_import_identities',
        sa.Column('key', sa.String(64), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('telegram_digest', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False))
    op.create_index('ix_customer_import_identities_user_id', 'customer_import_identities', ['user_id'])
    op.create_table('customer_batch_operations',
        sa.Column('key', sa.String(64), primary_key=True),
        sa.Column('fingerprint', sa.String(64), nullable=False),
        sa.Column('result', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False))


def downgrade():
    if op.get_bind().dialect.name == 'postgresql':
        op.execute('LOCK TABLE customer_import_jobs, customer_import_identities, customer_batch_operations IN ACCESS EXCLUSIVE MODE')
    for table in ('customer_import_identities', 'customer_batch_operations'):
        if op.get_bind().execute(sa.text(f'SELECT 1 FROM {table} LIMIT 1')).first():
            raise RuntimeError('Customer import/bulk history prevents downgrade')
    op.drop_table('customer_batch_operations');op.drop_table('customer_import_identities');op.drop_table('customer_import_jobs')
