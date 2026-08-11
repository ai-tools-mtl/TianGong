"""merge guest-browse prep: unify 3 heads

Revision ID: 697a84b2b359
Revises: t0p1u2v3w4x5, u6w7x8y9z0a1, v7w8x9y0z1b2
Create Date: 2026-08-11 17:49:25.528448

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '697a84b2b359'
down_revision: Union[str, Sequence[str], None] = ('t0p1u2v3w4x5', 'u6w7x8y9z0a1', 'v7w8x9y0z1b2')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
