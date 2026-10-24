"""Automation engine executions; reversible anti-abuse suspension of subscriptions."""
from alembic import op
import sqlalchemy as sa

revision = "0074_automation_engine"
down_revision = "0073_e2e_v2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "automation_executions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rule_id", sa.Integer(), sa.ForeignKey("automation_rules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("anchor", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("rule_id", "anchor", name="uq_automation_executions_rule_anchor"),
    )
    op.create_index("ix_automation_executions_rule_id", "automation_executions", ["rule_id"])
    op.create_index("ix_automation_executions_user_id", "automation_executions", ["user_id"])
    op.create_index("ix_automation_executions_created_at", "automation_executions", ["created_at"])
    with op.batch_alter_table("subscriptions") as batch:
        batch.add_column(sa.Column("suspended_from", sa.String(32)))
    # Rules saved before the engine existed were never executed: keep them off until reviewed.
    op.execute("UPDATE automation_rules SET enabled = false")


def downgrade():
    # A suspended subscription keeps its paid term; return it to "active" before the column goes.
    op.execute("UPDATE subscriptions SET lifecycle_status = COALESCE(suspended_from, 'active') WHERE lifecycle_status = 'suspended'")
    with op.batch_alter_table("subscriptions") as batch:
        batch.drop_column("suspended_from")
    op.drop_index("ix_automation_executions_created_at", table_name="automation_executions")
    op.drop_index("ix_automation_executions_user_id", table_name="automation_executions")
    op.drop_index("ix_automation_executions_rule_id", table_name="automation_executions")
    op.drop_table("automation_executions")
