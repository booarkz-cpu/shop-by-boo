"""Mini App configuration: offer consents and Telegram Stars invoice amounts."""
from alembic import op
import sqlalchemy as sa

revision = "0075_app_config"
down_revision = "0074_automation_engine"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "user_consents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document", sa.String(32), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("source", sa.String(16), nullable=False, server_default="miniapp"),
        sa.Column("accepted_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_id", "document", "version", name="uq_user_consents_user_document_version"),
    )
    op.create_index("ix_user_consents_user_id", "user_consents", ["user_id"])
    with op.batch_alter_table("payments") as batch:
        batch.add_column(sa.Column("stars_amount", sa.Integer()))


def downgrade():
    bind = op.get_bind()
    # Accepted offers are legal evidence and Stars payments cannot be re-priced: keep them.
    if bind.execute(sa.text("SELECT 1 FROM user_consents LIMIT 1")).first():
        raise RuntimeError("Offer consents exist; downgrade below 0075 would delete them")
    if bind.execute(sa.text("SELECT 1 FROM payments WHERE stars_amount IS NOT NULL LIMIT 1")).first():
        raise RuntimeError("Telegram Stars payments exist; downgrade below 0075 would lose their amounts")
    with op.batch_alter_table("payments") as batch:
        batch.drop_column("stars_amount")
    op.drop_index("ix_user_consents_user_id", table_name="user_consents")
    op.drop_table("user_consents")
