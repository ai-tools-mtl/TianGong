"""管理员：内容生产域（/admin/content/templates/* + /admin/knowledge/upload）。

从原 admin.py 拆出（refactor/admin-api-split）。包含：
- GET    /admin/content/templates                  系统模板列表
- POST   /admin/content/templates/upload           admin 上传 docx（202 + parse_job_id）
- GET    /admin/content/templates/parse-jobs/{id}  轮询解析状态
- POST   /admin/content/templates/{id}/status      改状态（状态机校验）
- DELETE /admin/content/templates/{id}             删除（拒删 published）
- POST   /admin/knowledge/upload                   admin 直传全局库（免审）

路由顺序约束：parse-jobs 必须在 {template_id} 之前。
"""

import uuid as _uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.exceptions import NotFoundError, ValidationError
from app.core.storage import get_storage
from app.deps import require_admin
from app.models import User
from app.services import knowledge_service, parse_service

router = APIRouter(tags=["admin"])


class TemplateStatusUpdate(BaseModel):
    """改模板状态的请求体。允许值：draft / published / offline。"""
    status: str


@router.get("/admin/content/templates")
def list_admin_templates(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """admin 视角：所有系统模板（含 draft/offline/published）。"""
    from app.schemas.template import TemplateSummary
    from app.services import template_service

    templates = template_service.list_system_templates(db)
    return [
        TemplateSummary(
            id=str(t.id), name=t.name, is_default=t.is_default,
            is_system=t.is_system, status=t.status, section_count=len(t.structure),
        )
        for t in templates
    ]


@router.post("/admin/content/templates/upload")
async def upload_admin_template(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """admin 上传 docx 创建内置模板（is_system=True, status='draft'）。

    返回 202，解析在 BackgroundTasks 异步执行，前端轮询 parse-job 状态。
    """
    if not file.filename or not file.filename.lower().endswith(".docx"):
        raise ValidationError("仅支持 .docx 文件")
    content = await file.read()
    parse_service.validate_docx_bytes(content, file.filename)
    job = parse_service.create_parse_job(
        db, storage=get_storage(), user_id=admin.id,
        filename=file.filename, file_bytes=content, is_system=True,
    )
    background_tasks.add_task(parse_service.run_parse_job_standalone, str(job.id))
    return {"parse_job_id": str(job.id), "status": "processing"}


# 注意路由顺序：必须在 /admin/content/templates/{template_id} 之前，
# 否则 'parse-jobs' 会被当 template_id 匹配。
@router.get("/admin/content/templates/parse-jobs/{job_id}")
def get_admin_parse_job(
    job_id: str,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """查询 admin 解析任务状态（前端轮询用）。"""
    from app.models import ParseJob
    from app.schemas.template import ParseJobOut

    try:
        pk = _uuid.UUID(job_id)
    except (ValueError, TypeError):
        raise NotFoundError("解析任务不存在")
    job = db.get(ParseJob, pk)
    if job is None:
        raise NotFoundError("解析任务不存在")
    return ParseJobOut(
        id=str(job.id),
        status=job.status,
        template_id=str(job.template_id) if job.template_id else None,
        error_message=job.error_message,
    )


@router.post("/admin/content/templates/{template_id}/status")
def set_admin_template_status(
    template_id: str,
    payload: TemplateStatusUpdate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """改模板状态（状态机：draft→published→offline→published）。

    非法转换抛 ValidationError，详见 template_service._TEMPLATE_TRANSITIONS。
    """
    from app.schemas.template import TemplateSummary
    from app.services import template_service

    tpl = template_service.set_template_status(
        db, template_id=template_id, status=payload.status,
    )
    return TemplateSummary(
        id=str(tpl.id), name=tpl.name, is_default=tpl.is_default,
        is_system=tpl.is_system, status=tpl.status, section_count=len(tpl.structure),
    )


@router.delete("/admin/content/templates/{template_id}", status_code=204)
def delete_admin_template(
    template_id: str,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """admin 删除系统模板。published 必须先下线（service 层拒删，409 ConflictError）。"""
    from app.services import template_service

    template_service.admin_delete_template(db, template_id=template_id)
    return None


# ── admin 直传全局库（免审，refactor/admin-ia-phase3 切片 C）──

@router.post("/admin/knowledge/upload")
async def upload_global(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """admin 直传全局库(免审,全员立即可检索)。

    异步向量化:落库后立即返回(status=pending),向量化在 BackgroundTasks 后台跑。
    前端轮询文件状态 pending→processing→ready。
    """
    from app.parsing.dispatcher import extract_text as _extract
    from app.core.text_utils import sanitize_filename

    if not file.filename:
        raise ValidationError("缺少文件名")
    # 文件大小上限（防 DoS）
    if file.size and file.size > knowledge_service.MAX_KNOWLEDGE_FILE_SIZE:
        raise ValidationError(
            f"文件过大（{file.size // 1024 // 1024}MB），上限 "
            f"{knowledge_service.MAX_KNOWLEDGE_FILE_SIZE // 1024 // 1024}MB"
        )
    filename = sanitize_filename(file.filename)
    content = await file.read()
    try:
        text = _extract(filename, content)
    except ValueError as e:
        raise ValidationError(str(e))
    kf = knowledge_service.upload_to_global(
        db, storage=get_storage(), uploader=admin,
        filename=filename, content=content,
        mime=file.content_type or "application/octet-stream", text=text,
    )
    # 向量化在响应返回后的后台任务执行(自开 session),不阻塞本请求
    background_tasks.add_task(knowledge_service.run_embed_job_standalone, str(kf.id))
    return {
        "file_id": str(kf.id), "scope": kf.scope, "source_type": kf.source_type,
        "status": kf.status, "stage": kf.stage,
    }


@router.delete("/admin/knowledge/files/{file_id}", status_code=204)
def delete_global_knowledge_file(
    file_id: str,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """admin 删除全局库文件(硬删除:KF + minio 对象 + 关联 chunk)。"""
    knowledge_service.delete_global_file(
        db, storage=get_storage(), file_id=file_id,
    )
    return None
