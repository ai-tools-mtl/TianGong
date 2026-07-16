"""add knowledge_files reviews + chunk scope/file_id/review_status + parse_job source_filename

Revision ID: 39198eaeea5d
Revises: d08c8546464c
Create Date: 2026-07-16 17:52:00.019658

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '39198eaeea5d'
down_revision: Union[str, Sequence[str], None] = 'd08c8546464c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 知识库源文件表(关联 minio 对象)
    op.create_table('knowledge_files',
        sa.Column('uploader_id', sa.Uuid(), nullable=False),
        sa.Column('scope', sa.String(length=20), nullable=False),
        sa.Column('bucket', sa.String(length=50), nullable=False),
        sa.Column('object_key', sa.String(length=512), nullable=False),
        sa.Column('filename', sa.String(length=255), nullable=False),
        sa.Column('mime_type', sa.String(length=100), nullable=False),
        sa.Column('size', sa.Integer(), nullable=False),
        sa.Column('source_type', sa.String(length=30), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['uploader_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_knowledge_files_uploader_id'), 'knowledge_files', ['uploader_id'], unique=False)

    # 审核工单表(双审核流共用,source_type 区分)
    op.create_table('knowledge_reviews',
        sa.Column('submitter_id', sa.Uuid(), nullable=False),
        sa.Column('reviewer_id', sa.Uuid(), nullable=True),
        sa.Column('source_type', sa.String(length=30), nullable=False),
        sa.Column('file_id', sa.Uuid(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('review_comment', sa.Text(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['file_id'], ['knowledge_files.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['reviewer_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['submitter_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_knowledge_reviews_file_id'), 'knowledge_reviews', ['file_id'], unique=False)
    op.create_index(op.f('ix_knowledge_reviews_submitter_id'), 'knowledge_reviews', ['submitter_id'], unique=False)

    # chunk 加三列:scope(NOT NULL,存量行回填 'personal')/ file_id / review_status
    op.add_column('knowledge_chunks', sa.Column('scope', sa.String(length=20), nullable=False, server_default='personal'))
    op.add_column('knowledge_chunks', sa.Column('file_id', sa.Uuid(), nullable=True))
    op.add_column('knowledge_chunks', sa.Column('review_status', sa.String(length=20), nullable=True))
    op.create_index(op.f('ix_knowledge_chunks_file_id'), 'knowledge_chunks', ['file_id'], unique=False)
    op.create_foreign_key('fk_knowledge_chunks_file_id', 'knowledge_chunks', 'knowledge_files', ['file_id'], ['id'], ondelete='SET NULL')

    # parse_job 加原始文件名列(原从 source_path basename 提,迁 minio 后 key 无原名)
    op.add_column('parse_jobs', sa.Column('source_filename', sa.String(length=255), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('parse_jobs', 'source_filename')
    op.drop_constraint('fk_knowledge_chunks_file_id', 'knowledge_chunks', type_='foreignkey')
    op.drop_index(op.f('ix_knowledge_chunks_file_id'), table_name='knowledge_chunks')
    op.drop_column('knowledge_chunks', 'review_status')
    op.drop_column('knowledge_chunks', 'file_id')
    op.drop_column('knowledge_chunks', 'scope')
    op.drop_index(op.f('ix_knowledge_reviews_submitter_id'), table_name='knowledge_reviews')
    op.drop_index(op.f('ix_knowledge_reviews_file_id'), table_name='knowledge_reviews')
    op.drop_table('knowledge_reviews')
    op.drop_index(op.f('ix_knowledge_files_uploader_id'), table_name='knowledge_files')
    op.drop_table('knowledge_files')
