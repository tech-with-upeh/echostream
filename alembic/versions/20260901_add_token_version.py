"""add token version for access-token revocation

Revision ID: 20260901_add_token_version
Revises: 184c1929a911
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260901_add_token_version"
down_revision: Union[str, Sequence[str], None] = "184c1929a911"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("users", "token_version")
