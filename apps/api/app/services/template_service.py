from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.models import Template


def list_templates(db: Session, *, user_id) -> list[Template]:
    """列出用户的模板 + 系统默认模板。"""
    return list(db.scalars(
        select(Template).where(
            (Template.user_id == user_id) | (Template.is_system.is_(True))
        ).order_by(Template.is_system.desc(), Template.created_at.desc())
    ))


def get_template(db: Session, *, user_id, template_id: str) -> Template:
    try:
        tid = UUID(template_id)
    except ValueError:
        raise NotFoundError("模板不存在")
    tpl = db.scalar(select(Template).where(Template.id == tid))
    if tpl is None:
        raise NotFoundError("模板不存在")
    if not tpl.is_system and tpl.user_id != user_id:
        raise NotFoundError("模板不存在")
    return tpl


def delete_template(db: Session, *, user_id, template_id: str) -> None:
    tpl = get_template(db, user_id=user_id, template_id=template_id)
    if tpl.is_system:
        raise ConflictError("系统模板不可删除")
    db.delete(tpl)
    db.commit()


def set_default(db: Session, *, user_id, template_id: str) -> Template:
    tpl = get_template(db, user_id=user_id, template_id=template_id)
    user_templates = db.scalars(
        select(Template).where(
            (Template.user_id == user_id) & (Template.is_default.is_(True))
        )
    )
    for t in user_templates:
        t.is_default = False
    tpl.is_default = True
    db.commit()
    db.refresh(tpl)
    return tpl
