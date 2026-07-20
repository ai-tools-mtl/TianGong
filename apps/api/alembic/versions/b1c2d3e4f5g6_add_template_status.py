"""add template status + parse_job is_system

阶段 3 切片 B（refactor/admin-ia-phase3）：
1. 给 templates 表加 status 字段，支持模板状态机：
   draft（草稿）/ published（已发布）/ offline（已下线）。
2. 给 parse_jobs 表加 is_system 字段，标记解析出的 Template 是否为系统模板
   （admin 上传内置模板时置 True，普通用户上传默认 False）。

加列时带 server_default，现有数据自动迁移：
- templates.status='published'（保持现有行为不变）
- parse_jobs.is_system=False（保持现有行为不变）

batch_alter_table add_column 兼容 sqlite（测试）与 PG（生产）。

Revision ID: b1c2d3e4f5g6
Revises: a1b2c3d4e5f6
Create Date: 2026-07-19 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b1c2d3e4f5g6'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """加 templates.status + parse_jobs.is_system，server_default 保证旧数据自动迁移。"""
    with op.batch_alter_table('templates', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'status',
                sa.String(length=20),
                nullable=False,
                server_default='published',
            )
        )
    with op.batch_alter_table('parse_jobs', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'is_system',
                sa.Boolean(),
                nullable=False,
                server_default=sa.text('false'),
            )
        )


def downgrade() -> None:
    """回滚：删除两列。"""
    with op.batch_alter_table('parse_jobs', schema=None) as batch_op:
        batch_op.drop_column('is_system')
    with op.batch_alter_table('templates', schema=None) as batch_op:
        batch_op.drop_column('status')

