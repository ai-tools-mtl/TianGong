import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models import Project, Section, Template, User


def create_project(
    db: Session, *, user: User, title: str,
    template_id: str | None = None,
    metadata: dict | None = None,
    commit: bool = True,
) -> Project:
    # 解析模板：指定 > 默认 > 系统
    tpl = None
    if template_id:
        tpl = db.get(Template, uuid.UUID(template_id))
    if tpl is None:
        tpl = db.scalar(select(Template).where(Template.is_default.is_(True)))
    if tpl is None:
        tpl = db.scalar(select(Template).where(Template.is_system.is_(True)))

    project = Project(
        user_id=user.id,
        template_id=tpl.id if tpl else None,
        title=title,
        metadata_=metadata,
    )
    db.add(project)
    db.flush()

    # 按模板结构快照生成 sections（创建时快照，详见设计 9.7）
    if tpl:
        for ts in tpl.structure:
            section = Section(
                project_id=project.id,
                template_section_id=ts.get("id", ""),
                order=ts.get("order", 0),
                key=ts.get("key", "custom"),
                title=ts.get("title", ""),
            )
            db.add(section)

    if commit:
        db.commit()
        db.refresh(project)
    else:
        # 调用方自管事务（如 init 落地路径须把落地标记并入同一事务，
        # 保持 FOR UPDATE 行锁持有到 commit，见 init_orchestrator）。
        # flush 已保证 project.id 可用；不 refresh，避免丢弃同事务内的对象状态。
        db.flush()
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


def list_projects(
    db: Session, *, user: User,
    status: str | None = None,
    q: str | None = None,
    tag_id: str | None = None,
) -> list[Project]:
    stmt = select(Project).where(Project.user_id == user.id)
    if status is not None:
        stmt = stmt.where(Project.status == status)
    else:
        stmt = stmt.where(Project.status != "archived")  # 默认排除归档
    if q:
        stmt = stmt.where(Project.title.ilike(f"%{q}%"))
    if tag_id:
        from app.models import ProjectTag
        try:
            tid = uuid.UUID(tag_id)
        except ValueError:
            return []
        stmt = stmt.join(ProjectTag, ProjectTag.project_id == Project.id).where(ProjectTag.tag_id == tid)
    stmt = stmt.order_by(Project.updated_at.desc())
    return list(db.scalars(stmt))


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
