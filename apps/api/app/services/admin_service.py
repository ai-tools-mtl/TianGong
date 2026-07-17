"""管理员运营服务：封禁/解禁/重置密码 + 全局 Key 授权 + 自我保护 + 审计 helper（设计 8.1/8.3）。

自我保护（设计 8.1，针对「封禁」语义）：
1. 不能封禁自己（ban: target.id == actor.id → 403）
2. 不能封禁超管（ban: target.is_superuser → 403）
3. 不能封禁其他管理员（ban: target.role == "admin" → 403）
重置密码约束更宽：仅禁「重置自己」（防误锁死自己），对超管/其他管理员放行。
全局 Key 授权（grant/revoke_global_llm，Task 2.2）：admin 角色免授权，
给其他 admin/超管授权无意义，故禁止；允许给自己授权（无害，虽无意义）。
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ForbiddenError, NotFoundError
from app.core.security import hash_password
from app.models import AuditLog, User, UserGlobalLLMGrant


def set_user_status(
    db: Session, *, actor: User, user_id: uuid.UUID, status: str
) -> User:
    """封禁/解禁用户。status ∈ {active, disabled}。"""
    if status not in ("active", "disabled"):
        raise ForbiddenError(f"非法状态值: {status}")
    target = _get_and_guard(db, actor=actor, user_id=user_id, action="ban")
    target.status = status
    db.commit()
    db.refresh(target)

    _audit(
        db,
        actor=actor,
        action="ban_user" if status == "disabled" else "unban_user",
        target_type="user",
        target_id=str(target.id),
        detail={"status": status, "target_email": target.email},
    )
    return target


def reset_user_password(
    db: Session, *, actor: User, user_id: uuid.UUID, new_password: str
) -> None:
    """重置用户密码。不返回响应（管理员线下告知）。"""
    if not new_password or len(new_password) < 1:
        raise ForbiddenError("新密码不能为空")
    # reset 仅禁自身（设计 8.1 自我保护只针对封禁语义；reset 不改账号可用性，对超管/其他管理员放行）
    target = _get_and_guard(db, actor=actor, user_id=user_id, action="reset")

    target.password_hash = hash_password(new_password)
    db.commit()

    _audit(
        db,
        actor=actor,
        action="reset_password",
        target_type="user",
        target_id=str(target.id),
        detail={"reset": True, "target_email": target.email},  # 不含新密码明文
    )


def _get_and_guard(db: Session, *, actor: User, user_id: uuid.UUID, action: str) -> User:
    """取目标用户 + 自我保护校验。action ∈ {ban, reset, grant_global_llm, revoke_global_llm}。

    - ban：不能操作自己、不能封禁超管、不能封禁其他管理员。
    - reset：仅禁自身（防误锁死自己）；对超管/其他管理员放行（不改账号可用性）。
    - grant/revoke_global_llm：允许操作自己（admin 自我授权无意义但无害）；
      禁止操作超管、其他管理员（admin 角色免授权，授权无意义）。
    """
    target = db.scalar(select(User).where(User.id == user_id))
    if target is None:
        raise NotFoundError("用户不存在")

    if action in ("ban", "reset"):
        # 约束 1（ban + reset 共有）：不能操作自己
        if target.id == actor.id:
            raise ForbiddenError("不能对自己执行此操作")

    if action == "ban":
        # 约束 2：不能封禁超管
        if target.is_superuser:
            raise ForbiddenError("不能封禁超级管理员")
        # 约束 3：不能封禁其他管理员
        if target.role == "admin":
            raise ForbiddenError("不能封禁其他管理员")

    if action in ("grant_global_llm", "revoke_global_llm"):
        # admin 角色免授权（设计 8.1），给其他 admin/超管授权无意义，禁之。
        # 允许给自己授权（无害；admin 本就免授权，grant 自己不会改变生效逻辑）。
        if target.id != actor.id:
            if target.is_superuser:
                raise ForbiddenError("超级管理员免授权，无需授权")
            if target.role == "admin":
                raise ForbiddenError("管理员角色免授权，无需授权")

    return target


# ── 全局 Key 授权（Task 2.2）──

def get_user_grant(db: Session, *, user_id: uuid.UUID) -> dict | None:
    """查用户的全局 Key 授权状态。无记录返回 None；有记录返回 {granted_at, revoked_at, is_active}."""
    grant = db.scalar(select(UserGlobalLLMGrant).where(UserGlobalLLMGrant.user_id == user_id))
    if not grant:
        return None
    return {
        "granted_at": grant.granted_at.isoformat() if grant.granted_at else None,
        "revoked_at": grant.revoked_at.isoformat() if grant.revoked_at else None,
        "is_active": grant.revoked_at is None,  # True=有效授权
    }


def grant_global_llm_access(db: Session, *, actor: User, user_id: uuid.UUID) -> UserGlobalLLMGrant:
    """授权用户使用全局 Key。幂等：已有记录则清 revoked_at（重新激活），否则新建。"""
    target = _get_and_guard(db, actor=actor, user_id=user_id, action="grant_global_llm")
    grant = db.scalar(select(UserGlobalLLMGrant).where(UserGlobalLLMGrant.user_id == user_id))
    if grant:
        grant.revoked_at = None  # 重新激活（幂等）
    else:
        grant = UserGlobalLLMGrant(user_id=user_id, granted_by=actor.id)
        db.add(grant)
    db.commit()
    db.refresh(grant)
    _audit(
        db,
        actor=actor,
        action="grant_global_llm",
        target_type="user",
        target_id=str(target.id),
        detail={},
    )
    return grant


def revoke_global_llm_access(db: Session, *, actor: User, user_id: uuid.UUID) -> None:
    """撤销用户的全局 Key 授权。写 revoked_at（保留行审计）。无记录则 no-op（仍校验目标存在）。"""
    target = _get_and_guard(db, actor=actor, user_id=user_id, action="revoke_global_llm")
    grant = db.scalar(select(UserGlobalLLMGrant).where(UserGlobalLLMGrant.user_id == user_id))
    if grant and grant.revoked_at is None:
        from datetime import datetime, timezone
        grant.revoked_at = datetime.now(timezone.utc)
        db.commit()
        _audit(
            db,
            actor=actor,
            action="revoke_global_llm",
            target_type="user",
            target_id=str(target.id),
            detail={},
        )


def _audit(
    db: Session,
    *,
    actor: User,
    action: str,
    target_type: str,
    target_id: str | None = None,
    detail: dict | None = None,
) -> AuditLog:
    """写审计日志。detail 必须已脱敏（调用方负责，绝不传 api_key 明文）。"""
    log = AuditLog(
        actor_id=actor.id,
        actor_username=actor.username,  # 冗余，防用户删除后查不到
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail=detail,
    )
    db.add(log)
    db.commit()
    return log
