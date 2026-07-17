"""p2 audit_logs actor_username

审计日志：actor_email → actor_username。Task 1.0 把登录标识从 email 改为
username 后，email 变成可选联系方式，作为审计冗余字段已不合适。改为
冗余存储 username（与 User.username 类型一致 String(50)）。

数据可丢弃（drop-rebuild 共识），用 batch_alter_table 的 drop + add 方式
重命名列，同时把类型从 String(255) 收紧到 String(50)，兼容 sqlite 与 PG。

Revision ID: fa75b47f596f
Revises: 74fc314a95ce
Create Date: 2026-07-16 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fa75b47f596f'
down_revision: Union[str, Sequence[str], None] = '74fc314a95ce'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: audit_logs.actor_email → actor_username (String(50))."""
    # 清空历史审计行（drop-rebuild 共识：旧 email 字段对 username 无意义）
    op.execute("DELETE FROM audit_logs")

    with op.batch_alter_table('audit_logs', schema=None) as batch_op:
        batch_op.drop_column('actor_email')
        batch_op.add_column(sa.Column('actor_username', sa.String(length=50), nullable=False))


def downgrade() -> None:
    """Downgrade schema: 回退到 actor_email (String(255))."""
    with op.batch_alter_table('audit_logs', schema=None) as batch_op:
        batch_op.drop_column('actor_username')
        batch_op.add_column(sa.Column('actor_email', sa.String(length=255), nullable=False))
