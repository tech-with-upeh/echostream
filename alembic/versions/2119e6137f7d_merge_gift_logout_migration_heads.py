"""merge gift logout migration heads

Revision ID: 2119e6137f7d
Revises: 93cd3f207615, 20260901_per_session_auth
Create Date: 2026-09-01 22:44:16.175993

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2119e6137f7d'
down_revision: Union[str, None] = ('93cd3f207615', '20260901_per_session_auth')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
