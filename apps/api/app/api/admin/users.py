"""管理员：用户运营域（/admin/users/*）。

从原 admin.py 拆出（refactor/admin-api-split）。包含：
- GET    /admin/users                       用户列表
- GET    /admin/users/recent-logins         最近登录 5（落地页聚合）
- GET    /admin/users/recent-creations      最近注册 5（落地页聚合）
- GET    /admin/users/{user_id}             单用户详情
- PATCH  /admin/users/{user_id}/status      封禁/解禁
- POST   /admin/users/{user_id}/reset-password  重置密码
- GET    /admin/users/{user_id}/global-llm-grant  查授权状态
- POST   /admin/users/{user_id}/global-llm-grant  授权使用全局 Key
- DELETE /admin/users/{user_id}/global-llm-grant  撤销授权

路由顺序约束：{user_id} 必须排在 recent-logins/recent-creations 之后。
"""

import uuid as _uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.deps import require_admin
from app.models import Project, User, UserGlobalLLMGrant, UserLLMConfig
from app.services import admin_service

router = APIRouter(tags=["admin"])


class UserStatusUpdate(BaseModel):
    status: str  # active / disabled


class PasswordReset(BaseModel):
    new_password: str


class AdminCreateUser(BaseModel):
    """admin 直接创建账号(内部产品化:关闭注册后的另一发号途径)。

    复用 register_user 的校验(EmailStr/username 唯一/密码强度),
    保证所有写用户入口同一套校验(GOTCHAS G4)。不需要邀请码。
    """
    username: str
    email: str | None = None
    password: str
    name: str
    role: str = "user"  # user / admin,默认 user


