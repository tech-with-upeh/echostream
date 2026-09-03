"""cleanup legacy event preferences

Revision ID: adab87076c3b
Revises: 0003_event_alert_preferences
Create Date: 2026-09-01 18:27:20.290088

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'adab87076c3b'
down_revision: Union[str, None] = '0003_event_alert_preferences'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # No-op: 0003_event_alert_preferences already dropped these legacy columns
    # (event_speech_enabled, gift_alert_enabled, gift_custom_audio_id, etc.)
    # and their supporting FK. This migration was originally auto-generated
    # against a local database that hadn't applied 0003 yet, which produced a
    # duplicate diff. Kept as a no-op so the revision chain and the later
    # merge migration that depends on it remain intact.
    pass


def downgrade() -> None:
    # No-op for the same reason — 0003's downgrade() already restores these
    # columns when stepping below that revision.
    pass