from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.deps import get_current_user
from app.models import User
from app.services import export_service, project_service

router = APIRouter(tags=["export"])


@router.get("/projects/{project_id}/preview")
def preview(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """全篇预览（合并章节）。"""
    project = project_service.get_project(db, user=current_user, project_id=project_id)
    sections = export_service._get_ordered_sections(db, project)
    return {
        "title": project.title,
        "metadata": project.metadata_,
        "sections": [
            {
                "order": s.order, "key": s.key, "title": s.title,
                "content": s.content, "status": s.status,
            }
            for s in sections
        ],
    }


@router.get("/projects/{project_id}/export/markdown")
def export_markdown(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = project_service.get_project(db, user=current_user, project_id=project_id)
    md = export_service.export_markdown(db, project=project)
    return PlainTextResponse(
        md,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{project.title}.md"},
    )


@router.get("/projects/{project_id}/export/docx")
def export_docx(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = project_service.get_project(db, user=current_user, project_id=project_id)
    docx_bytes = export_service.export_docx(db, project=project)
    return Response(
        docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": "attachment; filename=project.docx"},
    )
