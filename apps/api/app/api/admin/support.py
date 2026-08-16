"""经授权临时查看——admin 侧端点（设计 §8.3 完整版）。

管理员凭用户提供的授权码核销（一次性）并获得限时只读查看窗口；窗口内
可反复查看（每次访问写审计）。只读视图复用游客浏览的全套拼装逻辑
（_get_ordered_sections + inline_share_images），但不暴露在公开路由上。

数据可见性红线（§8.3）：admin 凭码才能看内容；码的核销/查看全程写审计
（action=support_view_project），审计 detail 不含码明文。
"""

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.deps import require_admin
from app.models import User
from app.schemas.share import SharedProject, SharedSection
from app.services import admin_service, export_service, support_access_service

router = APIRouter(tags=["admin"])


class RedeemRequest(BaseModel):
    code: str = Field(min_length=1, max_length=32)


class SupportViewOut(BaseModel):
    """核销/查看响应：项目只读视图 + 窗口信息 + 求助用户信息。"""
    code_id: str
    project_id: str
    project_title: str
    owner_id: str
    owner_name: str | None = None
    redeemed_at: datetime
    view_expires_at: datetime
    project: SharedProject


def _audit_view(db: Session, admin: User, row, *, action: str) -> None:
    """核销/每次查看都写审计。detail 不含码明文（防审计日志本身泄露凭据）。"""
    admin_service._audit(
        db, actor=admin, action=action,
        target_type="project", target_id=str(row.project_id),
        detail={"code_id": str(row.id), "owner_id": str(row.created_by)},
    )


def _build_view(db: Session, row, project, admin: User, *, action: str) -> SupportViewOut:
    sections = export_service._get_ordered_sections(db, project)
    out_sections = [
        SharedSection(
            order=s.order,
            key=s.key,
            title=s.title,
            status=s.status,
            content=export_service.inline_share_images(db, s.content, project.id)
            if s.content
            else None,
        )
        for s in sections
    ]
    owner = db.get(User, row.created_by)
    _audit_view(db, admin, row, action=action)
    return SupportViewOut(
        code_id=str(row.id),
        project_id=str(project.id),
        project_title=project.title,
        owner_id=str(row.created_by),
        owner_name=owner.name if owner else None,
        redeemed_at=row.redeemed_at,
        view_expires_at=row.view_expires_at,
        project=SharedProject(
            title=project.title,
            permissions="readonly",
            sections=out_sections,
            metadata=project.metadata_,
        ),
    )


@router.post("/admin/support-codes/redeem")
def redeem_support_code(
    payload: RedeemRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """核销授权码（一次性）：校验通过即开 30 分钟查看窗口，返回项目只读视图。

    不存在/已核销/过期/吊销统一 404（防探测）。核销写审计。
    """
    row, project = support_access_service.verify_and_redeem(db, code=payload.code, admin=admin)
    return _build_view(db, row, project, admin, action="support_view_project")


@router.get("/admin/support-codes/{code}/view", response_model=SupportViewOut)
def view_support_project(
    code: str,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """查看窗口内重复查看（仅核销该码的 admin）。每次查看写审计。"""
    row, project = support_access_service.verify_view_access(db, code=code, admin=admin)
    return _build_view(db, row, project, admin, action="support_view_project")
