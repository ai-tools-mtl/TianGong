"""经授权临时查看——用户侧端点（设计 §8.3 完整版）。

用户为「自己的项目」生成一次性求助短码发给管理员；管理员凭码在
admin/support.py 的核销端点获得限时只读查看窗口。

owner-only：统一 project_service.get_project 归属校验（非 owner 404 防探测）。
"""

from datetime import datetime

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.deps import get_current_user
from app.models import User
from app.services import project_service, support_access_service

router = APIRouter(tags=["support"])


class SupportCodeCreate(BaseModel):
    """生成求助码。ttl_minutes：码本身的有效期（须在此窗口内被管理员核销）。"""
    ttl_minutes: int = Field(default=30, ge=1, le=1440)


class SupportCodeOut(BaseModel):
    id: str
    code: str
    project_id: str
    expires_at: datetime | None = None
    redeemed_at: datetime | None = None
    view_expires_at: datetime | None = None
    revoked_at: datetime | None = None
    status: str  # active / redeemed / expired / revoked
    created_at: datetime

    @classmethod
    def from_row(cls, row) -> "SupportCodeOut":
        return cls(
            id=str(row.id),
            code=row.code,
            project_id=str(row.project_id),
            expires_at=row.expires_at,
            redeemed_at=row.redeemed_at,
            view_expires_at=row.view_expires_at,
            revoked_at=row.revoked_at,
            status=support_access_service.code_status(row),
            created_at=row.created_at,
        )


@router.post(
    "/projects/{project_id}/support-codes",
    response_model=SupportCodeOut,
    status_code=status.HTTP_201_CREATED,
)
def create_support_code(
    project_id: str,
    payload: SupportCodeCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """生成一次性求助码（owner-only）。发给管理员后，对方凭码获得限时只读查看。"""
    project = project_service.get_project(db, user=current_user, project_id=project_id)
    row = support_access_service.generate_code(
        db, project_id=project.id, user=current_user, ttl_minutes=payload.ttl_minutes)
    return SupportCodeOut.from_row(row)


@router.get("/projects/{project_id}/support-codes", response_model=list[SupportCodeOut])
def list_support_codes(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """列出我为该项目生成的求助码及状态（owner-only）。"""
    project = project_service.get_project(db, user=current_user, project_id=project_id)
    rows = support_access_service.list_codes(db, user_id=current_user.id, project_id=project.id)
    return [SupportCodeOut.from_row(r) for r in rows]


@router.delete(
    "/projects/{project_id}/support-codes/{code_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def revoke_support_code(
    project_id: str,
    code_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """吊销求助码（owner-only，幂等）。吊销后查看窗口立即失效。"""
    import uuid as _uuid

    project = project_service.get_project(db, user=current_user, project_id=project_id)
    support_access_service.revoke_code(
        db, code_id=_uuid.UUID(code_id), user_id=current_user.id)
    return None
