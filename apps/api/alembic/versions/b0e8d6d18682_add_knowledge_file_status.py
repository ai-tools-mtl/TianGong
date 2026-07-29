"""add knowledge_files.status / stage / error_message / completed_at

Revision ID: b0e8d6d18682
Revises: f1x2e3m4b5g6
Create Date: 2026-07-29

知识库上传异步化：给 knowledge_files 加进度字段，向量化从请求内移到后台。
- status: pending / processing / ready / failed（文件级状态机）
- stage: uploaded / embedding / done（细分阶段，前端进度条）
- error_message / completed_at

backfill：老数据（本迁移前已存在的文件）一律视为已完成（status='ready', stage='done'），
因为它们在旧的同步流程里已经向量化和检索可用。

幂等：纯 ADD COLUMN，不依赖数据存在；IF NOT EXISTS 风格由 batch_alter_table 保证
SQLite/PG 兼容。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b0e8d6d18682'
down_revision: Union[str, Sequence[str], None] = 'f1x2e3m4b5g6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """加 4 个进度字段 + backfill 老数据为 ready。"""
    with op.batch_alter_table('knowledge_files', schema=None) as batch_op:
        batch_op.add_column(sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'))
        batch_op.add_column(sa.Column('stage', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('error_message', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True))
    # status 加索引（前端按状态过滤/轮询）
    op.create_index('ix_knowledge_files_status', 'knowledge_files', ['status'])

    # backfill：老数据一律标记为已完成（status=ready, stage=done, completed_at=now）
    # 新数据默认 status=pending（server_default），由后台向量化任务流转到 ready。
    op.execute(
        "UPDATE knowledge_files SET status='ready', stage='done', "
        "completed_at=NOW() WHERE status='pending'"
    )


def downgrade() -> None:
    """回滚：删 4 个字段 + 索引。"""
    op.drop_index('ix_knowledge_files_status', table_name='knowledge_files')
    with op.batch_alter_table('knowledge_files', schema=None) as batch_op:
        batch_op.drop_column('completed_at')
        batch_op.drop_column('error_message')
        batch_op.drop_column('stage')
        batch_op.drop_column('status')
