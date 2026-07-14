from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError
from app.models import Project, Section


def list_sections(db: Session, *, user_id, project_id: str) -> list[Section]:
    """列出项目的章节（先校验项目归属）。"""
    try:
        pid = UUID(project_id)
    except ValueError:
        raise NotFoundError("项目不存在")
    project = db.scalar(select(Project).where(Project.id == pid))
    if project is None or project.user_id != user_id:
        raise NotFoundError("项目不存在")
    return list(db.scalars(
        select(Section).where(Section.project_id == pid).order_by(Section.order)
    ))


def get_section(db: Session, *, user_id, section_id: str) -> Section:
    try:
        sid = UUID(section_id)
    except ValueError:
        raise NotFoundError("章节不存在")
    section = db.scalar(select(Section).where(Section.id == sid))
    if section is None:
        raise NotFoundError("章节不存在")
    project = db.scalar(select(Project).where(Project.id == section.project_id))
    if project is None or project.user_id != user_id:
        raise NotFoundError("章节不存在")
    return section


def update_section(
    db: Session, *, user_id, section_id: str, content=None, status=None
) -> Section:
    section = get_section(db, user_id=user_id, section_id=section_id)
    if content is not None:
        section.content = content
    if status is not None:
        if status not in ("empty", "drafting", "confirmed"):
            raise ValidationError("无效的章节状态")
        old_status = section.status
        section.status = status
        if status == "confirmed" and old_status != "confirmed":
            # 触发 summary 生成（供跨章节上下文用，设计 5.10）
            from app.services.summary_service import generate_summary
            generate_summary(db, section)
    db.commit()
    db.refresh(section)
    return section
