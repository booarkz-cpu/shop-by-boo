"""Structured pages and immutable publication snapshots."""
from alembic import op
import sqlalchemy as sa
revision='0059_content_publishing'
down_revision='0058_customer_operations'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('content_pages',sa.Column('id',sa.Integer(),primary_key=True),sa.Column('slug',sa.String(80),nullable=False),
        sa.Column('locale',sa.String(2),nullable=False),sa.Column('kind',sa.String(16),nullable=False),sa.Column('version',sa.Integer(),nullable=False),
        sa.Column('draft',sa.JSON(),nullable=False),sa.Column('published_revision',sa.Integer()),sa.Column('archived',sa.Boolean(),nullable=False),
        sa.Column('created_at',sa.DateTime(),nullable=False),sa.Column('updated_at',sa.DateTime(),nullable=False),sa.UniqueConstraint('slug','locale',name='uq_content_page_slug_locale'))
    op.create_table('content_revisions',sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('page_id',sa.Integer(),sa.ForeignKey('content_pages.id',ondelete='RESTRICT'),nullable=False),sa.Column('version',sa.Integer(),nullable=False),
        sa.Column('snapshot',sa.JSON(),nullable=False),sa.Column('actor',sa.String(320),nullable=False),sa.Column('starts_at',sa.DateTime()),sa.Column('ends_at',sa.DateTime()),
        sa.Column('created_at',sa.DateTime(),nullable=False),sa.UniqueConstraint('page_id','version',name='uq_content_revision_version'))
    op.create_index('ix_content_revisions_page_id','content_revisions',['page_id'])


def downgrade():
    if op.get_bind().dialect.name=='postgresql':op.execute('LOCK TABLE content_pages, content_revisions IN ACCESS EXCLUSIVE MODE')
    if op.get_bind().execute(sa.text('SELECT 1 FROM content_pages LIMIT 1')).first():raise RuntimeError('Content drafts/publication history prevents downgrade')
    op.drop_table('content_revisions');op.drop_table('content_pages')
