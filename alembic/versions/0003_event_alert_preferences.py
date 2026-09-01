"""Add per-event alert preferences.

Revision ID: 0003_event_alert_preferences
Revises: 0002_audio_assets
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_event_alert_preferences"
down_revision: Union[str, Sequence[str], None] = "0002_audio_assets"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user_preferences",
        sa.Column("event_alerts", sa.Text(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("user_preferences", "event_alerts")
