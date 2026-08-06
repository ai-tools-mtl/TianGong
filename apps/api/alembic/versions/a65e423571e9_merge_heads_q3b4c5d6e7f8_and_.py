"""merge heads q3b4c5d6e7f8 and u1m2a3s4o5u6

Revision ID: a65e423571e9
Revises: q3b4c5d6e7f8, u1m2a3s4o5u6
Create Date: 2026-08-06 16:34:37.182233

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a65e423571e9'
down_revision: Union[str, Sequence[str], None] = ('q3b4c5d6e7f8', 'u1m2a3s4o5u6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
