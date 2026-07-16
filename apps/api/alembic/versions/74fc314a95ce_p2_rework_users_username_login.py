"""p2 rework users username login

User 模型改造：username 成为登录标识（UNIQUE NOT NULL），email 降级为可选联系
方式（nullable、不再唯一）。按 drop-rebuild 共识，users 表现有数据可丢弃。

Revision ID: 74fc314a95ce
Revises: d08c8546464c
Create Date: 2026-07-16 17:21:58.674597

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '74fc314a95ce'
down_revision: Union[str, Sequence[str], None] = 'd08c8546464c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    步骤（add-then-alter，兼容空表 drop-rebuild）：
      1. 先清空 users 表（用户已接受数据丢弃；username 是新 NOT NULL 列，
         旧行无法满足约束）。
      2. 删除旧的 email 唯一索引 ix_users_email。
      3. 新增 username 列（先 nullable，再 ALTER 为 NOT NULL —— 兼容 sqlite）。
      4. 创建 email 普通索引（不再唯一）+ username 唯一索引。
      5. ALTER email 为 nullable。

    alter_column 走 batch 模式以兼容 sqlite（test.db 本地验证）+ 生产 PG。
    """
    # 1. 清空旧数据（用户接受 drop-rebuild）：username 是 NOT NULL 新列，
    #    保留旧行会违反约束。
    op.execute("DELETE FROM users")

    # 2. 删除旧 email 唯一索引（init 迁移以 unique index 形式建立）
    op.drop_index('ix_users_email', table_name='users')

    with op.batch_alter_table('users', schema=None) as batch_op:
        # 3. 新增 username 列（先 nullable 以便后续 ALTER 为 NOT NULL）
        batch_op.add_column(sa.Column('username', sa.String(length=50), nullable=True))
        batch_op.alter_column('username',
               existing_type=sa.String(length=50),
               nullable=False)
        # 5. email 降级为 nullable
        batch_op.alter_column('email',
               existing_type=sa.String(length=255),
               nullable=True)

    # 4. 重建索引：email 普通索引 + username 唯一索引
    op.create_index('ix_users_email', 'users', ['email'], unique=False)
    op.create_index('ix_users_username', 'users', ['username'], unique=True)


def downgrade() -> None:
    """Downgrade schema: 回退到 username 不存在、email UNIQUE NOT NULL 的旧结构。"""
    op.drop_index('ix_users_username', table_name='users')
    op.drop_index('ix_users_email', table_name='users')

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.alter_column('email',
               existing_type=sa.String(length=255),
               nullable=False)
        batch_op.drop_column('username')

    op.create_index('ix_users_email', 'users', ['email'], unique=True)
