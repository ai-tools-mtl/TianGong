"""add web_ingestion_jobs table + knowledge_files.url column

Revision ID: c3d4e5f6a7b8
Revises: b_split_emb_config
Create Date: 2026-07-27

新建 web_ingestion_jobs 表(Firecrawl crawl 任务跟踪)+ 给 knowledge_files 加 url 列。
spec: docs/superpowers/specs/2026-07-27-firecrawl-web-ingestion-design.md 第 3 节。

列类型严格对齐 IdMixin/TimestampMixin(base.py),保证后续 autogenerate 不报伪 diff:
- id = sa.Uuid()
- timestamps = sa.DateTime(timezone=True) server_default now() NOT NULL
- file_ids 用 JSONB-with-variant(PG=JSONB, SQLite=JSON)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b_split_emb_config'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'web_ingestion_jobs',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('scope', sa.String(20), nullable=False),
        sa.Column('url', sa.String(2048), nullable=False),
        sa.Column('mode', sa.String(10), nullable=False),
        sa.Column('max_pages', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('firecrawl_job_id', sa.String(100), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('pages_fetched', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('pages_filtered', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('file_ids', sa.dialects.postgresql.JSONB().with_variant(sa.JSON(), 'sqlite'), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_web_ingestion_jobs_user_id', 'web_ingestion_jobs', ['user_id'])
    op.create_index('ix_web_ingestion_jobs_status', 'web_ingestion_jobs', ['status'])
    # 注:不建 created_at 索引——TimestampMixin 不声明 index=True,
    # 建了会让 alembic autogenerate 报伪 diff(检测到多余索引要删)。
    # user_id/status 索引对应模型里的 index=True 列。

    with op.batch_alter_table('knowledge_files', schema=None) as batch_op:
        batch_op.add_column(sa.Column('url', sa.String(2048), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('knowledge_files', schema=None) as batch_op:
        batch_op.drop_column('url')

    op.drop_index('ix_web_ingestion_jobs_status', table_name='web_ingestion_jobs')
    op.drop_index('ix_web_ingestion_jobs_user_id', table_name='web_ingestion_jobs')
    op.drop_table('web_ingestion_jobs')
