from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models import Template

# 模板状态机（refactor/admin-ia-phase3 切片 B）：
# draft（草稿）/ published（已发布）/ offline（已下线）
# 合法转换：draft→published、published→offline、offline→published。
# 删除：draft/offline 可删；published 必须先下线。
TEMPLATE_STATUS_DRAFT = "draft"
TEMPLATE_STATUS_PUBLISHED = "published"
TEMPLATE_STATUS_OFFLINE = "offline"
_TEMPLATE_VALID_STATUSES = {
    TEMPLATE_STATUS_DRAFT,
    TEMPLATE_STATUS_PUBLISHED,
    TEMPLATE_STATUS_OFFLINE,
}
# 合法的状态转换路径：from_status → {允许的 to_status}
_TEMPLATE_TRANSITIONS = {
    TEMPLATE_STATUS_DRAFT: {TEMPLATE_STATUS_PUBLISHED},
    TEMPLATE_STATUS_PUBLISHED: {TEMPLATE_STATUS_OFFLINE},
    TEMPLATE_STATUS_OFFLINE: {TEMPLATE_STATUS_PUBLISHED},
}


def list_templates(db: Session, *, user_id) -> list[Template]:
    """普通用户视角：自己的模板（全状态）+ 已发布的系统模板。

    注意：系统模板的 draft/offline 不向普通用户展示（admin 上传未发布或已下线的）。
    用户自己的模板不受 status 过滤（用户能管理自己的草稿/已发布）。
    """
    return list(db.scalars(
        select(Template).where(
            (Template.user_id == user_id)
            | (
                Template.is_system.is_(True)
                & (Template.status == TEMPLATE_STATUS_PUBLISHED)
            )
        ).order_by(Template.is_system.desc(), Template.created_at.desc())
    ))


def list_system_templates(db: Session) -> list[Template]:
    """admin 视角：所有系统模板（含 draft/offline/published，不过滤状态）。"""
    return list(db.scalars(
        select(Template)
        .where(Template.is_system.is_(True))
        .order_by(Template.created_at.desc())
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
    # 系统模板仅 published 可被普通用户读（draft/offline 仅 admin 可见）
    if tpl.is_system and tpl.status != TEMPLATE_STATUS_PUBLISHED and tpl.user_id != user_id:
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


# ── admin 操作（refactor/admin-ia-phase3 切片 B）──

def get_system_template(db: Session, *, template_id: str) -> Template:
    """admin 取单个系统模板（不过滤状态，draft/offline 也能取）。"""
    try:
        tid = UUID(template_id)
    except ValueError:
        raise NotFoundError("模板不存在")
    tpl = db.scalar(select(Template).where(Template.id == tid))
    if tpl is None or not tpl.is_system:
        raise NotFoundError("模板不存在")
    return tpl


def set_template_status(db: Session, *, template_id: str, status: str) -> Template:
    """admin 改模板状态，校验状态机合法转换路径。

    合法：draft→published、published→offline、offline→published。
    非法转换抛 ValidationError（400），不合法 status 抛 ValidationError。
    """
    if status not in _TEMPLATE_VALID_STATUSES:
        raise ValidationError(f"非法状态值：{status}")
    tpl = get_system_template(db, template_id=template_id)
    allowed = _TEMPLATE_TRANSITIONS.get(tpl.status, set())
    if status not in allowed:
        raise ValidationError(
            f"非法状态转换：{tpl.status} → {status}（允许：{sorted(allowed) or '无'}）"
        )
    tpl.status = status
    db.commit()
    db.refresh(tpl)
    return tpl


def admin_delete_template(db: Session, *, template_id: str) -> None:
    """admin 删除系统模板。published 必须先下线（拒删，409 ConflictError）。"""
    tpl = get_system_template(db, template_id=template_id)
    if tpl.status == TEMPLATE_STATUS_PUBLISHED:
        raise ConflictError("已发布的模板不可直接删除，请先下线")
    db.delete(tpl)
    db.commit()

