"""Growth features: Remnawave events, Stars subscriptions, family plans, trial guard,
cancellation feedback and partner commissions for wallet gifts."""
from alembic import op
import sqlalchemy as sa

revision = "0077_app_growth"
down_revision = "0075_app_config"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("plans") as batch:
        batch.add_column(sa.Column("family_seats", sa.Integer(), nullable=False, server_default="0"))
    with op.batch_alter_table("trial_grants") as batch:
        batch.add_column(sa.Column("ip_hash", sa.String(64)))
        batch.create_index("ix_trial_grants_ip_hash", ["ip_hash"])
    with op.batch_alter_table("partner_commissions") as batch:
        batch.alter_column("payment_id", existing_type=sa.Integer(), nullable=True)
        batch.add_column(sa.Column("gift_code_id", sa.Integer(), nullable=True))
        batch.create_unique_constraint("uq_partner_commissions_gift_code_id", ["gift_code_id"])
        batch.create_foreign_key("fk_partner_commissions_gift_code", "gift_codes", ["gift_code_id"], ["id"], ondelete="RESTRICT")
    op.create_table(
        "remnawave_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_key", sa.String(64), nullable=False, unique=True),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("event", sa.String(64), nullable=False),
        sa.Column("user_id", sa.Integer()),
        sa.Column("subscription_id", sa.Integer()),
        sa.Column("remote_id", sa.String(64)),
        sa.Column("data", sa.JSON()),
        sa.Column("notified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for column in ("event", "user_id", "subscription_id", "created_at"):
        op.create_index(f"ix_remnawave_events_{column}", "remnawave_events", [column])
    op.create_table(
        "stars_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.String(64), nullable=False, unique=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("subscription_id", sa.Integer()),
        sa.Column("stars_amount", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("first_charge_id", sa.String(255)),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("renewals", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("current_period_end", sa.DateTime()),
        sa.Column("reseller_id", sa.Integer()),
        sa.Column("reseller_percent_snapshot", sa.Numeric(5, 2)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("canceled_at", sa.DateTime()),
    )
    op.create_index("ix_stars_subscriptions_user_id", "stars_subscriptions", ["user_id"])
    op.create_index("ix_stars_subscriptions_subscription_id", "stars_subscriptions", ["subscription_id"])
    op.create_table(
        "family_groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("owner_subscription_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("invite_code", sa.String(32), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_family_groups_owner_user_id", "family_groups", ["owner_user_id"])
    op.create_table(
        "family_members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("family_groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("subscription_id", sa.Integer()),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("joined_at", sa.DateTime(), nullable=False),
        sa.Column("removed_at", sa.DateTime()),
        sa.Column("synced_at", sa.DateTime()),
        sa.Column("sync_error", sa.Text()),
        sa.UniqueConstraint("group_id", "user_id", name="uq_family_members_group_user"),
    )
    for column in ("group_id", "user_id", "subscription_id"):
        op.create_index(f"ix_family_members_{column}", "family_members", [column])
    op.create_table(
        "cancellation_feedback",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("subscription_id", sa.Integer()),
        sa.Column("reason", sa.String(32), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_cancellation_feedback_user_id", "cancellation_feedback", ["user_id"])
    op.create_index("ix_cancellation_feedback_created_at", "cancellation_feedback", ["created_at"])


def downgrade():
    bind = op.get_bind()
    # Paid Stars subscriptions, family members and gift commissions are financial/access records.
    for table, label in (("stars_subscriptions", "Telegram Stars subscriptions"), ("family_members", "family members")):
        if bind.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError(f"{label} exist; downgrade below 0076 would delete them")
    if bind.execute(sa.text("SELECT 1 FROM partner_commissions WHERE gift_code_id IS NOT NULL OR payment_id IS NULL LIMIT 1")).first():
        raise RuntimeError("Gift partner commissions exist; downgrade below 0076 would delete them")
    for table in ("cancellation_feedback", "family_members", "family_groups", "stars_subscriptions", "remnawave_events"):
        op.drop_table(table)
    with op.batch_alter_table("partner_commissions") as batch:
        # Dropping the column drops its foreign key and unique constraint whatever they are named.
        batch.drop_column("gift_code_id")
        batch.alter_column("payment_id", existing_type=sa.Integer(), nullable=False)
    with op.batch_alter_table("trial_grants") as batch:
        batch.drop_index("ix_trial_grants_ip_hash")
        batch.drop_column("ip_hash")
    with op.batch_alter_table("plans") as batch:
        batch.drop_column("family_seats")
