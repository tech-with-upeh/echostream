"""Generate payment identity fields for Core and ORM inserts.

Revision ID: 20260903_payment_identity_trg
Revises: 20260903_payment_identity
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260903_payment_identity_trg"
down_revision: Union[str, Sequence[str], None] = "20260903_payment_identity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION populate_payment_identity()
        RETURNS trigger AS $$
        BEGIN
            IF NEW.payment_id IS NULL OR NEW.payment_id = '' THEN
                NEW.payment_id := 'ES-PAY-' || md5(random()::text || clock_timestamp()::text || coalesce(NEW.reference, ''));
            END IF;

            IF NEW.receipt_number IS NULL OR NEW.receipt_number = '' THEN
                NEW.receipt_number := 'ES-RCP-' || md5(random()::text || clock_timestamp()::text || coalesce(NEW.reference, ''));
            END IF;

            IF NEW.provider IS NULL OR NEW.provider = '' THEN
                NEW.provider := 'paystack';
            END IF;

            IF NEW.provider_reference IS NULL OR NEW.provider_reference = '' THEN
                NEW.provider_reference := NEW.reference;
            END IF;

            IF NEW.billing_type IS NULL OR NEW.billing_type = '' THEN
                NEW.billing_type := CASE
                    WHEN NEW.payment_method = 'recurring' THEN 'recurring'
                    ELSE 'one_time'
                END;
            END IF;

            IF NEW.method IS NULL OR NEW.method = '' THEN
                IF lower(coalesce(NEW.channel, '')) IN ('card', 'bank', 'bank_transfer', 'ussd', 'qr', 'mobile_money') THEN
                    NEW.method := lower(NEW.channel);
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_payment_history_identity
        BEFORE INSERT ON payment_history
        FOR EACH ROW
        EXECUTE FUNCTION populate_payment_identity();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_payment_history_identity ON payment_history;")
    op.execute("DROP FUNCTION IF EXISTS populate_payment_identity();")
