"""Mail domain health: DMARC aggregate reports and the read-only report mailbox cursor."""
from alembic import op
import sqlalchemy as sa

revision = "0069_mail_domain"
down_revision = "0068_network_intel"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "dmarc_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("org_name", sa.String(255), nullable=False),
        sa.Column("report_id", sa.String(255), nullable=False),
        sa.Column("reporter_email", sa.String(255)),
        sa.Column("sender_matches", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("domain", sa.String(255), nullable=False),
        sa.Column("policy", sa.String(16)),
        sa.Column("pct", sa.Integer()),
        sa.Column("date_begin", sa.DateTime(), nullable=False),
        sa.Column("date_end", sa.DateTime(), nullable=False),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("messages", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("passed", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("failed", sa.BigInteger(), nullable=False, server_default="0"),
        sa.UniqueConstraint("org_name", "report_id", name="uq_dmarc_reports_org_report"),
    )
    op.create_index("ix_dmarc_reports_date_end", "dmarc_reports", ["date_end"])
    op.create_table(
        "dmarc_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("report_row_id", sa.Integer(), sa.ForeignKey("dmarc_reports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_ip", sa.String(45), nullable=False),
        sa.Column("count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("disposition", sa.String(16)),
        sa.Column("dkim", sa.String(8)),
        sa.Column("spf", sa.String(8)),
        sa.Column("header_from", sa.String(255)),
        sa.Column("dkim_domain", sa.String(255)),
        sa.Column("dkim_result", sa.String(16)),
        sa.Column("spf_domain", sa.String(255)),
        sa.Column("spf_result", sa.String(16)),
    )
    op.create_index("ix_dmarc_records_report_row_id", "dmarc_records", ["report_row_id"])
    op.create_index("ix_dmarc_records_source_ip", "dmarc_records", ["source_ip"])
    op.create_table(
        "dmarc_intake_state",
        sa.Column("mailbox", sa.String(64), primary_key=True),
        sa.Column("uidvalidity", sa.BigInteger()),
        sa.Column("last_uid", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("last_success", sa.DateTime()),
        sa.Column("last_error", sa.String(255)),
        sa.Column("last_error_at", sa.DateTime()),
        sa.Column("imported", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duplicates", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rejected", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("journal", sa.JSON()),
    )


def downgrade():
    # Reports are re-readable from the report mailbox only while it keeps them, so a
    # downgrade with stored reports would silently lose history: refuse it.
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT COUNT(*) FROM dmarc_reports")).scalar():
        raise RuntimeError("DMARC reports exist; erase them in the admin panel before downgrading 0069")
    op.drop_table("dmarc_intake_state")
    op.drop_table("dmarc_records")
    op.drop_table("dmarc_reports")
