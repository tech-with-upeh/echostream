"""Initial EchoStream schema.

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-31
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0001_initial"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("first_name", sa.String(), nullable=False),
        sa.Column("last_name", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("hashed_password", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("is_verified", sa.Boolean(), nullable=True),
        sa.Column("plan", sa.String(), nullable=False, server_default="starter"),
        sa.Column("subscription_status", sa.String(), nullable=False, server_default="active"),
        sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("subscription_ends_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_users_id", "users", ["id"], unique=False)
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token", sa.String(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_refresh_tokens_id", "refresh_tokens", ["id"], unique=False)
    op.create_index("ix_refresh_tokens_token", "refresh_tokens", ["token"], unique=True)

    op.create_table(
        "email_verification_codes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_email_verification_codes_id", "email_verification_codes", ["id"], unique=False)
    op.create_index("ix_email_verification_codes_email", "email_verification_codes", ["email"], unique=False)

    op.create_table(
        "pass_reset_verification_codes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("token", sa.String(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_pass_reset_verification_codes_id", "pass_reset_verification_codes", ["id"], unique=False)
    op.create_index("ix_pass_reset_verification_codes_email", "pass_reset_verification_codes", ["email"], unique=False)

    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("plan", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("paystack_customer_code", sa.String(), nullable=True),
        sa.Column("paystack_subscription_code", sa.String(), nullable=True),
        sa.Column("paystack_email_token", sa.String(), nullable=True),
        sa.Column("authorization_code", sa.String(), nullable=True),
        sa.Column("reference", sa.String(), nullable=True),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_at_period_end", sa.Boolean(), nullable=True),
        sa.Column("last_event", sa.String(), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id"),
        sa.UniqueConstraint("paystack_subscription_code"),
        sa.UniqueConstraint("reference"),
    )
    op.create_index("ix_subscriptions_id", "subscriptions", ["id"], unique=False)
    op.create_index("ix_subscriptions_paystack_customer_code", "subscriptions", ["paystack_customer_code"], unique=False)
    op.create_index("ix_subscriptions_paystack_subscription_code", "subscriptions", ["paystack_subscription_code"], unique=True)
    op.create_index("ix_subscriptions_reference", "subscriptions", ["reference"], unique=True)

    op.create_table(
        "user_preferences",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("tiktok_username", sa.String(), nullable=True),
        sa.Column("tts_provider", sa.String(), nullable=False, server_default="edge"),
        sa.Column("voice", sa.String(), nullable=False, server_default="en-US-GuyNeural"),
        sa.Column("fish_voice_id", sa.String(), nullable=True),
        sa.Column("fish_model", sa.String(), nullable=False, server_default="s2-pro"),
        sa.Column("pitch", sa.String(), nullable=False, server_default="+0Hz"),
        sa.Column("volume", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("speed", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("emoji_to_words", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("filter_profanity", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("require_command_prefix", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("max_message_length", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("comment_speech_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("comment_speech_template", sa.String(), nullable=False, server_default="{{user}} said {{comment}}"),
        sa.Column("event_speech_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("event_speech_template", sa.String(), nullable=False, server_default="{{user}} sent {{gift}}"),
        sa.Column("gift_alert_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("gift_alert_type", sa.String(), nullable=False, server_default="tts"),
        sa.Column("gift_tts_template", sa.String(), nullable=False, server_default="{{user}} sent {{gift}}"),
        sa.Column("gift_tts_voice", sa.String(), nullable=True),
        sa.Column("gift_tts_provider", sa.String(), nullable=True),
        sa.Column("gift_fish_voice_id", sa.String(), nullable=True),
        sa.Column("gift_fish_model", sa.String(), nullable=True),
        sa.Column("gift_system_sound_id", sa.String(), nullable=True),
        sa.Column("gift_custom_audio_url", sa.String(), nullable=True),
        sa.Column("gift_volume", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("gift_speed", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("allowed_user_types", sa.String(), nullable=False, server_default='["all"]'),
        sa.Column("minimum_account_age_days", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("blocked_words", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("spam_protection_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("block_repeated_words", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("auto_mute_repeat_offenders", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("spam_cooldown_seconds", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("spam_max_requests_per_minute", sa.Integer(), nullable=False, server_default="10"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index("ix_user_preferences_id", "user_preferences", ["id"], unique=False)

    op.create_table(
        "gift_preferences",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("gift_id", sa.String(), nullable=False),
        sa.Column("gift_name", sa.String(), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("alert_type", sa.String(), nullable=False, server_default="tts"),
        sa.Column("tts_template", sa.String(), nullable=True),
        sa.Column("tts_provider", sa.String(), nullable=True),
        sa.Column("voice", sa.String(), nullable=True),
        sa.Column("fish_voice_id", sa.String(), nullable=True),
        sa.Column("fish_model", sa.String(), nullable=True),
        sa.Column("system_sound_id", sa.String(), nullable=True),
        sa.Column("custom_audio_url", sa.String(), nullable=True),
        sa.Column("volume", sa.Integer(), nullable=True),
        sa.Column("speed", sa.Integer(), nullable=True),
        sa.Column("pitch", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_gift_preferences_id", "gift_preferences", ["id"], unique=False)
    op.create_index("ix_gift_preferences_owner_id", "gift_preferences", ["owner_id"], unique=False)

    op.create_table(
        "fish_voices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("voice_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("model", sa.String(), nullable=False, server_default="s2-pro"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_fish_voices_id", "fish_voices", ["id"], unique=False)
    op.create_index("ix_fish_voices_user_id", "fish_voices", ["user_id"], unique=False)
    op.create_index("ix_fish_voices_voice_id", "fish_voices", ["voice_id"], unique=True)

    op.create_table(
        "muted_users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("tiktok_user_id", sa.String(), nullable=True),
        sa.Column("tiktok_username", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False, server_default="manual"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_muted_users_id", "muted_users", ["id"], unique=False)
    op.create_index("ix_muted_users_owner_id", "muted_users", ["owner_id"], unique=False)
    op.create_index("ix_muted_users_tiktok_user_id", "muted_users", ["tiktok_user_id"], unique=False)


def downgrade() -> None:
    op.drop_table("muted_users")
    op.drop_table("fish_voices")
    op.drop_table("gift_preferences")
    op.drop_table("user_preferences")
    op.drop_table("subscriptions")
    op.drop_table("pass_reset_verification_codes")
    op.drop_table("email_verification_codes")
    op.drop_table("refresh_tokens")
    op.drop_table("users")
