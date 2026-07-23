"""邀请码服务(内部产品化:关闭开放注册后的账号发号机制)。

核心操作:
- generate: admin 生成邀请码(可选 max_uses / expires_in_days)
- validate_and_consume: 注册时核销(校验存在/未吊销/未过期/未用尽,used_count+1)
- revoke: admin 吊销
- list_codes / get_code: admin 后台查询

生成规则:8 位,字母表剔除易混淆字符(0O1I),secrets 防预测。
碰撞:32^8 ≈ 1.1e12,加 unique 约束 + 重试兜底。

审计:生成/核销/吊销写 audit_logs,复用 admin_service._audit 的模式。
"""

import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.models import AuditLog, InviteCode, User

# 剔除易混淆字符:0 O 1 I
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_CODE_LENGTH = 8
_DEFAULT_EXPIRES_DAYS = 7
_MAX_GENERATE_RETRIES = 10


def _is_expired(expires_at: datetime | None) -> bool:
    """判断是否过期。兼容 sqlite 返回 naive datetime 的情况(同 share_service 模式)。"""
    if expires_at is None:
        return False
    exp = expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return exp < datetime.now(timezone.utc)


def _generate_code() -> str:
    """生成单个 8 位邀请码。"""
    return "".join(secrets.choice(_ALPHABET) for _ in range(_CODE_LENGTH))


def generate_code(
    db: Session,
    *,
    actor: User,
    max_uses: int = 1,
    expires_in_days: int | None = _DEFAULT_EXPIRES_DAYS,
) -> InviteCode:
    """生成邀请码。max_uses 控制可用次数;expires_in_days=None 表示不过期。

    碰撞极罕见(unique 约束 + 重试兜底)。
    """
    if max_uses < 1:
        raise ForbiddenError("max_uses 至少为 1")

    expires_at = None
    if expires_in_days is not None:
        expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)

    # 碰撞重试(unique 约束兜底)
    for _ in range(_MAX_GENERATE_RETRIES):
        code = _generate_code()
        existing = db.scalar(select(InviteCode).where(InviteCode.code == code))
        if existing is None:
            break
    else:
        # 理论上几乎不可能(32^8 空间)
        raise ConflictError("邀请码生成失败,请重试")

    invite = InviteCode(
        code=code,
        created_by_id=actor.id,
        max_uses=max_uses,
        used_count=0,
        expires_at=expires_at,
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)

    _audit(
        db, actor=actor, action="generate_invite_code",
        target_type="invite_code", target_id=str(invite.id),
        detail={"code": code, "max_uses": max_uses},
    )
    return invite


def validate_and_consume(db: Session, *, code: str) -> InviteCode:
    """注册时核销邀请码。校验 + used_count+1,同一事务。

    失败原因(均抛 ForbiddenError,不泄露码是否存在以防探测):
    - 不存在 / 已吊销 / 已过期 / 已用尽
    """
    invite = db.scalar(select(InviteCode).where(InviteCode.code == code.upper().strip()))
    # 统一报「邀请码无效」,不区分原因(防探测)
    if invite is None:
        raise ForbiddenError("邀请码无效或已失效")
    if invite.revoked_at is not None:
        raise ForbiddenError("邀请码无效或已失效")
    if _is_expired(invite.expires_at):
        raise ForbiddenError("邀请码无效或已失效")
    if invite.used_count >= invite.max_uses:
        raise ForbiddenError("邀请码无效或已失效")

    invite.used_count += 1
    db.commit()
    db.refresh(invite)
    return invite


def revoke_code(db: Session, *, actor: User, invite_id: uuid.UUID) -> InviteCode:
    """吊销邀请码。写 revoked_at(保留行审计)。已吊销则 no-op。"""
    invite = db.scalar(select(InviteCode).where(InviteCode.id == invite_id))
    if invite is None:
        raise NotFoundError("邀请码不存在")
    if invite.revoked_at is None:
        invite.revoked_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(invite)
        _audit(
            db, actor=actor, action="revoke_invite_code",
            target_type="invite_code", target_id=str(invite.id),
            detail={"code": invite.code},
        )
    return invite


def list_codes(db: Session) -> list[InviteCode]:
    """列出所有邀请码(按创建时间倒序)。admin 后台用。"""
    return list(
        db.scalars(select(InviteCode).order_by(InviteCode.created_at.desc()))
    )


def code_status(invite: InviteCode) -> str:
    """计算邀请码状态文案:active / exhausted / revoked / expired。"""
    if invite.revoked_at is not None:
        return "revoked"
    if _is_expired(invite.expires_at):
        return "expired"
    if invite.used_count >= invite.max_uses:
        return "exhausted"
    return "active"


def code_to_dict(invite: InviteCode) -> dict:
    """邀请码转 dict(给 admin API 返回)。含计算出的 status。"""
    return {
        "id": str(invite.id),
        "code": invite.code,
        "max_uses": invite.max_uses,
        "used_count": invite.used_count,
        "status": code_status(invite),
        "expires_at": invite.expires_at.isoformat() if invite.expires_at else None,
        "revoked_at": invite.revoked_at.isoformat() if invite.revoked_at else None,
        "created_by_id": str(invite.created_by_id) if invite.created_by_id else None,
        "created_at": invite.created_at.isoformat() if invite.created_at else None,
    }


def _audit(
    db: Session,
    *,
    actor: User,
    action: str,
    target_type: str,
    target_id: str | None = None,
    detail: dict | None = None,
) -> AuditLog:
    """写审计日志(与 admin_service._audit 同模式)。"""
    log = AuditLog(
        actor_id=actor.id,
        actor_username=actor.username,
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail=detail,
    )
    db.add(log)
    db.commit()
    return log
