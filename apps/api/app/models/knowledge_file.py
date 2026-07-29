"""知识库源文件元信息(关联 minio 对象)。

设计(计划 T4):文件元信息独立成表,KnowledgeChunk 通过 file_id 关联。
- scope: personal(仅本人)/ global(全员共享)
- bucket/object_key: minio 定位
- source_type: 区分文件来源(归档导出 / 外部 docx / 外部 pdf)

异步向量化(plan async-knowledge-upload + async-parsing):上传立即落库
(status=pending),解析+分块+向量化在后台跑,通过 status/stage 跟踪进度。
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
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
    # 网页来源的原 URL(external_web 才有;其他来源为 None)
    url: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    # ── 异步解析+向量化进度(plan async-knowledge-upload + async-parsing)──
    # status: 文件级状态机。pending(刚落库待处理) / processing(解析/向量化中) /
    #         ready(完成,可检索) / failed(解析/向量化失败)。老数据迁移时 backfill 为 ready。
    # stage: 细分阶段,前端进度条用。uploaded(已落库) / parsing(解析中) /
    #        embedding(向量化中) / done(完成)。失败时保留上一个 stage + status=failed。
    # 前端轮询列表接口看 status/stage 推进。
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    stage: Mapped[str | None] = mapped_column(String(20), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
