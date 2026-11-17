"""Widen operators.totp_secret so an AES-GCM seed fits. Plaintext rows are left as they are."""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    # SQLite does not enforce VARCHAR length and rejects ALTER COLUMN TYPE.
    if op.get_bind().dialect.name == "sqlite":
        return
    op.alter_column("operators", "totp_secret", existing_type=sa.String(length=64), type_=sa.Text(), existing_nullable=True)


def downgrade():
    bound = op.get_bind()
    stored = bound.execute(sa.text(
        "SELECT 1 FROM operators WHERE totp_secret LIKE 'sp1:%' OR length(totp_secret) > 64 LIMIT 1"
    )).first()
    if stored:
        raise RuntimeError("Encrypted TOTP seeds exist; downgrade would truncate them")
    if bound.dialect.name == "sqlite":
        return
    op.alter_column("operators", "totp_secret", existing_type=sa.Text(), type_=sa.String(length=64), existing_nullable=True)
