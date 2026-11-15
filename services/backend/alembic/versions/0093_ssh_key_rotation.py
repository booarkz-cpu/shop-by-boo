"""v28.75: SSH key rotation for the servers of the Remnawave wizard (stage 16).

See docs/ru/new/SECRETS_MANAGEMENT.md. The shop keeps its own Ed25519 key per server: the fingerprint of its public
half, the comment (``corgi-shop-<server>-<time>-<random>``) that marks its line in ``authorized_keys`` so the next rotation
removes exactly it, and when it was made."""
from alembic import op
import sqlalchemy as sa

revision = "0093_ssh_key_rotation"
down_revision = "0092_telegram_bot"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("remnawave_servers", sa.Column("ssh_key_fingerprint", sa.String(64)))
    op.add_column("remnawave_servers", sa.Column("ssh_key_marker", sa.String(80)))
    op.add_column("remnawave_servers", sa.Column("ssh_key_rotated_at", sa.DateTime()))


def downgrade():
    op.drop_column("remnawave_servers", "ssh_key_rotated_at")
    op.drop_column("remnawave_servers", "ssh_key_marker")
    op.drop_column("remnawave_servers", "ssh_key_fingerprint")
