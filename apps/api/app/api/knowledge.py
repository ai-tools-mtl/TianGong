"""知识库路由:归档 + 检索 + 三域文件管理(计划 T11)。

新增端点:
- POST /knowledge/upload         user 上传外部素材到个人库
- POST /knowledge/files/{id}/submit-review   user 上报进全局审核
- GET  /knowledge/files/{id}/download        下载文件(personal 仅本人,global 全员)
- GET  /knowledge/files/personal             列出本人个人库
- GET  /knowledge/files/global               列出全局库(全员可见)
"""

import uuid as _uuid

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.exceptions import NotFoundError, ValidationError
from app.core.storage import get_storage
from app.deps import get_current_user
from app.models import KnowledgeFile, User
from app.parsing.dispatcher import extract_text
from app.services import archive_service, knowledge_service

router = APIRouter(tags=["knowledge"])


class SearchRequest(BaseModel):
    query: str
    top_k: int = 3


@router.post("/projects/{project_id}/archive")
def archive_project(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = archive_service.archive(db, user_id=current_user.id, project_id=project_id)
    return result


@router.post("/knowledge/search")
def search(
    payload: SearchRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """检索知识库。"""
    from app.rag.retriever import retrieve

    results = retrieve(db, user_id=current_user.id, query=payload.query, top_k=payload.top_k)
    return [
        {
            "content": r.content[:300],
            "score": round(r.score, 3),
            "section_key": r.source_section_key,
            "project_title": r.project_title,
        }
        for r in results
    ]


# ── 三域文件管理 ──────────────────────────────────────────────


def _file_out(kf: KnowledgeFile) -> dict:
    return {
        "id": str(kf.id),
        "uploader_id": str(kf.uploader_id),
        "scope": kf.scope,
        "filename": kf.filename,
        "mime_type": kf.mime_type,
        "size": kf.size,
        "source_type": kf.source_type,
        "created_at": kf.created_at.isoformat(),
    }


@router.post("/knowledge/upload")
async def upload_personal(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """user 上传外部素材(docx/pdf)到个人库。"""
    if not file.filename:
        raise ValidationError("缺少文件名")
    content = await file.read()
    try:
        text = extract_text(file.filename, content)
    except ValueError as e:
        raise ValidationError(str(e))
    kf = knowledge_service.upload_external(
        db, storage=get_storage(), user=current_user,
        filename=file.filename, content=content,
        mime=file.content_type or "application/octet-stream", text=text,
    )
    return _file_out(kf)


@router.post("/knowledge/files/{file_id}/submit-review")
def submit_review(
    file_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """user 上报个人素材进全局审核。建 pending 工单(幂等)。"""
    review = knowledge_service.submit_for_review(
        db, submitter_id=str(current_user.id), file_id=file_id,
    )
    return {"review_id": str(review.id), "status": review.status}


@router.post("/projects/{project_id}/submit-disclosure-review")
def submit_disclosure_review(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """归档交底书上报进全局审核(流 A)。生成导出 docx 存 minio + 建工单。"""
    from app.models import Project
    from app.services.project_service import get_project

    project = get_project(db, user=current_user, project_id=project_id)
    if project.status != "archived":
        raise ValidationError("仅已归档项目可上报")
    review = knowledge_service.submit_disclosure_for_review(
        db, storage=get_storage(), submitter=current_user, project=project,
    )
    return {"review_id": str(review.id), "status": review.status}


@router.get("/knowledge/files/{file_id}/download")
def download_file(
    file_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """下载知识库文件。personal 仅本人(越权 404),global 全员可读。"""
    try:
        fid = _uuid.UUID(file_id)
    except ValueError:
        raise NotFoundError("文件不存在")
    kf = db.get(KnowledgeFile, fid)
    if kf is None:
        raise NotFoundError("文件不存在")
    if kf.scope == "personal" and kf.uploader_id != current_user.id:
        raise NotFoundError("文件不存在")  # 越权 404,不暴露存在性
    try:
        content = get_storage().get(kf.bucket, kf.object_key)
    except Exception:
        raise NotFoundError("文件不存在")
    return Response(
        content=content, media_type=kf.mime_type,
        headers={"Content-Disposition": f'attachment; filename="{kf.filename}"'},
    )


@router.get("/knowledge/files/personal")
def list_personal(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """列出本人个人库文件。"""
    files = knowledge_service.list_personal_files(db, user_id=current_user.id)
    return [_file_out(kf) for kf in files]


@router.get("/knowledge/files/global")
def list_global(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """列出全局库文件(所有登录 user 可见)。"""
    files = knowledge_service.list_global_files(db)
    return [_file_out(kf) for kf in files]
