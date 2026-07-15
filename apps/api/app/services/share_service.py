"""协作系统服务（设计 plan17 / spec §7）。

负责：
- 项目成员（注册用户 reviewer）的增删查
- 分享链接（访客 token）的创建/撤销/校验
- 用户权限查询（owner / reviewer / none）

归属校验约定：本服务函数收到的 project_id 假定已由 API 层
（project_service.get_project）完成 owner 归属校验。
"""

import uuid
from datetime import datetime, timedelta, timezone

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


# ── 分享链接管理 ──

def create_share_link(
    db: Session, project_id, created_by, permissions: str, expires_days: int | None,
) -> ShareLink:
    """创建分享链接。

    - permissions: "comment" | "readonly"，其它值抛 ValidationError
    - expires_days: None 或 <=0 表示永不过期；>0 设置对应过期时间
    - token: uuid4().hex（32 位十六进制）
    """
    if permissions not in ("comment", "readonly"):
        raise ValidationError("权限必须为 comment 或 readonly")
    pid = _to_uuid(project_id, "项目不存在")
    cby = _to_uuid(created_by, "创建者无效")

    expires_at = None
    if expires_days is not None and expires_days > 0:
        expires_at = datetime.now(timezone.utc) + timedelta(days=expires_days)

    link = ShareLink(
        project_id=pid,
        token=uuid.uuid4().hex,
        permissions=permissions,
        expires_at=expires_at,
        created_by=cby,
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    return link


def list_share_links(db: Session, project_id) -> list[ShareLink]:
    """列出项目所有分享链接，按创建时间降序（新的在前）。"""
    pid = _to_uuid(project_id, "项目不存在")
    return list(db.scalars(
        select(ShareLink)
        .where(ShareLink.project_id == pid)
        .order_by(ShareLink.created_at.desc())
    ))


def revoke_share_link(db: Session, project_id, link_id) -> None:
    """撤销分享链接。幂等：不存在则无操作。

    校验 link 属于该 project（防越权删别项目的链接）。
    """
    pid = _to_uuid(project_id, "项目不存在")
    lid = _to_uuid(link_id, "链接不存在")
    link = db.get(ShareLink, lid)
    if link is None or link.project_id != pid:
        return  # 幂等
    db.delete(link)
    db.commit()


def verify_share_link(db: Session, token: str) -> tuple[ShareLink, Project]:
    """校验分享链接：存在 + 未过期 + 项目存在。

    失败一律抛 NotFoundError（防探测，对外统一"链接不存在或已失效"）。
    返回 (link, project) 供调用方构造受限权限的 Collabora URL。
    """
    link = db.scalar(select(ShareLink).where(ShareLink.token == token))
    if link is None:
        raise NotFoundError("分享链接不存在或已失效")

    if link.expires_at is not None:
        now = datetime.now(timezone.utc)
        exp = link.expires_at
        # sqlite 测试可能返回 naive datetime，补时区再比较
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp < now:
            raise NotFoundError("分享链接不存在或已失效")

    project = db.get(Project, link.project_id)
    if project is None:
        raise NotFoundError("分享链接不存在或已失效")
    return link, project
