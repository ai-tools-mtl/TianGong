import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError
from app.models import Project, ProjectTag, Tag, User


def _get_tag_owned(db: Session, *, user: User, tag_id: str) -> Tag:
    """获取标签并校验归属（非本人返回 404，防探测）。"""
    try:
        tid = uuid.UUID(tag_id)
    except ValueError:
        raise NotFoundError("标签不存在")
    tag = db.get(Tag, tid)
    if tag is None or tag.user_id != user.id:
        raise NotFoundError("标签不存在")
    return tag


def _get_project_owned(db: Session, *, user: User, project_id: str) -> Project:
    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        raise NotFoundError("项目不存在")
    project = db.get(Project, pid)
    if project is None or project.user_id != user.id:
        raise NotFoundError("项目不存在")
    return project


# ── 标签 CRUD ──

def create_tag(db: Session, *, user: User, name: str) -> Tag:
    tag = Tag(user_id=user.id, name=name.strip())
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return tag


def list_tags(db: Session, *, user: User) -> list[Tag]:
    """列出用户所有标签，按名称排序。返回的 Tag 对象附带 project_count 属性。"""
    tags = list(db.scalars(
        select(Tag).where(Tag.user_id == user.id).order_by(Tag.name)
    ))
    if not tags:
        return tags
    tag_ids = [t.id for t in tags]
    counts = dict(db.execute(
        select(ProjectTag.tag_id, func.count(ProjectTag.project_id))
        .where(ProjectTag.tag_id.in_(tag_ids))
        .group_by(ProjectTag.tag_id)
    ).all())
    for t in tags:
        t.project_count = counts.get(t.id, 0)
    return tags


def rename_tag(db: Session, *, user: User, tag_id: str, name: str) -> Tag:
    tag = _get_tag_owned(db, user=user, tag_id=tag_id)
    tag.name = name.strip()
    db.commit()
    db.refresh(tag)
    return tag


def delete_tag(db: Session, *, user: User, tag_id: str) -> None:
    """删除标签，并显式摘除该标签的所有 project_tag 关联。

    注：数据库层 tag→project_tags 已配置 ON DELETE CASCADE（生产 Postgres 生效），
    但 SQLite 测试默认不开启 PRAGMA foreign_keys，此处显式删除以保证行为一致。
    """
    tag = _get_tag_owned(db, user=user, tag_id=tag_id)
    # 显式摘除关联，避免依赖 DB 层 CASCADE（SQLite 测试不强制 FK）
    db.execute(
        ProjectTag.__table__.delete().where(ProjectTag.tag_id == tag.id)
    )
    db.delete(tag)
    db.commit()


def merge_tags(db: Session, *, user: User, source_id: str, target_id: str) -> Tag:
    """合并标签：source 的所有项目关联转移到 target，然后删除 source。

    幂等处理：source 和 target 都关联了同一项目时，避免唯一约束冲突。
    """
    if source_id == target_id:
        raise ValidationError("不能合并到自身")
    source = _get_tag_owned(db, user=user, tag_id=source_id)
    target = _get_tag_owned(db, user=user, tag_id=target_id)

    source_links = list(db.scalars(
        select(ProjectTag).where(ProjectTag.tag_id == source.id)
    ))
    target_project_ids = set(db.scalars(
        select(ProjectTag.project_id).where(ProjectTag.tag_id == target.id)
    ))

    for link in source_links:
        if link.project_id not in target_project_ids:
            link.tag_id = target.id
            target_project_ids.add(link.project_id)
        else:
            db.delete(link)

    db.delete(source)
    db.commit()
    db.refresh(target)
    return target


# ── 项目-标签关联 ──

def attach_tag(db: Session, *, user: User, project_id: str, tag_id: str) -> ProjectTag:
    """给项目贴标签。幂等：已存在则不重复创建。"""
    project = _get_project_owned(db, user=user, project_id=project_id)
    tag = _get_tag_owned(db, user=user, tag_id=tag_id)

    existing = db.scalar(
        select(ProjectTag).where(
            (ProjectTag.project_id == project.id) & (ProjectTag.tag_id == tag.id)
        )
    )
    if existing is not None:
        return existing  # 幂等

    link = ProjectTag(project_id=project.id, tag_id=tag.id)
    db.add(link)
    db.commit()
    db.refresh(link)
    return link


def detach_tag(db: Session, *, user: User, project_id: str, tag_id: str) -> None:
    """摘除项目标签。幂等：不存在则无操作。"""
    project = _get_project_owned(db, user=user, project_id=project_id)
    try:
        tid = uuid.UUID(tag_id)
    except ValueError:
        return  # 无效 id，幂等无操作

    link = db.scalar(
        select(ProjectTag).where(
            (ProjectTag.project_id == project.id) & (ProjectTag.tag_id == tid)
        )
    )
    if link is not None:
        db.delete(link)
        db.commit()


def list_tags_for_project(db: Session, *, user: User, project_id: str) -> list[Tag]:
    """列出项目上的所有标签。"""
    project = _get_project_owned(db, user=user, project_id=project_id)
    return list(db.scalars(
        select(Tag)
        .join(ProjectTag, ProjectTag.tag_id == Tag.id)
        .where(ProjectTag.project_id == project.id)
        .order_by(Tag.name)
    ))


def list_tag_ids_for_projects(db: Session, *, project_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[str]]:
    """批量查询多个项目的标签 id（用于 list_projects 时填充 tags 字段）。

    返回 {project_id: [tag_id_str, ...]}。
    """
    if not project_ids:
        return {}
    rows = db.execute(
        select(ProjectTag.project_id, ProjectTag.tag_id)
        .where(ProjectTag.project_id.in_(project_ids))
    ).all()
    result: dict[uuid.UUID, list[str]] = {}
    for pid, tid in rows:
        result.setdefault(pid, []).append(str(tid))
    return result
