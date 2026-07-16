from fastapi import APIRouter, BackgroundTasks, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.exceptions import NotFoundError, ValidationError
from app.core.storage import get_storage
from app.deps import get_current_user
from app.models import User
from app.schemas.template import ParseJobOut, TemplateOut, TemplateSummary
from app.services import parse_service, template_service

router = APIRouter(prefix="/templates", tags=["templates"])


@router.get("", response_model=list[TemplateSummary])
def list_all(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    templates = template_service.list_templates(db, user_id=current_user.id)
    return [
        TemplateSummary(
            id=str(t.id), name=t.name, is_default=t.is_default,
            is_system=t.is_system, section_count=len(t.structure),
        )
        for t in templates
    ]


@router.post("", response_model=dict, status_code=202)
async def upload(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """上传 Word 文件创建模板。返回 202，解析在后台执行；前端轮询 parse-job 状态。"""
    if not file.filename or not file.filename.lower().endswith(".docx"):
        raise ValidationError("仅支持 .docx 文件")
    content = await file.read()
    job = parse_service.create_parse_job(
        db, storage=get_storage(), user_id=current_user.id,
        filename=file.filename, file_bytes=content,
    )
    # 真异步：BackgroundTasks 在响应返回后才执行，用 standalone 自开 session
    background_tasks.add_task(
        parse_service.run_parse_job_standalone, str(job.id)
    )
    return {"parse_job_id": str(job.id), "status": "processing"}


@router.get("/parse-jobs/{job_id}", response_model=ParseJobOut)
def get_parse_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """查询解析任务状态（前端轮询用）。

    注意路由顺序：必须声明在 GET /{template_id} 之前，否则
    "parse-jobs" 会被当作 template_id 匹配。
    """
    import uuid as _uuid

    from app.models import ParseJob

    try:
        pk = _uuid.UUID(job_id)
    except (ValueError, TypeError):
        raise NotFoundError("解析任务不存在")
    job = db.get(ParseJob, pk)
    if job is None or job.user_id != current_user.id:
        raise NotFoundError("解析任务不存在")
    return ParseJobOut(
        id=str(job.id),
        status=job.status,
        template_id=str(job.template_id) if job.template_id else None,
        error_message=job.error_message,
    )


@router.get("/{template_id}", response_model=TemplateOut)
def get_one(
    template_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    t = template_service.get_template(db, user_id=current_user.id, template_id=template_id)
    return TemplateOut(
        id=str(t.id), name=t.name, source_filename=t.source_filename,
        structure=t.structure, styles=t.styles, numbering=t.numbering,
        is_default=t.is_default, is_system=t.is_system, created_at=t.created_at,
    )


@router.delete("/{template_id}", status_code=204)
def delete(
    template_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    template_service.delete_template(db, user_id=current_user.id, template_id=template_id)
    return None


@router.post("/{template_id}/default", response_model=TemplateSummary)
def set_default(
    template_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    t = template_service.set_default(db, user_id=current_user.id, template_id=template_id)
    return TemplateSummary(
        id=str(t.id), name=t.name, is_default=t.is_default,
        is_system=t.is_system, section_count=len(t.structure),
    )
