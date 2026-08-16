"""经授权临时查看服务（设计 §8.3 完整版）。

用户为指定项目生成一次性求助短码 → admin 凭码核销（redeemed_at/by + 开
30 分钟查看窗口 view_expires_at）→ 窗口内仅核销 admin 可反复只读查看
（每次访问由 API 层写审计）。用户可随时吊销。

防探测：所有失败原因（不存在/过期/已核销/吊销/非核销人）统一
NotFoundError「授权码无效或已失效」，不泄露码的存在性。
生命周期状态计算 code_status()：active / redeemed(窗口中) / expired / revoked。
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.models import SupportAccessCode, User

_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # 剔除易混淆 0 O 1 I（同 invite）
_CODE_LENGTH = 8
_MAX_GENERATE_RETRIES = 10

# 码有效期与查看窗口（分钟）。§8.3 语义：短时授权，用完即止。
DEFAULT_CODE_TTL_MINUTES = 30
DEFAULT_VIEW_WINDOW_MINUTES = 30


def _is_past(dt: datetime | None) -> bool:
    """判断是否已过时刻。兼容 sqlite 返回 naive datetime 的情况（同 invite/share 模式）。"""
    if dt is None:
        return False
    exp = dt
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return exp < datetime.now(timezone.utc)


def _generate_code() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(_CODE_LENGTH))


def generate_code(
    db: Session, *, project_id, user: User,
    ttl_minutes: int = DEFAULT_CODE_TTL_MINUTES,
) -> SupportAccessCode:
    """用户为项目生成一次性求助码（默认 30 分钟内须被核销）。"""
    if ttl_minutes < 1 or ttl_minutes > 24 * 60:
        raise ConflictError("有效期须在 1 分钟到 24 小时之间")

    expires_at = datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)
    for _ in range(_MAX_GENERATE_RETRIES):
        code = _generate_code()
        if db.scalar(select(SupportAccessCode).where(
                SupportAccessCode.code == code)) is None:
            break
    else:  # pragma: no cover - 32^8 空间，几乎不可能
        raise ConflictError("授权码生成失败，请重试")

    row = SupportAccessCode(
        code=code, project_id=project_id, created_by=user.id,
        expires_at=expires_at,
    )
    db.add(row)
    db.commit()
    return row


def list_codes(db: Session, *, user_id, project_id) -> list[SupportAccessCode]:
    """列出用户为某项目生成的授权码（新→旧）。"""
    return list(db.scalars(
        select(SupportAccessCode)
        .where((SupportAccessCode.project_id == project_id)
               & (SupportAccessCode.created_by == user_id))
        .order_by(SupportAccessCode.created_at.desc())
    ))


def revoke_code(db: Session, *, code_id, user_id) -> None:
    """用户吊销自己的授权码（幂等：已吊销不报错）。"""
    row = db.get(SupportAccessCode, code_id)
    if row is None or row.created_by != user_id:
        raise NotFoundError("授权码不存在")
    if row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)
        db.commit()


def code_status(row: SupportAccessCode) -> str:
    """计算状态：active（待核销）/ redeemed（查看窗口中）/ expired / revoked。"""
    if row.revoked_at is not None:
        return "revoked"
    if _is_past(row.expires_at) and row.redeemed_at is None:
        return "expired"
    if row.redeemed_at is not None:
        return "redeemed" if not _is_past(row.view_expires_at) else "expired"
    return "active"


def verify_and_redeem(
    db: Session, *, code: str, admin: User,
    view_window_minutes: int = DEFAULT_VIEW_WINDOW_MINUTES,
) -> tuple[SupportAccessCode, object]:
    """admin 凭码核销：校验 + 一次性核销 + 开查看窗口。返回 (授权码, 项目)。

    失败统一 NotFoundError（防探测）。已核销/过期/吊销均不可再核销。
    """
    row = db.scalar(select(SupportAccessCode).where(SupportAccessCode.code == (code or "").strip().upper()))
    if row is None:
        raise NotFoundError("授权码无效或已失效")
    if row.revoked_at is not None or row.redeemed_at is not None or _is_past(row.expires_at):
        raise NotFoundError("授权码无效或已失效")

    project = _load_project(db, row.project_id)
    if project is None:
        raise NotFoundError("授权码无效或已失效")

    now = datetime.now(timezone.utc)
    row.redeemed_at = now
    row.redeemed_by = admin.id
    row.view_expires_at = now + timedelta(minutes=view_window_minutes)
    db.commit()
    return row, project


def _load_project(db: Session, project_id):
    from app.models import Project

    return db.get(Project, project_id)


def verify_view_access(db: Session, *, code: str, admin: User) -> tuple[SupportAccessCode, object]:
    """查看窗口内校验访问权（仅核销该码的 admin）。返回 (授权码, 项目)。

    供核销后的重复查看（GET）用：未过期窗口内、 redeemed_by==admin 才放行，
    其余统一 NotFoundError。
    """
    row = db.scalar(select(SupportAccessCode).where(SupportAccessCode.code == (code or "").strip().upper()))
    if (row is None or row.redeemed_at is None
            or row.redeemed_by != admin.id
            or _is_past(row.view_expires_at) or row.revoked_at is not None):
        raise NotFoundError("授权码无效或已失效")
    project = _load_project(db, row.project_id)
    if project is None:
        raise NotFoundError("授权码无效或已失效")
    return row, project
