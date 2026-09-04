"""Add current payment authorization details to subscriptions.

Revision ID: 20260904_subscription_payment_details
Revises: 20260904_payment_history_method
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260904_subscription_payment_details"
down_revision: Union[str, Sequence[str], None] = "20260904_payment_history_method"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("subscriptions", sa.Column("payment_method", sa.String(), nullable=True))
    op.add_column("subscriptions", sa.Column("payment_method_brand", sa.String(), nullable=True))
    op.add_column("subscriptions", sa.Column("payment_method_last4", sa.String(), nullable=True))
    op.add_column("subscriptions", sa.Column("payment_method_bank", sa.String(), nullable=True))
    op.add_column("subscriptions", sa.Column("payment_method_card_type", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("subscriptions", "payment_method_card_type")
    op.drop_column("subscriptions", "payment_method_bank")
    op.drop_column("subscriptions", "payment_method_last4")
    op.drop_column("subscriptions", "payment_method_brand")
    op.drop_column("subscriptions", "payment_method")
