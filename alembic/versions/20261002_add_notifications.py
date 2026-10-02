"""add notification_devices and notifications tables

Revision ID: 20261002_add_notifications
Revises: <<< FILL IN WITH CURRENT HEAD — run `alembic heads` >>>
Create Date: 2026-10-02
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20261002_add_notifications"
down_revision = "tt_image_20260929"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notification_devices",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("push_token", sa.String(), nullable=False),
        sa.Column("platform", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("app_version", sa.String(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("push_token"),
    )
    op.create_index(
        "ix_notification_devices_user_id", "notification_devices", ["user_id"]
    )
    op.create_index(
        "ix_notification_devices_push_token", "notification_devices", ["push_token"]
    )
    op.create_index(
        "ix_notification_devices_is_active", "notification_devices", ["is_active"]
    )

    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("data", sa.Text(), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
    op.create_index("ix_notifications_type", "notifications", ["type"])
    op.create_index("ix_notifications_created_at", "notifications", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_notifications_created_at", table_name="notifications")
    op.drop_index("ix_notifications_type", table_name="notifications")
    op.drop_index("ix_notifications_user_id", table_name="notifications")
    op.drop_table("notifications")

    op.drop_index(
        "ix_notification_devices_is_active", table_name="notification_devices"
    )
    op.drop_index(
        "ix_notification_devices_push_token", table_name="notification_devices"
    )
    op.drop_index(
        "ix_notification_devices_user_id", table_name="notification_devices"
    )
    op.drop_table("notification_devices")