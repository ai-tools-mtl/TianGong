"""管理员：邀请码管理域（/admin/invites/*）。

内部产品化：关闭开放注册后，admin 通过邀请码发号。

- POST   /admin/invites           生成邀请码（可选 max_uses / expires_in_days）
- GET    /admin/invites           邀请码列表
- DELETE /admin/invites/{invite_id}  吊销邀请码
"""

import uuid as _uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.deps import require_admin
from app.models import User
from app.services import invite_service

router = APIRouter(tags=["admin"])


class GenerateInviteRequest(BaseModel):
    """生成邀请码入参。"""
    max_uses: int = Field(default=1, ge=1)
    # 有效天数,None=不过期,默认 7
    expires_in_days: int | None = 7


@router.post("/admin/invites")
def generate_invite(
    payload: GenerateInviteRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """生成邀请码。"""
    invite = invite_service.generate_code(
        db, actor=admin,
        max_uses=payload.max_uses,
        expires_in_days=payload.expires_in_days,
    )
    return invite_service.code_to_dict(invite)


@router.get("/admin/invites")
def list_invites(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """邀请码列表（按创建时间倒序）。"""
    codes = invite_service.list_codes(db)
    return [invite_service.code_to_dict(c) for c in codes]


@router.delete("/admin/invites/{invite_id}")
def revoke_invite(
    invite_id: str,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """吊销邀请码。已吊销则 no-op。"""
    invite_service.revoke_code(db, actor=admin, invite_id=_uuid.UUID(invite_id))
    return {"ok": True}
