"""merge mcp_servers and drop_rerank heads

Revision ID: a55afec3993e
Revises: c1a2b3d4e5f6, e371fa7db6da
Create Date: 2026-07-30 17:18:21.610489

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a55afec3993e'
down_revision: Union[str, Sequence[str], None] = ('c1a2b3d4e5f6', 'e371fa7db6da')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
