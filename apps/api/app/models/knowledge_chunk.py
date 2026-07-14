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
    source_type: Mapped[str] = mapped_column(String(30), default="disclosure")
    source_id: Mapped[uuid.UUID] = mapped_column(index=True)
    source_section_key: Mapped[str | None] = mapped_column(String(50), nullable=True)
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[str] = mapped_column(Text)
    embedding = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONType, nullable=True)
