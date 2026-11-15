"""Freeze fixed and constructed gift entitlements at purchase."""
from alembic import op
import sqlalchemy as sa
revision='0046_gift_snapshots'
down_revision='0045_multiple_subscriptions'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('gift_redemptions',sa.Column('before_snapshot',sa.JSON(),nullable=True))
    op.add_column('gift_codes',sa.Column('entitlements_snapshot',sa.JSON(),nullable=True))
    op.add_column('gift_codes',sa.Column('purchase_fingerprint',sa.String(64),nullable=True))
    op.add_column('gift_codes',sa.Column('purchase_amount',sa.Numeric(12,2),nullable=True))
    op.execute("""UPDATE gift_codes g SET entitlements_snapshot=json_build_object(
        'days',COALESCE(g.duration_days,p.duration_days),'traffic_gb',p.traffic_limit_gb,
        'devices',p.device_limit,'profile_id',p.remnawave_profile_id) FROM plans p WHERE g.plan_id=p.id""")
    op.execute("UPDATE gift_codes g SET purchase_amount=l.amount FROM financial_ledger l WHERE l.operation_key='gift-purchase:'||g.id AND l.user_id=g.purchaser_user_id")

def downgrade():
    op.drop_column('gift_redemptions','before_snapshot')
    for col in ('purchase_amount','purchase_fingerprint','entitlements_snapshot'):op.drop_column('gift_codes',col)
