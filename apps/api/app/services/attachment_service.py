"""附件服务：存盘 + 魔数校验 + CRUD（设计 13.2 文件上传安全）。"""

import os
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import NotFoundError, ValidationError
from app.models import Attachment

# 图片魔数签名（设计 13.2：不轻信扩展名，校验魔数）
_MAGIC_NUMBERS = {
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"\xff\xd8\xff": "image/jpeg",
    b"GIF8": "image/gif",
}

ALLOWED_MIME = {"image/png", "image/jpeg", "image/gif"}


def _detect_mime(content: bytes) -> str | None:
    """通过魔数检测真实 MIME 类型。"""
    for magic, mime in _MAGIC_NUMBERS.items():
        if content.startswith(magic):
            return mime
    return None


def _ext_for_mime(mime: str) -> str:
    return {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif"}.get(mime, ".bin")


def upload_attachment(
    db: Session, *, user_id, project_id: str, section_id: str | None,
    filename: str, content: bytes,
) -> Attachment:
    """校验 + 存盘 + 建记录。"""
    settings = get_settings()

    # 魔数校验（设计 13.2）
    real_mime = _detect_mime(content)
    if real_mime is None or real_mime not in ALLOWED_MIME:
        raise ValidationError("仅支持 PNG/JPEG/GIF 图片")

    # 大小校验
    max_bytes = settings.max_image_size_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise ValidationError(f"图片大小超过 {settings.max_image_size_mb}MB 限制")

    # UUID 存储名（防路径遍历，设计 13.2）
    stored_name = f"{uuid.uuid4()}{_ext_for_mime(real_mime)}"
    upload_dir = settings.upload_dir
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, stored_name)
    with open(file_path, "wb") as f:
        f.write(content)

    att = Attachment(
        project_id=uuid.UUID(project_id),
        section_id=uuid.UUID(section_id) if section_id else None,
        filename=filename,
        storage_path=file_path,
        mime_type=real_mime,
        size=len(content),
    )
    db.add(att)
    db.commit()
    db.refresh(att)
    return att


def list_attachments(
    db: Session, *, user_id, project_id: str, section_id: str | None = None,
) -> list[Attachment]:
    """列出项目的附件（先校验项目归属）。"""
    from app.models import Project

    project = db.scalar(select(Project).where(Project.id == uuid.UUID(project_id)))
    if project is None or project.user_id != user_id:
        raise NotFoundError("项目不存在")
    query = select(Attachment).where(Attachment.project_id == project.id)
    if section_id:
        query = query.where(Attachment.section_id == uuid.UUID(section_id))
    return list(db.scalars(query.order_by(Attachment.created_at)))


def get_attachment(db: Session, *, user_id, attachment_id: str) -> Attachment:
    """获取附件（含归属校验）。"""
    try:
        aid = uuid.UUID(attachment_id)
    except ValueError:
        raise NotFoundError("附件不存在")
    att = db.get(Attachment, aid)
    if att is None:
        raise NotFoundError("附件不存在")
    # 通过 project 校验归属
    from app.models import Project

    project = db.scalar(select(Project).where(Project.id == att.project_id))
    if project is None or project.user_id != user_id:
        raise NotFoundError("附件不存在")
    return att


def delete_attachment(db: Session, *, user_id, attachment_id: str) -> None:
    """删除附件（记录 + 文件）。"""
    att = get_attachment(db, user_id=user_id, attachment_id=attachment_id)
    # 删文件
    if os.path.exists(att.storage_path):
        os.remove(att.storage_path)
    db.delete(att)
    db.commit()
