"""Push campaigns: sending later and A/B tests of two texts (push_campaign_recipients)."""
from alembic import op
import sqlalchemy as sa

revision = "0078_campaign_ab"
down_revision = "0077_app_growth"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("push_campaigns", sa.Column("scheduled_at", sa.DateTime()))
    op.add_column("push_campaigns", sa.Column("sent_at", sa.DateTime()))
    op.add_column("push_campaigns", sa.Column("title_b", sa.String(120)))
    op.add_column("push_campaigns", sa.Column("body_b", sa.Text()))
    op.add_column("push_campaigns", sa.Column("b_percent", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("push_campaigns", sa.Column("conversion_days", sa.Integer(), nullable=False, server_default="7"))
    op.create_index("ix_push_campaigns_scheduled_at", "push_campaigns", ["scheduled_at"])
    op.execute("UPDATE push_campaigns SET sent_at = created_at WHERE status = 'sent'")
    op.create_table(
        "push_campaign_recipients",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("campaign_id", sa.Integer(), sa.ForeignKey("push_campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("variant", sa.String(1), nullable=False, server_default="a"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("campaign_id", "user_id", name="uq_push_campaign_recipient"),
    )
    op.create_index("ix_push_campaign_recipients_campaign_id", "push_campaign_recipients", ["campaign_id"])
    op.create_index("ix_push_campaign_recipients_user_id", "push_campaign_recipients", ["user_id"])


def downgrade():
    op.drop_table("push_campaign_recipients")
    op.drop_index("ix_push_campaigns_scheduled_at", table_name="push_campaigns")
    for column in ("conversion_days", "b_percent", "body_b", "title_b", "sent_at", "scheduled_at"):
        op.drop_column("push_campaigns", column)
