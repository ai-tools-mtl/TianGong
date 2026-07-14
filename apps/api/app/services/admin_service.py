"""管理员运营服务：封禁/解禁/重置密码 + 自我保护 + 审计 helper（设计 8.1/8.3）。

自我保护（设计 8.1，针对「封禁」语义）：
1. 不能封禁自己（ban: target.id == actor.id → 403）
2. 不能封禁超管（ban: target.is_superuser → 403）
3. 不能封禁其他管理员（ban: target.role == "admin" → 403）
重置密码约束更宽：仅禁「重置自己」（防误锁死自己），对超管/其他管理员放行。
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ForbiddenError, NotFoundError
from app.core.security import hash_password
from app.models import AuditLog, User


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
    """取目标用户 + 自我保护校验。action ∈ {ban, reset}。

    共同约束：不能操作自己（ban/reset 都禁自身）。
    ban 额外约束：不能封禁超管、不能封禁其他管理员。
    reset 对超管/其他管理员放行（重置密码不改账号可用性）。
    """
    target = db.scalar(select(User).where(User.id == user_id))
    if target is None:
        raise NotFoundError("用户不存在")

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

    return target


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
        actor_email=actor.email,  # 冗余，防用户删除后查不到
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail=detail,
    )
    db.add(log)
    db.commit()
    return log
