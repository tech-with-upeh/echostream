"""Add immutable subscription upgrade records.

Revision ID: 20260906_subscription_upgrades
Revises: 20260904_payment_history_method
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260906_subscription_upgrades"
down_revision: Union[str, Sequence[str], None] = "20260904_payment_history_method"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "subscription_upgrades",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subscription_id", sa.Integer(), sa.ForeignKey("subscriptions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reference", sa.String(), nullable=False),
        sa.Column("payment_reference", sa.String(), nullable=True),
        sa.Column("old_plan", sa.String(), nullable=False),
        sa.Column("old_interval", sa.String(), nullable=False),
        sa.Column("old_subscription_code", sa.String(), nullable=False),
        sa.Column("old_authorization_code", sa.String(), nullable=True),
        sa.Column("old_period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("old_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("new_plan", sa.String(), nullable=False),
        sa.Column("new_interval", sa.String(), nullable=False),
        sa.Column("new_subscription_code", sa.String(), nullable=True),
        sa.Column("new_authorization_code", sa.String(), nullable=True),
        sa.Column("total_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("remaining_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("old_plan_price_kobo", sa.Integer(), nullable=False),
        sa.Column("new_plan_price_kobo", sa.Integer(), nullable=False),
        sa.Column("unused_value_kobo", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("upgrade_amount_kobo", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("credit_duration_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("first_debit", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payment_amount_kobo", sa.Integer(), nullable=True),
        sa.Column("payment_channel", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="pending_payment"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("reference"),
        sa.UniqueConstraint("payment_reference"),
    )
    op.create_index("ix_subscription_upgrades_user_id", "subscription_upgrades", ["user_id"])
    op.create_index("ix_subscription_upgrades_subscription_id", "subscription_upgrades", ["subscription_id"])
    op.create_index("ix_subscription_upgrades_payment_reference", "subscription_upgrades", ["payment_reference"])
    op.create_index("ix_subscription_upgrades_new_subscription_code", "subscription_upgrades", ["new_subscription_code"])
    op.create_index("ix_subscription_upgrades_status", "subscription_upgrades", ["status"])


def downgrade() -> None:
    op.drop_index("ix_subscription_upgrades_status", table_name="subscription_upgrades")
    op.drop_index("ix_subscription_upgrades_new_subscription_code", table_name="subscription_upgrades")
    op.drop_index("ix_subscription_upgrades_payment_reference", table_name="subscription_upgrades")
    op.drop_index("ix_subscription_upgrades_subscription_id", table_name="subscription_upgrades")
    op.drop_index("ix_subscription_upgrades_user_id", table_name="subscription_upgrades")
    op.drop_table("subscription_upgrades")
