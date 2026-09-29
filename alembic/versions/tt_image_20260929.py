"""add TikTok profile image to users

Revision ID: tt_image_20260929
Revises: 3957bc6acd4f
Create Date: 2026-09-29
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "tt_image_20260929"
down_revision: Union[str, None] = "3957bc6acd4f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("tt_image", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "tt_image")
