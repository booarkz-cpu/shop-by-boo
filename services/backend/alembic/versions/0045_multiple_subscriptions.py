"""Bind orders and devices to independent owner subscriptions."""
from alembic import op
import sqlalchemy as sa
revision='0045_multiple_subscriptions'
down_revision='0044_subscription_commerce'
branch_labels=None
depends_on=None

def upgrade():
    bind=op.get_bind();inspector=sa.inspect(bind)
    for c in inspector.get_unique_constraints('subscriptions'):
        if c['column_names']==['user_id']:op.drop_constraint(c['name'],'subscriptions',type_='unique')
    for i in inspector.get_indexes('subscriptions'):
        if i['unique'] and i['column_names']==['user_id'] and not i.get('duplicates_constraint'):
            op.drop_index(i['name'],table_name='subscriptions')
    if not any(i['name']=='ix_subscriptions_user_id' and not i['unique'] for i in sa.inspect(bind).get_indexes('subscriptions')):
        op.create_index('ix_subscriptions_user_id','subscriptions',['user_id'])
    op.add_column('subscriptions',sa.Column('is_primary',sa.Boolean(),nullable=False,server_default=sa.false()))
    op.add_column('subscriptions',sa.Column('name',sa.String(80),nullable=False,server_default='Подписка'))
    op.add_column('subscriptions',sa.Column('auto_renew_enabled',sa.Boolean(),nullable=False,server_default=sa.false()))
    op.add_column('subscriptions',sa.Column('next_renewal_at',sa.DateTime(),nullable=True))
    op.execute('UPDATE subscriptions SET is_primary=true WHERE id IN (SELECT min(id) FROM subscriptions GROUP BY user_id)')
    op.execute('UPDATE subscriptions s SET auto_renew_enabled=u.auto_renew_enabled FROM users u WHERE s.user_id=u.id AND s.is_primary')
    op.create_index('uq_subscriptions_primary_user','subscriptions',['user_id'],unique=True,postgresql_where=sa.text('is_primary'))
    for table in ('payments','user_devices','trial_grants','gift_redemptions'):
        op.add_column(table,sa.Column('subscription_id',sa.Integer(),nullable=True))
        op.create_index(f'ix_{table}_subscription_id',table,['subscription_id'])
        op.execute(f'UPDATE {table} t SET subscription_id=s.id FROM subscriptions s WHERE t.user_id=s.user_id AND s.is_primary'+(" AND t.purpose='subscription'" if table=='payments' else ''))
    op.execute('UPDATE subscriptions s SET next_renewal_at=m.next_attempt_at FROM auto_renew_methods m WHERE s.user_id=m.user_id AND s.is_primary')
    op.add_column('payments',sa.Column('new_subscription',sa.Boolean(),nullable=False,server_default=sa.false()))

def downgrade():
    if op.get_bind().execute(sa.text('SELECT 1 FROM subscriptions GROUP BY user_id HAVING count(*)>1 LIMIT 1')).first():
        raise RuntimeError('Multiple subscriptions exist: migrate data explicitly before downgrade')
    op.drop_column('payments','new_subscription')
    for table in ('payments','user_devices','trial_grants','gift_redemptions'):
        op.drop_index(f'ix_{table}_subscription_id',table_name=table);op.drop_column(table,'subscription_id')
    op.drop_index('uq_subscriptions_primary_user',table_name='subscriptions')
    for column in ('next_renewal_at','auto_renew_enabled','name','is_primary'):op.drop_column('subscriptions',column)
