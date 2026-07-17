"""知识库源文件元信息(关联 minio 对象)。

设计(计划 T4):文件元信息独立成表,KnowledgeChunk 通过 file_id 关联。
- scope: personal(仅本人)/ global(全员共享)
- bucket/object_key: minio 定位
- source_type: 区分文件来源(归档导出 / 外部 docx / 外部 pdf)
"""

import uuid

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


class KnowledgeFile(Base, IdMixin, TimestampMixin):
    __tablename__ = "knowledge_files"

    uploader_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    scope: Mapped[str] = mapped_column(String(20), default="personal")  # personal / global
    bucket: Mapped[str] = mapped_column(String(50))  # "personal" / "global"(minio 别名)
    object_key: Mapped[str] = mapped_column(String(512))
    filename: Mapped[str] = mapped_column(String(255))  # 原始名(展示用)
    mime_type: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(Integer)
    source_type: Mapped[str] = mapped_column(String(30))
    # disclosure_export(归档导出件) / external_docx / external_pdf
    # 内容哈希(SHA256 hex,全局库去重用;personal 库不去重)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
