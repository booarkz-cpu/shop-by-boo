"""v28.71: Telegram bot state (stage 13) — the bot process reports its connection to Telegram.

See docs/ru/new/TELEGRAM_GUIDE.md. One row: who the bot is (getMe), when Telegram last answered, the last update and
error, and the commands applied from the admin panel. The token itself lives in the runtime settings (encrypted)."""
from alembic import op
import sqlalchemy as sa

revision = "0092_telegram_bot"
down_revision = "0091_remnawave_domains"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "telegram_bot_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("bot_id", sa.BigInteger()),
        sa.Column("username", sa.String(64)),
        sa.Column("first_name", sa.String(128)),
        sa.Column("token_fingerprint", sa.String(16)),
        sa.Column("state", sa.String(16), nullable=False, server_default="idle"),
        sa.Column("started_at", sa.DateTime()),
        sa.Column("last_ok_at", sa.DateTime()),
        sa.Column("last_update_at", sa.DateTime()),
        sa.Column("updates_total", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text()),
        sa.Column("last_error_at", sa.DateTime()),
        sa.Column("commands", sa.JSON()),
        sa.Column("commands_applied_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade():
    op.drop_table("telegram_bot_state")
