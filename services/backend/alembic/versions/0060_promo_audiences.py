"""Manual/dynamic promo groups and personal offer scopes."""
from alembic import op
import sqlalchemy as sa
revision='0060_promo_audiences'
down_revision='0059_content_publishing'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('promo_groups',sa.Column('id',sa.Integer(),primary_key=True),sa.Column('name',sa.String(200),nullable=False),
        sa.Column('segment',sa.String(16),nullable=False),sa.Column('enabled',sa.Boolean(),nullable=False),sa.Column('version',sa.Integer(),nullable=False))
    op.create_table('promo_group_members',sa.Column('group_id',sa.Integer(),sa.ForeignKey('promo_groups.id',ondelete='RESTRICT'),primary_key=True),
        sa.Column('user_id',sa.Integer(),sa.ForeignKey('users.id',ondelete='RESTRICT'),primary_key=True))
    op.create_table('promo_audiences',sa.Column('promo_id',sa.Integer(),sa.ForeignKey('promo_codes.id',ondelete='RESTRICT'),primary_key=True),
        sa.Column('title',sa.String(200),nullable=False),sa.Column('description',sa.Text(),nullable=False),
        sa.Column('group_id',sa.Integer(),sa.ForeignKey('promo_groups.id',ondelete='RESTRICT')),sa.Column('user_ids',sa.JSON(),nullable=False),
        sa.Column('enabled',sa.Boolean(),nullable=False),sa.Column('version',sa.Integer(),nullable=False))


def downgrade():
    if op.get_bind().dialect.name=='postgresql':op.execute('LOCK TABLE promo_groups, promo_group_members, promo_audiences IN ACCESS EXCLUSIVE MODE')
    for table in ('promo_groups','promo_audiences'):
        if op.get_bind().execute(sa.text(f'SELECT 1 FROM {table} LIMIT 1')).first():raise RuntimeError('Targeted promotion rules prevent downgrade')
    op.drop_table('promo_audiences');op.drop_table('promo_group_members');op.drop_table('promo_groups')
