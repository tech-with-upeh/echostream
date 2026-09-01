"""Add per-event alert preferences.

Revision ID: 0003_event_alert_preferences
Revises: 8086d5910b34
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_event_alert_preferences"
down_revision: Union[str, Sequence[str], None] = "8086d5910b34"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user_preferences",
        sa.Column("event_alerts", sa.Text(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("user_preferences", "event_alerts")
