"""Add payment_history table for tracking each successful/failed charge.

Revision ID: 20260903_payment_history
Revises: 2119e6137f7d
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260903_payment_history"
down_revision: Union[str, Sequence[str], None] = "2119e6137f7d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "payment_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("subscription_id", sa.Integer(), nullable=True),
        sa.Column("reference", sa.String(), nullable=False),
        sa.Column("plan", sa.String(), nullable=False),
        sa.Column("interval", sa.String(), nullable=True),
        sa.Column("amount", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(), nullable=False, server_default="NGN"),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("channel", sa.String(), nullable=True),
        sa.Column("payment_method", sa.String(), nullable=True),
        sa.Column("event", sa.String(), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subscription_id"], ["subscriptions.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("reference"),
    )
    op.create_index("ix_payment_history_id", "payment_history", ["id"], unique=False)
    op.create_index("ix_payment_history_user_id", "payment_history", ["user_id"], unique=False)
    op.create_index("ix_payment_history_subscription_id", "payment_history", ["subscription_id"], unique=False)
    op.create_index("ix_payment_history_reference", "payment_history", ["reference"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_payment_history_reference", table_name="payment_history")
    op.drop_index("ix_payment_history_subscription_id", table_name="payment_history")
    op.drop_index("ix_payment_history_user_id", table_name="payment_history")
    op.drop_index("ix_payment_history_id", table_name="payment_history")
    op.drop_table("payment_history")