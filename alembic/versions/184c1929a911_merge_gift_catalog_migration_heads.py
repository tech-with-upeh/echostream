"""merge gift catalog migration heads

Revision ID: 184c1929a911
Revises: adab87076c3b, 0004_gift_catalog
Create Date: 2026-09-01 20:22:37.654287

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '184c1929a911'
down_revision: Union[str, None] = ('adab87076c3b', '0004_gift_catalog')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
