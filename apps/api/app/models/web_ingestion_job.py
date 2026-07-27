"""网页摄入任务(WebIngestionJob)。

跟踪 Firecrawl crawl 任务的远端状态、本地配额、生成的内容文件。
scrape 模式不建本表记录(同步返回 KnowledgeFile);仅 crawl 模式建。

设计 spec: docs/superpowers/specs/2026-07-27-firecrawl-web-ingestion-design.md 第 3 节。
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, JSONType, TimestampMixin


class WebIngestionJob(Base, IdMixin, TimestampMixin):
    __tablename__ = "web_ingestion_jobs"

    # 发起者
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    scope: Mapped[str] = mapped_column(String(20))  # personal / global

    # 抓取参数
    url: Mapped[str] = mapped_column(String(2048))
    mode: Mapped[str] = mapped_column(String(10))  # scrape / crawl
    max_pages: Mapped[int] = mapped_column(Integer, default=1)  # crawl 上限

    # Firecrawl 远端任务跟踪
    firecrawl_job_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # 状态机:pending → running → completed / failed
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)

    # 抓取结果统计
    pages_fetched: Mapped[int] = mapped_column(Integer, default=0)
    pages_filtered: Mapped[int] = mapped_column(Integer, default=0)  # 被质量过滤掉的
    file_ids: Mapped[list | None] = mapped_column(JSONType, nullable=True)  # 生成的 KF.id 列表

    # 错误与时间
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
