import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, JSONType, TimestampMixin

# 智谱 embedding-3 输出 2048 维
EMBEDDING_DIM = 2048


class KnowledgeChunk(Base, IdMixin, TimestampMixin):
    __tablename__ = "knowledge_chunks"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # 三域隔离(关键约束 1):global 时 user_id 记上传者但全员可检索;
    # personal 时 user_id 是 owner 严格隔离。retriever 按 scope+user_id 过滤。
    scope: Mapped[str] = mapped_column(String(20), default="personal")  # personal / global
    source_type: Mapped[str] = mapped_column(String(30), default="disclosure")
    source_id: Mapped[uuid.UUID] = mapped_column(index=True)
    source_section_key: Mapped[str | None] = mapped_column(String(50), nullable=True)
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[str] = mapped_column(Text)
    embedding = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONType, nullable=True)
    # 关联源文件(导入类有,自产归档类可为 NULL)
    file_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("knowledge_files.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # 审核状态:NULL(非上报对象)/ pending / approved / rejected
    review_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
