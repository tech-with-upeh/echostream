"""add help chat persistence and full-text retrieval index

Revision ID: 42f6f046783e
Revises: 20261002_add_notifications, f5a445515f5b
"""

from alembic import op
import sqlalchemy as sa

revision = "42f6f046783e"
down_revision = ("20261002_add_notifications", "f5a445515f5b")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "help_conversations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("public_id"),
        sa.CheckConstraint("status IN ('active', 'closed')", name="ck_help_conversations_status"),
    )
    op.create_index("ix_help_conversations_id", "help_conversations", ["id"])
    op.create_index("ix_help_conversations_public_id", "help_conversations", ["public_id"], unique=True)
    op.create_index("ix_help_conversations_user_id", "help_conversations", ["user_id"])
    op.create_index("ix_help_conversations_status", "help_conversations", ["status"])
    op.create_index("ix_help_conversations_last_message_at", "help_conversations", ["last_message_at"])
    op.create_index("ix_help_conversations_user_last_message", "help_conversations", ["user_id", "last_message_at"])

    op.create_table(
        "help_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("provider", sa.String(length=50), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["help_conversations.id"], ondelete="CASCADE"),
        sa.CheckConstraint("role IN ('user', 'assistant', 'system')", name="ck_help_messages_role"),
    )
    op.create_index("ix_help_messages_id", "help_messages", ["id"])
    op.create_index("ix_help_messages_conversation_id", "help_messages", ["conversation_id"])
    op.create_index("ix_help_messages_role", "help_messages", ["role"])
    op.create_index("ix_help_messages_created_at", "help_messages", ["created_at"])
    op.create_index("ix_help_messages_conversation_created", "help_messages", ["conversation_id", "created_at"])

    op.execute("""
        CREATE INDEX ix_help_articles_fts
        ON help_articles
        USING GIN (
            (
                setweight(to_tsvector('english', coalesce(title, '')), 'A')
                ||
                setweight(to_tsvector('english', coalesce(search_keywords, '')), 'A')
                ||
                setweight(to_tsvector('english', coalesce(excerpt, '')), 'B')
                ||
                setweight(to_tsvector('english', coalesce(content, '')), 'C')
            )
        )
        WHERE is_published = true
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_help_articles_fts")
    op.drop_index("ix_help_messages_conversation_created", table_name="help_messages")
    op.drop_index("ix_help_messages_created_at", table_name="help_messages")
    op.drop_index("ix_help_messages_role", table_name="help_messages")
    op.drop_index("ix_help_messages_conversation_id", table_name="help_messages")
    op.drop_index("ix_help_messages_id", table_name="help_messages")
    op.drop_table("help_messages")
    op.drop_index("ix_help_conversations_user_last_message", table_name="help_conversations")
    op.drop_index("ix_help_conversations_last_message_at", table_name="help_conversations")
    op.drop_index("ix_help_conversations_status", table_name="help_conversations")
    op.drop_index("ix_help_conversations_user_id", table_name="help_conversations")
    op.drop_index("ix_help_conversations_public_id", table_name="help_conversations")
    op.drop_index("ix_help_conversations_id", table_name="help_conversations")
    op.drop_table("help_conversations")
