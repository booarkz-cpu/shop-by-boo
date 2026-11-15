"""Single-use account recovery and durable encrypted mail outbox."""
from alembic import op
import sqlalchemy as sa
revision='0050_account_actions'
down_revision='0049_renewal_terms'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('users',sa.Column('email_verified_at',sa.DateTime(),nullable=True))
    op.create_table('account_actions',sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('user_id',sa.Integer(),sa.ForeignKey('users.id',ondelete='CASCADE'),nullable=False),
        sa.Column('token_hash',sa.String(64),nullable=False,unique=True),sa.Column('purpose',sa.String(24),nullable=False),
        sa.Column('email',sa.String(320),nullable=False),sa.Column('password_fingerprint',sa.String(64)),
        sa.Column('created_at',sa.DateTime(),nullable=False),sa.Column('expires_at',sa.DateTime(),nullable=False),sa.Column('used_at',sa.DateTime()))
    op.create_index('ix_account_actions_user_id','account_actions',['user_id'])
    op.create_table('account_mail',sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('action_id',sa.Integer(),sa.ForeignKey('account_actions.id',ondelete='CASCADE'),nullable=False,unique=True),
        sa.Column('token_encrypted',sa.Text(),nullable=False),sa.Column('status',sa.String(16),nullable=False),
        sa.Column('attempts',sa.Integer(),nullable=False),sa.Column('next_retry_at',sa.DateTime(),nullable=False),sa.Column('error',sa.String(40)))

def downgrade():
    op.drop_table('account_mail');op.drop_index('ix_account_actions_user_id',table_name='account_actions');op.drop_table('account_actions')
    op.drop_column('users','email_verified_at')
