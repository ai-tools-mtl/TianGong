"""merge heads: 线性化迁移链 + 删除废弃的 user_ima_configs 表

Revision ID: a65e423571e9
Revises: q3b4c5d6e7f8
Create Date: 2026-08-06 16:34:37.182233

变更说明：
原合并点曾指向 (q3b4c5d6e7f8, u1m2a3s4o5u6) 两个 head——u1m2a3s4o5u6 建
user_ima_configs 表（用户级 ima 配置）。ima 检索源已改为 admin 全局配置（存
SystemSetting），用户级表废弃，该迁移文件已删除。此处重写为单 parent，
并在 upgrade 中 drop 废弃表，保持迁移链单线完整。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a65e423571e9'
down_revision: Union[str, Sequence[str], None] = 'q3b4c5d6e7f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """线性化迁移链 + 删除废弃的 user_ima_configs 表。"""
    # ima 检索源改为 admin 全局配置（SystemSetting），用户级表废弃。
    # 若表已不存在（如全新部署）静默跳过。
    op.execute("DROP TABLE IF EXISTS user_ima_configs")


def downgrade() -> None:
    """不建议回滚——用户级 ima 表已废弃，不再使用。"""
    pass
