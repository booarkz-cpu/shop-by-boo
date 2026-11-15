"""Menu folders, parent links, styles and custom emoji."""
from alembic import op
import sqlalchemy as sa
import json
revision='0061_menu_hierarchy'
down_revision='0060_promo_audiences'
branch_labels=None
depends_on=None


def upgrade():
    op.add_column('bot_menu_items',sa.Column('parent_id',sa.Integer(),sa.ForeignKey('bot_menu_items.id',name='fk_bot_menu_parent',ondelete='RESTRICT')))
    op.create_index('ix_bot_menu_items_parent_id','bot_menu_items',['parent_id'])
    op.add_column('bot_menu_items',sa.Column('style',sa.String(16),nullable=False,server_default='default'))
    op.add_column('bot_menu_items',sa.Column('icon_custom_emoji_id',sa.String(32)))
    op.add_column('bot_menu_items',sa.Column('icon',sa.String(16),nullable=False,server_default=''))


def downgrade():
    if op.get_bind().dialect.name=='postgresql':op.execute('LOCK TABLE bot_menu_items, app_settings IN ACCESS EXCLUSIVE MODE')
    used=op.get_bind().execute(sa.text("SELECT 1 FROM bot_menu_items WHERE parent_id IS NOT NULL OR item_type='folder' OR style<>'default' OR icon_custom_emoji_id IS NOT NULL OR icon<>'' LIMIT 1")).first()
    if used:raise RuntimeError('Configured menu tree/styles prevent downgrade')
    raw=op.get_bind().execute(sa.text("SELECT value FROM app_settings WHERE key='miniapp_buttons'")).scalar()
    if raw:
        try:buttons=json.loads(raw)
        except (ValueError,TypeError):raise RuntimeError('Malformed Mini App menu prevents downgrade')
        def configured(nodes):
            if not isinstance(nodes,list):return True
            return any(not isinstance(node,dict) or node.get('type')=='folder' or node.get('children') or node.get('style','default')!='default' or node.get('icon_custom_emoji_id') or node.get('icon') for node in nodes)
        if configured(buttons):raise RuntimeError('Configured Mini App tree/styles prevent downgrade')
    op.drop_column('bot_menu_items','icon');op.drop_column('bot_menu_items','icon_custom_emoji_id');op.drop_column('bot_menu_items','style')
    op.drop_index('ix_bot_menu_items_parent_id',table_name='bot_menu_items');op.drop_constraint('fk_bot_menu_parent','bot_menu_items',type_='foreignkey');op.drop_column('bot_menu_items','parent_id')
