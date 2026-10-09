"""Re-enable standard platform modules so installed features are available."""
from alembic import op

revision = "0041_enable_platform_modules"
down_revision = "0040_v20_payment_platform"
branch_labels = None
depends_on = None

def upgrade():
    op.execute("UPDATE platform_plugins SET enabled = TRUE WHERE key IN ('abuse','agent','webhooks','mail','metrics','torrents')")

def downgrade():
    return None
