"""Merge parallel heads

Revision ID: 54848436c361
Revises: 20260904_subscription_payment_details, e0a539bfa11b
Create Date: 2026-09-04 16:46:54.665730

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '54848436c361'
down_revision: Union[str, None] = ('20260904_sub_payment_details', 'e0a539bfa11b')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
