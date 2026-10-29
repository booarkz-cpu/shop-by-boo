"""v28.52: support ratings (CSAT) and NPS answers (feedback.py)."""
from alembic import op
import sqlalchemy as sa

revision = "0086_feedback"
down_revision = "0085_loyalty"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "feedback_ratings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, nullable=False),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("ticket_id", sa.Integer),
        sa.Column("period", sa.String(16)),
        sa.Column("operator", sa.String(320)),
        sa.Column("score", sa.Integer, nullable=False),
        sa.Column("comment", sa.Text),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("kind", "ticket_id", name="uq_feedback_ticket"),
        sa.UniqueConstraint("kind", "user_id", "period", name="uq_feedback_wave"),
    )
    op.create_index("ix_feedback_ratings_user_id", "feedback_ratings", ["user_id"])
    op.create_index("ix_feedback_ratings_created_at", "feedback_ratings", ["created_at"])


def downgrade():
    # Customer answers are statistics the owner keeps: refuse while any exist.
    if op.get_bind().execute(sa.text("SELECT 1 FROM feedback_ratings LIMIT 1")).first():
        raise RuntimeError("Есть оценки клиентов: выгрузите их перед откатом миграции 0086")
    op.drop_table("feedback_ratings")
