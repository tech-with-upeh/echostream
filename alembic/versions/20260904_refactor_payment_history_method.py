"""Refactor payment history payment-method fields.

Revision ID: 20260904_payment_history_method
Revises: 20260903_payment_identity_trg
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260904_payment_history_method"
down_revision: Union[str, Sequence[str], None] = "20260903_payment_identity_trg"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("payment_history", sa.Column("method_brand", sa.String(), nullable=True))
    op.add_column("payment_history", sa.Column("method_last4", sa.String(), nullable=True))

    # Move the actual payment channel into the single `method` field before
    # removing the old duplicate channel/payment_method columns.
    op.execute(
        sa.text(
            """
            UPDATE payment_history
            SET method = lower(channel)
            WHERE channel IS NOT NULL
              AND trim(channel) <> ''
              AND (method IS NULL OR trim(method) = '')
            """
        )
    )

    # Normalize the old billing classification values used by earlier writes.
    op.execute(sa.text("UPDATE payment_history SET billing_type = 'recurring' WHERE lower(billing_type) IN ('recurring', 'reoccuring');"))
    op.execute(sa.text("UPDATE payment_history SET billing_type = 'one_time' WHERE lower(billing_type) IN ('one_time', 'onetime');"))
    op.execute(sa.text("UPDATE payment_history SET billing_type = 'recurring' WHERE lower(payment_method) = 'recurring' AND (billing_type IS NULL OR lower(billing_type) NOT IN ('recurring', 'one_time'));"))
    op.execute(sa.text("UPDATE payment_history SET billing_type = 'one_time' WHERE billing_type IS NULL OR trim(billing_type) = '';"))

    # The database trigger from the previous payment-identity migration refers
    # to channel/payment_method, so remove it before dropping those columns.
    op.execute("DROP TRIGGER IF EXISTS trg_payment_history_identity ON payment_history;")
    op.execute("DROP FUNCTION IF EXISTS populate_payment_identity();")

    op.drop_column("payment_history", "channel")
    op.drop_column("payment_history", "payment_method")


def downgrade() -> None:
    op.add_column("payment_history", sa.Column("channel", sa.String(), nullable=True))
    op.add_column("payment_history", sa.Column("payment_method", sa.String(), nullable=True))
    op.execute(sa.text("UPDATE payment_history SET channel = method, payment_method = billing_type;"))
    op.drop_column("payment_history", "method_last4")
    op.drop_column("payment_history", "method_brand")
