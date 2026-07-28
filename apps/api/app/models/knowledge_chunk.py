import uuid

from pgvector.sqlalchemy import HALFVEC as HalfVec
from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, JSONType, TimestampMixin

# 智谱 embedding-3 输出 2048 维
EMBEDDING_DIM = 2048


class KnowledgeChunk(Base, IdMixin, TimestampMixin):
    __tablename__ = "knowledge_chunks"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # 三域隔离(关键约束 1):
    # - scope=personal:user_id 是 owner,严格隔离,仅本人可检索
    # - scope=global:user_id 记「上传者/来源」,全员可检索(retriever 不按 user_id 过滤 global)
    # 注意:personal 素材 approve 升 global 后,user_id 仍是原 owner——
    # 该用户从 personal 角度不再单独命中它(已升 global,走 global 分支),语义一致。
    scope: Mapped[str] = mapped_column(String(20), default="personal")  # personal / global
    source_type: Mapped[str] = mapped_column(String(30), default="disclosure")
    source_id: Mapped[uuid.UUID] = mapped_column(index=True)
    source_section_key: Mapped[str | None] = mapped_column(String(50), nullable=True)
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[str] = mapped_column(Text)
    embedding = mapped_column(HalfVec(EMBEDDING_DIM), nullable=True)
    # BM25 关键词路召回用（G3）：PG 层是 tsvector，SQLite 层用 Text 占位
    tsv: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONType, nullable=True)
    # 关联源文件(导入类有,自产归档类可为 NULL)
    file_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("knowledge_files.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # 审核状态:NULL(非上报对象)/ pending / approved / rejected
    review_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # G4 分块干预字段（spec §5.4, D3 独立列）
    keywords: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    questions: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    weight: Mapped[float | None] = mapped_column(Float, default=1.0)
    edited_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    locked: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
