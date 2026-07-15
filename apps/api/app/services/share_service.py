"""协作系统服务（设计 plan17 / spec §7）。

负责：
- 项目成员（注册用户 reviewer）的增删查
- 分享链接（访客 token）的创建/撤销/校验
- 用户权限查询（owner / reviewer / none）

归属校验约定：本服务函数收到的 project_id 假定已由 API 层
（project_service.get_project）完成 owner 归属校验。
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models import Project, ProjectMember, ShareLink, User


# ── 成员管理 ──

def list_members(db: Session, project_id) -> list[ProjectMember]:
    """列出项目所有成员（不含 owner），按创建时间升序。"""
    pid = _to_uuid(project_id, "项目不存在")
    return list(db.scalars(
        select(ProjectMember)
        .where(ProjectMember.project_id == pid)
        .order_by(ProjectMember.created_at.asc())
    ))


def add_member(db: Session, project_id, email: str) -> ProjectMember:
    """按邮箱邀请已注册用户加入项目。

    - 邮箱未注册 → ValidationError("用户未注册")
    - 用户已是成员 → ConflictError("该用户已是项目成员")
    - 用户是 owner 本人 → ValidationError("不能添加项目所有者为成员")
    """
    pid = _to_uuid(project_id, "项目不存在")
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        raise ValidationError("用户未注册")

    # 不能把 owner 加为成员
    project = db.get(Project, pid)
    if project is not None and project.user_id == user.id:
        raise ValidationError("不能添加项目所有者为成员")

    # 重复校验（DB 唯一约束兜底，这里提前抛更友好的 ConflictError）
    existing = db.scalar(
        select(ProjectMember).where(
            (ProjectMember.project_id == pid) & (ProjectMember.user_id == user.id)
        )
    )
    if existing is not None:
        raise ConflictError("该用户已是项目成员")

    member = ProjectMember(project_id=pid, user_id=user.id, role="reviewer")
    db.add(member)
    db.commit()
    db.refresh(member)
    return member


def remove_member(db: Session, project_id, member_id) -> None:
    """移除项目成员。幂等：不存在则无操作。

    校验 member 属于该 project（防越权删别项目的成员）。
    """
    pid = _to_uuid(project_id, "项目不存在")
    mid = _to_uuid(member_id, "成员不存在")
    member = db.get(ProjectMember, mid)
    if member is None or member.project_id != pid:
        return  # 幂等
    db.delete(member)
    db.commit()


# ── 权限查询 ──

def get_user_permission(db: Session, project_id, user_id) -> str:
    """返回用户对项目的权限："owner" | "reviewer" | "none"。

    用于 collabora-url 端点决定 WOPI token 权限。
    项目不存在或用户无关系时返回 "none"（不抛异常，便于调用方统一降级为 404）。
    """
    pid = _to_uuid_or_none(project_id)
    if pid is None:
        return "none"
    uid = _to_uuid_or_none(user_id)
    if uid is None:
        return "none"

    project = db.get(Project, pid)
    if project is None:
        return "none"
    if project.user_id == uid:
        return "owner"
    member = db.scalar(
        select(ProjectMember).where(
            (ProjectMember.project_id == pid) & (ProjectMember.user_id == uid)
        )
    )
    if member is not None:
        return member.role
    return "none"


# ── 工具函数 ──

def _to_uuid(value, error_message: str) -> uuid.UUID:
    """字符串/UUID → UUID；非法抛 NotFoundError（防探测，统一 404）。"""
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError):
        raise NotFoundError(error_message)


def _to_uuid_or_none(value):
    """同 _to_uuid 但非法时返回 None（用于 get_user_permission 的安全降级）。"""
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError):
        return None
