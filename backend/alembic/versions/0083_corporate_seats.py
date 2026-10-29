"""v28.48: corporate plans — seats, a device pool, members with their own access, invoices to a company."""
from alembic import op
import sqlalchemy as sa

revision = "0083_corporate_seats"
down_revision = "0082_status_subscribers"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("corporate_accounts") as t:
        t.add_column(sa.Column("plan_id", sa.Integer))
        t.add_column(sa.Column("seats", sa.Integer, nullable=False, server_default="0"))
        t.add_column(sa.Column("devices_per_seat", sa.Integer, nullable=False, server_default="1"))
        t.add_column(sa.Column("seat_price", sa.Numeric(12, 2), nullable=False, server_default="0"))
        t.add_column(sa.Column("paid_until", sa.DateTime))
        t.add_column(sa.Column("invite_code", sa.String(32)))
        t.add_column(sa.Column("contact_email", sa.String(255)))
        t.add_column(sa.Column("kpp", sa.String(16)))
        t.add_column(sa.Column("legal_address", sa.Text))
        t.create_unique_constraint("uq_corporate_accounts_invite_code", ["invite_code"])
    op.create_table(
        "corporate_members",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("account_id", sa.Integer, sa.ForeignKey("corporate_accounts.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("user_id", sa.Integer, nullable=False, index=True),
        sa.Column("subscription_id", sa.Integer, index=True),
        sa.Column("role", sa.String(16), nullable=False, server_default="member"),
        sa.Column("devices", sa.Integer, nullable=False, server_default="1"),
        sa.Column("label", sa.String(120), nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("joined_at", sa.DateTime, nullable=False),
        sa.Column("removed_at", sa.DateTime),
        sa.Column("synced_at", sa.DateTime),
        sa.Column("sync_error", sa.Text),
        sa.UniqueConstraint("account_id", "user_id", name="uq_corporate_members_account_user"),
    )
    op.create_table(
        "corporate_invoices",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("account_id", sa.Integer, sa.ForeignKey("corporate_accounts.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("number", sa.String(40), nullable=False, unique=True),
        sa.Column("months", sa.Integer, nullable=False),
        sa.Column("seats", sa.Integer, nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="issued"),
        sa.Column("issued_at", sa.DateTime, nullable=False),
        sa.Column("paid_at", sa.DateTime),
    )


def downgrade():
    op.drop_table("corporate_invoices")
    op.drop_table("corporate_members")
    with op.batch_alter_table("corporate_accounts") as t:
        t.drop_constraint("uq_corporate_accounts_invite_code", type_="unique")
        for c in ("legal_address", "kpp", "contact_email", "invite_code", "paid_until", "seat_price", "devices_per_seat", "seats", "plan_id"):
            t.drop_column(c)
