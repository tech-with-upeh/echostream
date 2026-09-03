"""Add stable EchoStream payment and receipt identifiers.

Revision ID: 20260903_payment_identity
Revises: 20260903_payment_history
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260903_payment_identity"
down_revision: Union[str, Sequence[str], None] = "20260903_payment_history"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("payment_history", sa.Column("payment_id", sa.String(), nullable=True))
    op.add_column("payment_history", sa.Column("receipt_number", sa.String(), nullable=True))
    op.add_column("payment_history", sa.Column("provider", sa.String(), nullable=True))
    op.add_column("payment_history", sa.Column("provider_reference", sa.String(), nullable=True))
    op.add_column("payment_history", sa.Column("billing_type", sa.String(), nullable=True))
    op.add_column("payment_history", sa.Column("method", sa.String(), nullable=True))

    op.execute(
        sa.text(
            """
            UPDATE payment_history
            SET
                payment_id = 'ES-PAY-' || id::text,
                receipt_number = 'ES-RCP-' || lpad(id::text, 8, '0'),
                provider = 'paystack',
                provider_reference = reference,
                billing_type = CASE
                    WHEN payment_method = 'recurring' THEN 'recurring'
                    ELSE 'one_time'
                END,
                method = CASE
                    WHEN lower(coalesce(channel, '')) IN ('card', 'bank', 'bank_transfer', 'ussd', 'qr', 'mobile_money')
                        THEN lower(channel)
                    ELSE NULL
                END
            WHERE payment_id IS NULL
            """
        )
    )

    op.alter_column("payment_history", "payment_id", nullable=False)
    op.alter_column("payment_history", "receipt_number", nullable=False)
    op.alter_column("payment_history", "provider", nullable=False)
    op.alter_column("payment_history", "provider_reference", nullable=False)
    op.alter_column("payment_history", "billing_type", nullable=False)

    op.create_unique_constraint("uq_payment_history_payment_id", "payment_history", ["payment_id"])
    op.create_unique_constraint("uq_payment_history_receipt_number", "payment_history", ["receipt_number"])
    op.create_index("ix_payment_history_payment_id", "payment_history", ["payment_id"], unique=False)
    op.create_index("ix_payment_history_receipt_number", "payment_history", ["receipt_number"], unique=False)
    op.create_index("ix_payment_history_provider_reference", "payment_history", ["provider_reference"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_payment_history_provider_reference", table_name="payment_history")
    op.drop_index("ix_payment_history_receipt_number", table_name="payment_history")
    op.drop_index("ix_payment_history_payment_id", table_name="payment_history")
    op.drop_constraint("uq_payment_history_receipt_number", "payment_history", type_="unique")
    op.drop_constraint("uq_payment_history_payment_id", "payment_history", type_="unique")
    op.drop_column("payment_history", "method")
    op.drop_column("payment_history", "billing_type")
    op.drop_column("payment_history", "provider_reference")
    op.drop_column("payment_history", "provider")
    op.drop_column("payment_history", "receipt_number")
    op.drop_column("payment_history", "payment_id")
