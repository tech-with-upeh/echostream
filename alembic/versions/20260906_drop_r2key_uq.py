"""Drop redundant duplicate unique constraint on audio_assets.r2_key.

r2_key was covered by two separate objects: the named unique index
ix_audio_assets_r2_key and a separate UniqueConstraint (Postgres-named
audio_assets_r2_key_key). The named index alone fully enforces uniqueness,
so the constraint is redundant.

Revision ID: 20260906_drop_r2key_uq
Revises: 20260906_subscription_upgrades
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260906_drop_r2key_uq"
down_revision: Union[str, Sequence[str], None] = "20260906_subscription_upgrades"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("audio_assets_r2_key_key", "audio_assets", type_="unique")


def downgrade() -> None:
    op.create_unique_constraint("audio_assets_r2_key_key", "audio_assets", ["r2_key"])
