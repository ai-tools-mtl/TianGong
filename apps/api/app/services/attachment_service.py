"""附件服务：对象存储 + 魔数校验 + CRUD（设计 13.2 文件上传安全）。

存储改造(计划 T3):本地磁盘 → minio 对象存储。storage_path 字段语义从
"本地完整路径"变为"minio object key",如 attachments/{user_id}/{uuid}.png。
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import NotFoundError, ValidationError
from app.core.storage import Storage
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
    db: Session, *, storage: Storage, user_id, project_id: str,
    section_id: str | None, filename: str, content: bytes,
) -> Attachment:
    """校验 + 存 minio + 建记录。"""
    settings = get_settings()

    # 魔数校验（设计 13.2）
    real_mime = _detect_mime(content)
    if real_mime is None or real_mime not in ALLOWED_MIME:
        raise ValidationError("仅支持 PNG/JPEG/GIF 图片")

    # 大小校验
    max_bytes = settings.max_image_size_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise ValidationError(f"图片大小超过 {settings.max_image_size_mb}MB 限制")

    # object key:personal bucket 下按 user 隔离(防路径遍历,设计 13.2)
    object_key = f"attachments/{user_id}/{uuid.uuid4()}{_ext_for_mime(real_mime)}"
    storage.put("personal", object_key, content, real_mime)

    att = Attachment(
        project_id=uuid.UUID(project_id),
        section_id=uuid.UUID(section_id) if section_id else None,
        filename=filename,
        storage_path=object_key,  # 语义变更:minio object key(不再是本地路径)
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


def delete_attachment(
    db: Session, *, storage: Storage, user_id, attachment_id: str,
) -> None:
    """删除附件（记录 + minio 对象,幂等）。"""
    att = get_attachment(db, user_id=user_id, attachment_id=attachment_id)
    storage.delete("personal", att.storage_path)  # 幂等:对象不存在不抛
    db.delete(att)
    db.commit()
