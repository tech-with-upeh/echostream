"""Add persistent TikTok gift catalog tables.

Revision ID: 0004_gift_catalog
Revises: 0003_event_alert_preferences
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0004_gift_catalog"
down_revision: Union[str, Sequence[str], None] = "0003_event_alert_preferences"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tiktok_gifts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tiktok_gift_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("diamond_count", sa.Integer(), nullable=True),
        sa.Column("type", sa.Integer(), nullable=True),
        sa.Column("image_url", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tiktok_gift_id"),
    )
    op.create_index("ix_tiktok_gifts_id", "tiktok_gifts", ["id"])
    op.create_index("ix_tiktok_gifts_tiktok_gift_id", "tiktok_gifts", ["tiktok_gift_id"])
    op.create_index("ix_tiktok_gifts_is_active", "tiktok_gifts", ["is_active"])

    op.create_table(
        "gift_catalog_sync",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("last_attempted_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_successful_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_successful_source", sa.String(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("catalog_version", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("gift_catalog_sync")
    op.drop_index("ix_tiktok_gifts_is_active", table_name="tiktok_gifts")
    op.drop_index("ix_tiktok_gifts_tiktok_gift_id", table_name="tiktok_gifts")
    op.drop_index("ix_tiktok_gifts_id", table_name="tiktok_gifts")
    op.drop_table("tiktok_gifts")
