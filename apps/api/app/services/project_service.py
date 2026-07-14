import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models import Project, User


def create_project(
    db: Session, *, user: User, title: str,
    template_id: str | None = None,
    metadata: dict | None = None,
) -> Project:
    project = Project(
        user_id=user.id,
        title=title,
        template_id=uuid.UUID(template_id) if template_id else None,
        metadata_=metadata,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def get_project(db: Session, *, user: User, project_id: str) -> Project:
    """获取项目。资源级权限：非本人项目返回 NotFound（防探测）。"""
    try:
        pid = uuid.UUID(project_id) if isinstance(project_id, str) else project_id
    except ValueError:
        raise NotFoundError("项目不存在")
    project = db.scalar(select(Project).where(Project.id == pid))
    if project is None or project.user_id != user.id:
        raise NotFoundError("项目不存在")
    return project


def list_projects(db: Session, *, user: User) -> list[Project]:
    return list(db.scalars(
        select(Project)
        .where(Project.user_id == user.id)
        .order_by(Project.updated_at.desc())
    ))


def update_project(
    db: Session, *, user: User, project_id: str,
    title: str | None = None, metadata: dict | None = None,
) -> Project:
    project = get_project(db, user=user, project_id=project_id)
    if title is not None:
        project.title = title
    if metadata is not None:
        project.metadata_ = metadata
    db.commit()
    db.refresh(project)
    return project


def delete_project(db: Session, *, user: User, project_id: str) -> None:
    project = get_project(db, user=user, project_id=project_id)
    db.delete(project)
    db.commit()
