"""附件/附图路由（设计 13.2 文件上传安全）。"""

import os

from fastapi import APIRouter, Depends, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.deps import get_current_user
from app.models import User
from app.services import attachment_service, section_service

router = APIRouter(tags=["attachments"])


def _to_out(a) -> dict:
    return {
        "id": str(a.id),
        "project_id": str(a.project_id),
        "section_id": str(a.section_id) if a.section_id else None,
        "filename": a.filename,
        "mime_type": a.mime_type,
        "size": a.size,
        "created_at": a.created_at.isoformat(),
    }


@router.post("/sections/{section_id}/attachments", status_code=201)
async def upload(
    section_id: str,
    file: UploadFile,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """上传图片到指定章节（先校验章节归属）。"""
    # 校验章节归属（复用 section_service 的资源级授权）
    section = section_service.get_section(db, user_id=current_user.id, section_id=section_id)
    content = await file.read()
    att = attachment_service.upload_attachment(
        db, user_id=current_user.id,
        project_id=str(section.project_id), section_id=section_id,
        filename=file.filename or "upload.png", content=content,
    )
    return _to_out(att)


@router.get("/projects/{project_id}/attachments")
def list_all(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """列出项目的所有附件。"""
    atts = attachment_service.list_attachments(
        db, user_id=current_user.id, project_id=project_id
    )
    return [_to_out(a) for a in atts]


@router.get("/projects/{project_id}/attachments/{attachment_id}/file")
def download(
    project_id: str,
    attachment_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """鉴权后返回图片流（不暴露真实路径）。"""
    att = attachment_service.get_attachment(db, user_id=current_user.id, attachment_id=attachment_id)
    if not os.path.exists(att.storage_path):
        from app.core.exceptions import NotFoundError

        raise NotFoundError("文件不存在")
    return FileResponse(
        att.storage_path, media_type=att.mime_type, filename=att.filename,
    )


@router.delete("/attachments/{attachment_id}", status_code=204)
def delete(
    attachment_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    attachment_service.delete_attachment(db, user_id=current_user.id, attachment_id=attachment_id)
    return None
