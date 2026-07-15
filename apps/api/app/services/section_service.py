from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
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
    db: Session, *, user_id, section_id: str,
    content=None, status=None, expected_version: int | None = None,
) -> Section:
    section = get_section(db, user_id=user_id, section_id=section_id)

    # 乐观锁：传了 expected_version 则校验（设计 13.4）
    if expected_version is not None and expected_version != section.version:
        raise ConflictError(
            f"内容已被修改（当前版本 {section.version}，期望 {expected_version}）"
        )

    if content is not None:
        section.content = content
    if status is not None:
        if status not in ("empty", "drafting", "confirmed"):
            raise ValidationError("无效的章节状态")
        old_status = section.status
        section.status = status
        if status == "confirmed" and old_status != "confirmed":
            # 确认时自动存版本（设计 13.6 + 版本快照）
            from app.services.version_service import create_version
            create_version(db, section=section, created_by="auto", note="确认章节时自动保存")
            # 触发 summary 生成（供跨章节上下文用，设计 5.10）
            from app.services.summary_service import generate_summary
            generate_summary(db, section)
    section.version += 1  # 乐观锁版本号自增

    # 反写 Project.status（状态机）：section 流转 → 项目状态联动
    _sync_project_status(db, section)

    db.commit()
    db.refresh(section)
    return section


def _sync_project_status(db: Session, section: Section) -> None:
    """根据项目所有 section 状态反推 Project.status（设计 P1 状态机）。

    规则（归档优先，不覆盖 archived）：
    - 全部 sections 均 confirmed（≥1）→ completed
    - 任一 drafting/confirmed → in_progress
    - 否则 → draft
    """
    project = db.scalar(select(Project).where(Project.id == section.project_id))
    if project is None or project.status == "archived":
        return  # 归档项目不回退

    sections = list(db.scalars(
        select(Section).where(Section.project_id == project.id)
    ))
    if not sections:
        return

    statuses = [s.status for s in sections]
    if all(s == "confirmed" for s in statuses):
        project.status = "completed"
    elif any(s in ("drafting", "confirmed") for s in statuses):
        project.status = "in_progress"
    else:
        project.status = "draft"
