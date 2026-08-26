import uuid

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


class Figure(Base, IdMixin, TimestampMixin):
    """AI 生成的专利附图（drawio 源 + 渲染产物）。

    与 Attachment 的关系：渲染出的 PNG 存为一条 Attachment 记录（复用现有上传/展示/导出
    通路），Figure 通过 attachment_id 关联它；同时单独保存 drawio XML 源文件与生成 prompt，
    支持「重新生成」「导出回 draw.io 编辑」。
    """
    __tablename__ = "figures"
    __table_args__ = (
        # 图号连续性由服务端保证（删除后重排无空洞）；唯一约束兜底并发分配
        UniqueConstraint("project_id", "number", name="uq_figures_project_number"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    section_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sections.id", ondelete="CASCADE"), nullable=True
    )
    # 渲染产物 PNG 的 Attachment 记录；Attachment 删除时置空（保留 XML 源）。
    attachment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("attachments.id", ondelete="SET NULL"), nullable=True, index=True
    )
    prompt: Mapped[str] = mapped_column(Text)  # 生成时的用户描述
    drawio_xml: Mapped[str] = mapped_column(Text)  # 可编辑源文件
    diagram_type: Mapped[str | None] = mapped_column(String(50), nullable=True)  # flowchart/architecture/...
    style: Mapped[str] = mapped_column(String(30), default="patent-bw")  # patent-bw/clean-color/technical
    # 项目内连续图号（1 起）。《专利审查指南》要求图按顺序编号——删除图后服务端
    # 同事务重排保持无空洞；regenerate 原地覆写不动编号（2026-08-26 图号系统 V1）。
    number: Mapped[int] = mapped_column(Integer, default=1)
