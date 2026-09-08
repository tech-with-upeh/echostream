"""add redeem codes, voucher credit balances and ledger

Revision ID: 20260908_redeem_vouchers
Revises: 20260907_nullable_old_sub
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260908_redeem_vouchers"
down_revision: Union[str, Sequence[str], None] = "20260907_nullable_old_sub"
branch_labels: Union[str, Sequence[str], None] = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "redeem_codes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code_hash", sa.String(), nullable=False),
        sa.Column("code_prefix", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("plan", sa.String(), nullable=True),
        sa.Column("duration_days", sa.Integer(), nullable=True),
        sa.Column("credit_kobo", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_redemptions", sa.Integer(), nullable=True),
        sa.Column("redemption_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_redeem_codes_code_hash", "redeem_codes", ["code_hash"], unique=True)
    op.create_index("ix_redeem_codes_code_prefix", "redeem_codes", ["code_prefix"])
    op.create_index("ix_redeem_codes_kind", "redeem_codes", ["kind"])
    op.create_index("ix_redeem_codes_plan", "redeem_codes", ["plan"])
    op.create_index("ix_redeem_codes_expires_at", "redeem_codes", ["expires_at"])
    op.create_index("ix_redeem_codes_is_active", "redeem_codes", ["is_active"])
    op.create_index("ix_redeem_codes_created_by", "redeem_codes", ["created_by"])

    op.create_table(
        "redeem_code_redemptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("redeem_code_id", sa.Integer(), sa.ForeignKey("redeem_codes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="consumed"),
        sa.Column("plan", sa.String(), nullable=True),
        sa.Column("duration_days", sa.Integer(), nullable=True),
        sa.Column("credit_kobo", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("checkout_reference", sa.String(), nullable=True),
        sa.Column("redeemed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("redeem_code_id", "user_id"),
        sa.UniqueConstraint("checkout_reference"),
    )
    op.create_index("ix_redeem_code_redemptions_redeem_code_id", "redeem_code_redemptions", ["redeem_code_id"])
    op.create_index("ix_redeem_code_redemptions_user_id", "redeem_code_redemptions", ["user_id"])
    op.create_index("ix_redeem_code_redemptions_status", "redeem_code_redemptions", ["status"])
    op.create_index("ix_redeem_code_redemptions_checkout_reference", "redeem_code_redemptions", ["checkout_reference"])

    op.create_table(
        "user_credits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("balance_kobo", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index("ix_user_credits_user_id", "user_credits", ["user_id"])

    op.create_table(
        "user_credit_ledger",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("amount_kobo", sa.Integer(), nullable=False),
        sa.Column("balance_after_kobo", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("reference", sa.String(), nullable=False),
        sa.Column("redeem_code_id", sa.Integer(), sa.ForeignKey("redeem_codes.id", ondelete="SET NULL"), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("reference"),
    )
    op.create_index("ix_user_credit_ledger_user_id", "user_credit_ledger", ["user_id"])
    op.create_index("ix_user_credit_ledger_reference", "user_credit_ledger", ["reference"], unique=True)
    op.create_index("ix_user_credit_ledger_redeem_code_id", "user_credit_ledger", ["redeem_code_id"])


def downgrade() -> None:
    op.drop_index("ix_user_credit_ledger_redeem_code_id", table_name="user_credit_ledger")
    op.drop_index("ix_user_credit_ledger_reference", table_name="user_credit_ledger")
    op.drop_index("ix_user_credit_ledger_user_id", table_name="user_credit_ledger")
    op.drop_table("user_credit_ledger")
    op.drop_index("ix_user_credits_user_id", table_name="user_credits")
    op.drop_table("user_credits")
    op.drop_index("ix_redeem_code_redemptions_checkout_reference", table_name="redeem_code_redemptions")
    op.drop_index("ix_redeem_code_redemptions_status", table_name="redeem_code_redemptions")
    op.drop_index("ix_redeem_code_redemptions_user_id", table_name="redeem_code_redemptions")
    op.drop_index("ix_redeem_code_redemptions_redeem_code_id", table_name="redeem_code_redemptions")
    op.drop_table("redeem_code_redemptions")
    op.drop_index("ix_redeem_codes_created_by", table_name="redeem_codes")
    op.drop_index("ix_redeem_codes_is_active", table_name="redeem_codes")
    op.drop_index("ix_redeem_codes_expires_at", table_name="redeem_codes")
    op.drop_index("ix_redeem_codes_plan", table_name="redeem_codes")
    op.drop_index("ix_redeem_codes_kind", table_name="redeem_codes")
    op.drop_index("ix_redeem_codes_code_prefix", table_name="redeem_codes")
    op.drop_index("ix_redeem_codes_code_hash", table_name="redeem_codes")
    op.drop_table("redeem_codes")
