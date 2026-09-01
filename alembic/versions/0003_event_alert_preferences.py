"""Replace legacy gift alert columns with unified event alerts.

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

LEGACY_COLUMNS = [
    "event_speech_enabled", "event_speech_template", "gift_alert_enabled", "gift_alert_type",
    "gift_tts_template", "gift_tts_voice", "gift_tts_provider", "gift_fish_voice_id",
    "gift_fish_model", "gift_system_sound_id", "gift_custom_audio_id", "gift_custom_audio_url",
    "gift_volume", "gift_speed",
]

def upgrade() -> None:
    op.add_column("user_preferences", sa.Column("event_alerts", sa.Text(), nullable=False, server_default="{}"))
    # Existing development installations are intentionally simplified rather than preserving
    # the redundant legacy representation. Specific gift overrides remain in gift_preferences.
    for column in LEGACY_COLUMNS:
        op.drop_column("user_preferences", column)

def downgrade() -> None:
    op.add_column("user_preferences", sa.Column("event_speech_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("user_preferences", sa.Column("event_speech_template", sa.String(), nullable=False, server_default="{{user}} sent {{event}}"))
    op.add_column("user_preferences", sa.Column("gift_alert_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("user_preferences", sa.Column("gift_alert_type", sa.String(), nullable=False, server_default="tts"))
    op.add_column("user_preferences", sa.Column("gift_tts_template", sa.String(), nullable=False, server_default="{{user}} sent {{gift}}"))
    op.add_column("user_preferences", sa.Column("gift_tts_voice", sa.String(), nullable=True))
    op.add_column("user_preferences", sa.Column("gift_tts_provider", sa.String(), nullable=True))
    op.add_column("user_preferences", sa.Column("gift_fish_voice_id", sa.String(), nullable=True))
    op.add_column("user_preferences", sa.Column("gift_fish_model", sa.String(), nullable=True))
    op.add_column("user_preferences", sa.Column("gift_system_sound_id", sa.String(), nullable=True))
    op.add_column("user_preferences", sa.Column("gift_custom_audio_id", sa.Integer(), nullable=True))
    op.add_column("user_preferences", sa.Column("gift_custom_audio_url", sa.String(), nullable=True))
    op.add_column("user_preferences", sa.Column("gift_volume", sa.Integer(), nullable=False, server_default="100"))
    op.add_column("user_preferences", sa.Column("gift_speed", sa.Integer(), nullable=False, server_default="100"))
    op.drop_column("user_preferences", "event_alerts")
