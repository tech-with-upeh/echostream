"""make old_subscription_code nullable for one-time payment upgrades

Revision ID: 20260907_upgrade_old_sub_nullable
Revises: 20260906_subscription_upgrades
Create Date: 2026-09-07
"""
from alembic import op
import sqlalchemy as sa

revision = "20260907_nullable_old_sub"
down_revision = "20260906_drop_r2key_uq"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("subscription_upgrades", "old_subscription_code", existing_type=sa.String(), nullable=True)


def downgrade() -> None:
    op.alter_column("subscription_upgrades", "old_subscription_code", existing_type=sa.String(), nullable=False)
