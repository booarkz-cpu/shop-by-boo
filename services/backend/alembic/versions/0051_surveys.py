"""Frozen surveys and exactly-once participation rewards."""
from alembic import op
import sqlalchemy as sa
revision='0051_surveys'
down_revision='0050_account_actions'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('surveys',sa.Column('id',sa.Integer(),primary_key=True),sa.Column('title',sa.String(255),nullable=False),
        sa.Column('description',sa.Text(),nullable=False),sa.Column('questions',sa.JSON(),nullable=False),sa.Column('state',sa.String(16),nullable=False),
        sa.Column('starts_at',sa.DateTime(),nullable=False),sa.Column('ends_at',sa.DateTime(),nullable=False),sa.Column('max_responses',sa.Integer(),nullable=False),
        sa.Column('response_count',sa.Integer(),nullable=False),sa.Column('reward_amount',sa.Numeric(12,2),nullable=False),sa.Column('currency',sa.String(3),nullable=False),
        sa.Column('require_verified_email',sa.Boolean(),nullable=False),sa.Column('require_subscription',sa.Boolean(),nullable=False),
        sa.Column('results_mode',sa.String(16),nullable=False),sa.Column('statistics',sa.JSON(),nullable=False),
        sa.Column('created_at',sa.DateTime(),nullable=False),sa.Column('updated_at',sa.DateTime(),nullable=False))
    op.create_table('survey_responses',sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('survey_id',sa.Integer(),sa.ForeignKey('surveys.id',ondelete='RESTRICT'),nullable=False),
        sa.Column('user_id',sa.Integer(),sa.ForeignKey('users.id',ondelete='SET NULL')),
        sa.Column('answers',sa.JSON(),nullable=False),sa.Column('fingerprint',sa.String(64),nullable=False),
        sa.Column('reward_amount',sa.Numeric(12,2),nullable=False),sa.Column('currency',sa.String(3),nullable=False),sa.Column('created_at',sa.DateTime(),nullable=False),
        sa.UniqueConstraint('survey_id','user_id',name='uq_survey_responses_owner'))
    op.create_index('ix_survey_responses_survey_id','survey_responses',['survey_id'])
    op.create_index('ix_survey_responses_user_id','survey_responses',['user_id'])

def downgrade():
    if op.get_bind().dialect.name=='postgresql':
        op.get_bind().execute(sa.text('LOCK TABLE survey_responses IN ACCESS EXCLUSIVE MODE'))
    if op.get_bind().execute(sa.text('SELECT count(*) FROM survey_responses')).scalar():
        raise RuntimeError('Survey responses exist; downgrade would lose participation and reward identities')
    op.drop_table('survey_responses');op.drop_table('surveys')
