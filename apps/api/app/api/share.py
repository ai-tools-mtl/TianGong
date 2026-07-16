"""协作系统 API（设计 plan17 / spec §7）。

端点分两组：
1. owner-only（cookie 鉴权 + project_service.get_project 归属校验）：
   - POST   /projects/{project_id}/members
   - GET    /projects/{project_id}/members
   - DELETE /projects/{project_id}/members/{member_id}
   - POST   /projects/{project_id}/share-links
   - GET    /projects/{project_id}/share-links
   - DELETE /projects/{project_id}/share-links/{link_id}
2. 公开（无 cookie 鉴权，靠 share token）：
   - GET    /shared/{token}

归属校验：owner-only 端点统一调 project_service.get_project(db, user=current_user, ...)，
非 owner 抛 NotFoundError（404，防探测）。
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas.share import (
    MemberAdd, MemberOut, ShareLinkCreate, ShareLinkOut, SharedInfo,
)
from app.services import project_service, share_service

router = APIRouter(tags=["share"])


def _to_member_out(member, user: User) -> MemberOut:
    """把 ProjectMember + User 组装成 MemberOut（含 email/name）。"""
    return MemberOut(
        id=str(member.id),
        project_id=str(member.project_id),
        user_id=str(member.user_id),
        email=user.email,
        name=user.name,
        role=member.role,
        created_at=member.created_at,
    )


def _to_link_out(link) -> ShareLinkOut:
    """把 ShareLink ORM 对象转为 ShareLinkOut（UUID → str 显式转换）。"""
    return ShareLinkOut(
        id=str(link.id),
        project_id=str(link.project_id),
        token=link.token,
        permissions=link.permissions,
        expires_at=link.expires_at,
        created_by=str(link.created_by),
        created_at=link.created_at,
    )


# ── 成员管理（owner-only）──

@router.post(
    "/projects/{project_id}/members",
    response_model=MemberOut,
    status_code=status.HTTP_201_CREATED,
)
def add_member(
    project_id: str,
    payload: MemberAdd,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """添加项目成员（按邮箱，owner-only）。

    邮箱未注册 → 422；已是成员 → 409；owner 本人 → 422。
    """
    project = project_service.get_project(db, user=current_user, project_id=project_id)
    member = share_service.add_member(db, project.id, payload.email)
    user = db.get(User, member.user_id)
    return _to_member_out(member, user)


@router.get("/projects/{project_id}/members", response_model=list[MemberOut])
def list_members(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """列出项目成员（owner-only）。"""
    project = project_service.get_project(db, user=current_user, project_id=project_id)
    members = share_service.list_members(db, project.id)
    user_ids = [m.user_id for m in members]
    users = {
        u.id: u for u in db.scalars(select(User).where(User.id.in_(user_ids)))
    } if user_ids else {}
    return [_to_member_out(m, users[m.user_id]) for m in members]


@router.delete("/projects/{project_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    project_id: str,
    member_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """移除项目成员（owner-only，幂等）。"""
    project = project_service.get_project(db, user=current_user, project_id=project_id)
    share_service.remove_member(db, project.id, member_id)
    return None


# ── 分享链接管理（owner-only）──

@router.post(
    "/projects/{project_id}/share-links",
    response_model=ShareLinkOut,
    status_code=status.HTTP_201_CREATED,
)
def create_share_link(
    project_id: str,
    payload: ShareLinkCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """创建分享链接（owner-only）。

    permissions: comment / readonly；expires_days: None=永不过期。
    """
    project = project_service.get_project(db, user=current_user, project_id=project_id)
    link = share_service.create_share_link(
        db, project.id, created_by=current_user.id,
        permissions=payload.permissions, expires_days=payload.expires_days,
    )
    return _to_link_out(link)


@router.get("/projects/{project_id}/share-links", response_model=list[ShareLinkOut])
def list_share_links(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """列出项目分享链接（owner-only）。"""
    project = project_service.get_project(db, user=current_user, project_id=project_id)
    links = share_service.list_share_links(db, project.id)
    return [_to_link_out(l) for l in links]


@router.delete(
    "/projects/{project_id}/share-links/{link_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def revoke_share_link(
    project_id: str,
    link_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """撤销分享链接（owner-only，幂等）。"""
    project = project_service.get_project(db, user=current_user, project_id=project_id)
    share_service.revoke_share_link(db, project.id, link_id)
    return None


# ── 公开端点（无 cookie 鉴权，靠 share token）──

@router.get("/shared/{token}", response_model=SharedInfo)
def get_shared_info(token: str, db: Session = Depends(get_db)):
    """公开端点：访客凭分享 token 获取项目标题 + 权限。

    无需登录。token 不存在/过期/项目不存在 → 404（统一防探测）。
    """
    link, project = share_service.verify_share_link(db, token)
    return SharedInfo(
        title=project.title,
        permissions=link.permissions,
        project_id=str(project.id),
        share_token=link.token,
    )
