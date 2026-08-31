"""Add unified R2 audio assets and admin authorization.

Revision ID: 0002_audio_assets
Revises: 0001_initial
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_audio_assets"
down_revision: Union[str, Sequence[str], None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()))

    op.create_table(
        "audio_assets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("r2_key", sa.String(), nullable=False),
        sa.Column("public_url", sa.String(), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("r2_key"),
        sa.UniqueConstraint("public_url"),
    )
    op.create_index("ix_audio_assets_id", "audio_assets", ["id"], unique=False)
    op.create_index("ix_audio_assets_r2_key", "audio_assets", ["r2_key"], unique=True)
    op.create_index("ix_audio_assets_owner_user_id", "audio_assets", ["owner_user_id"], unique=False)

    op.add_column("user_preferences", sa.Column("gift_custom_audio_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_user_preferences_gift_custom_audio_id", "user_preferences", "audio_assets", ["gift_custom_audio_id"], ["id"], ondelete="SET NULL")
    op.add_column("gift_preferences", sa.Column("custom_audio_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_gift_preferences_custom_audio_id", "gift_preferences", "audio_assets", ["custom_audio_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    op.drop_constraint("fk_gift_preferences_custom_audio_id", "gift_preferences", type_="foreignkey")
    op.drop_column("gift_preferences", "custom_audio_id")
    op.drop_constraint("fk_user_preferences_gift_custom_audio_id", "user_preferences", type_="foreignkey")
    op.drop_column("user_preferences", "gift_custom_audio_id")
    op.drop_index("ix_audio_assets_owner_user_id", table_name="audio_assets")
    op.drop_index("ix_audio_assets_r2_key", table_name="audio_assets")
    op.drop_index("ix_audio_assets_id", table_name="audio_assets")
    op.drop_table("audio_assets")
    op.drop_column("users", "is_admin")