@router.post("/admin/users")
def create_user(
    payload: AdminCreateUser,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """admin 直接创建账号。复用 register_user 校验逻辑,无需邀请码。"""
    from app.services.auth_service import register_user
    user = register_user(
        db,
        username=payload.username,
        password=payload.password,
        name=payload.name,
        email=payload.email,
    )
    # 角色调整(register_user 默认建 user;admin 指定 admin 时改)
    if payload.role == "admin" and user.role != "admin":
        user.role = "admin"
        db.commit()
        db.refresh(user)
    # 审计
    from app.services.admin_service import _audit
    _audit(
        db, actor=admin, action="create_user",
        target_type="user", target_id=str(user.id),
        detail={"username": user.username, "role": user.role},
    )
    return {
        "id": str(user.id),
        "username": user.username,
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "status": user.status,
    }


@router.get("/admin/users")
def list_users(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """用户列表（仅聚合信息：邮箱/角色/状态/项目数/是否自配key/是否被全局授权）。"""
    users = list(db.scalars(select(User).order_by(User.created_at.desc())))
    # 一次性取出所有有效授权（revoked_at is null）的 user_id，避免 N+1。
    active_grant_ids = set(db.scalars(
        select(UserGlobalLLMGrant.user_id).where(UserGlobalLLMGrant.revoked_at.is_(None))
    ))
    result = []
    for u in users:
        project_count = db.scalar(
            select(func.count(Project.id)).where(Project.user_id == u.id)
        )
        has_own_key = db.scalar(
            select(func.count(UserLLMConfig.id)).where(UserLLMConfig.user_id == u.id)
        )
        result.append({
            "id": str(u.id),
            "username": u.username,
            "email": u.email,
            "name": u.name,
            "role": u.role,
            "status": u.status,
            "project_count": project_count or 0,
            "has_own_llm_key": (has_own_key or 0) > 0,
            "has_global_grant": u.id in active_grant_ids,
            "created_at": u.created_at.isoformat(),
            "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
        })
    return result


# ── 落地页聚合（refactor/admin-ia-phase1）──

@router.get("/admin/users/recent-logins")
def list_recent_logins(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """最近登录的 5 个用户（按 last_login_at 倒序）。

    数据来源是 User.last_login_at（登录时由 auth_service.update_last_login 写入），
    不依赖 AuditLog——当前 auth 不写审计，避免落地页与审计耦合。
    """
    users = list(db.scalars(
        select(User)
        .where(User.last_login_at.is_not(None))
        .order_by(User.last_login_at.desc())
        .limit(5)
    ))
    return [
        {
            "id": str(u.id),
            "username": u.username,
            "email": u.email,
            "ts": u.last_login_at.isoformat() if u.last_login_at else None,
        }
        for u in users
    ]


@router.get("/admin/users/recent-creations")
def list_recent_creations(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """最近注册的 5 个用户（按 created_at 倒序）。"""
    users = list(db.scalars(
        select(User).order_by(User.created_at.desc()).limit(5)
    ))
    return [
        {
            "id": str(u.id),
            "username": u.username,
            "email": u.email,
            "ts": u.created_at.isoformat() if u.created_at else None,
        }
        for u in users
    ]


# 注意路由顺序：本路由 {user_id} 必须排在 /admin/users/recent-logins 和
# /admin/users/recent-creations 之后，否则 "recent-logins" 会被当成 user_id 匹配。
@router.get("/admin/users/{user_id}")
def get_user_detail(
    user_id: str,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """单用户详情（聚合信息 + 全局 Key 授权状态）。

    字段与 list_users 对齐，额外返回 grant_detail（{granted_at, revoked_at, is_active} or None）。
    用户不存在返回 404。
    """
    u = db.scalar(select(User).where(User.id == _uuid.UUID(user_id)))
    if not u:
        raise NotFoundError("用户不存在")
    project_count = db.scalar(
        select(func.count(Project.id)).where(Project.user_id == u.id)
    ) or 0
    has_own_key = db.scalar(
        select(func.count(UserLLMConfig.id)).where(UserLLMConfig.user_id == u.id)
    ) or 0
    grant = admin_service.get_user_grant(db, user_id=u.id)
    return {
        "id": str(u.id),
        "username": u.username,
        "email": u.email,
        "name": u.name,
        "role": u.role,
        "status": u.status,
        "project_count": project_count,
        "has_own_llm_key": has_own_key > 0,
        "has_global_grant": bool(grant and grant.get("is_active")),
        "grant_detail": grant,
        "created_at": u.created_at.isoformat(),
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
    }


@router.patch("/admin/users/{user_id}/status")
def update_user_status(
    user_id: str,
    payload: UserStatusUpdate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """封禁/解禁用户。自我保护在 service 层强制。"""
    target = admin_service.set_user_status(
        db, actor=admin, user_id=_uuid.UUID(user_id), status=payload.status,
    )
    return {"id": str(target.id), "status": target.status}


@router.post("/admin/users/{user_id}/reset-password")
def reset_user_password(
    user_id: str,
    payload: PasswordReset,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """重置用户密码（管理员线下告知，不返回敏感信息）。"""
    admin_service.reset_user_password(
        db, actor=admin, user_id=_uuid.UUID(user_id), new_password=payload.new_password,
    )
    return {"ok": True}


# ── 全局 Key 授权（Task 2.2）──

@router.get("/admin/users/{user_id}/global-llm-grant")
def get_user_grant(
    user_id: str,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """查用户的全局 Key 授权状态。无记录返回 {is_active: False}。"""
    return admin_service.get_user_grant(db, user_id=_uuid.UUID(user_id)) or {"is_active": False}


@router.post("/admin/users/{user_id}/global-llm-grant")
def grant_global_llm(
    user_id: str,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """授权用户使用全局 Key。幂等：已有则清 revoked_at 重新激活。自我保护在 service 层强制。"""
    admin_service.grant_global_llm_access(db, actor=admin, user_id=_uuid.UUID(user_id))
    return {"message": "已授权"}


@router.delete("/admin/users/{user_id}/global-llm-grant")
def revoke_global_llm(
    user_id: str,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """撤销用户的全局 Key 授权。写 revoked_at（保留行审计）。无记录则 no-op。"""
    admin_service.revoke_global_llm_access(db, actor=admin, user_id=_uuid.UUID(user_id))
    return {"message": "已撤销"}
