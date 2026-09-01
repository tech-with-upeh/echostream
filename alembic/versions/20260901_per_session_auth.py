"""replace global token version with per-session auth

Revision ID: 20260901_per_session_auth
Revises: 20260901_add_token_version
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260901_per_session_auth"
down_revision: Union[str, Sequence[str], None] = "20260901_add_token_version"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])
    op.create_index("ix_user_sessions_revoked_at", "user_sessions", ["revoked_at"])

    op.add_column(
        "refresh_tokens",
        sa.Column("session_id", sa.String(), nullable=True),
    )
    op.create_index("ix_refresh_tokens_session_id", "refresh_tokens", ["session_id"])

    # Existing refresh tokens were created before per-session IDs existed.
    # They cannot be safely associated with a session, so revoke them during
    # the migration. Users will simply log in again after deployment.
    op.execute("DELETE FROM refresh_tokens")

    op.alter_column("refresh_tokens", "session_id", nullable=False)
    op.create_foreign_key(
        "fk_refresh_tokens_session_id_user_sessions",
        "refresh_tokens",
        "user_sessions",
        ["session_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_column("users", "token_version")


def downgrade() -> None:
    op.add_column(
        "users",
        sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.drop_constraint(
        "fk_refresh_tokens_session_id_user_sessions",
        "refresh_tokens",
        type_="foreignkey",
    )
    op.drop_index("ix_refresh_tokens_session_id", table_name="refresh_tokens")
    op.drop_column("refresh_tokens", "session_id")
    op.drop_index("ix_user_sessions_revoked_at", table_name="user_sessions")
    op.drop_index("ix_user_sessions_user_id", table_name="user_sessions")
    op.drop_table("user_sessions")
