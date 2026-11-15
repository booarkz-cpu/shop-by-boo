"""Keep support conversation history and retry identities."""
from alembic import op
import sqlalchemy as sa

revision = "0043_support_conversations"
down_revision = "0042_workspace_withdrawals"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("support_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ticket_id", sa.Integer(), sa.ForeignKey("support_tickets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("ticket_id", "role", "idempotency_key", name="uq_support_message_retry"))
    op.create_index("ix_support_messages_ticket_id", "support_messages", ["ticket_id"])
    op.execute("""INSERT INTO support_messages (ticket_id, role, body, created_at)
        SELECT id, 'admin', admin_reply, updated_at FROM support_tickets
        WHERE admin_reply IS NOT NULL AND LENGTH(TRIM(admin_reply)) > 0""")


def downgrade():
    op.drop_index("ix_support_messages_ticket_id", table_name="support_messages")
    op.drop_table("support_messages")
