"""Node terminal: audited shell sessions through the node agent, transcripts and snippets."""
from alembic import op
import sqlalchemy as sa

revision = "0070_node_terminal"
down_revision = "0069_mail_domain"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("node_agents", sa.Column("terminal_ready", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table(
        "terminal_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("agent_id", sa.Integer(), nullable=False),
        sa.Column("agent_name", sa.String(80), nullable=False),
        sa.Column("admin_id", sa.Integer(), nullable=False),
        sa.Column("admin_email", sa.String(320), nullable=False),
        sa.Column("reason", sa.String(255), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("close_reason", sa.String(255)),
        sa.Column("agent_key_hash", sa.String(64)),
        sa.Column("client_ip", sa.String(64)),
        sa.Column("cols", sa.Integer(), nullable=False, server_default="120"),
        sa.Column("rows", sa.Integer(), nullable=False, server_default="32"),
        sa.Column("input_seq", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_seq", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("echo_off", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("bytes_in", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("bytes_out", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("exit_code", sa.Integer()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("claimed_at", sa.DateTime()),
        sa.Column("last_activity_at", sa.DateTime()),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("closed_at", sa.DateTime()),
    )
    op.create_index("ix_terminal_sessions_agent_id", "terminal_sessions", ["agent_id"])
    op.create_index("ix_terminal_sessions_admin_id", "terminal_sessions", ["admin_id"])
    op.create_index("ix_terminal_sessions_status", "terminal_sessions", ["status"])
    op.create_index("ix_terminal_sessions_created_at", "terminal_sessions", ["created_at"])
    op.create_table(
        "terminal_chunks",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("terminal_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("direction", sa.String(8), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("data_encrypted", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_terminal_chunks_session_id", "terminal_chunks", ["session_id"])
    op.create_table(
        "terminal_snippets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("command", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(320), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade():
    # Transcripts are the audit trail of shell access to nodes: never drop them silently.
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT COUNT(*) FROM terminal_sessions")).scalar():
        raise RuntimeError("Terminal sessions exist; their audit transcripts would be lost by downgrading 0070")
    op.drop_table("terminal_snippets")
    op.drop_table("terminal_chunks")
    op.drop_table("terminal_sessions")
    op.drop_column("node_agents", "terminal_ready")
