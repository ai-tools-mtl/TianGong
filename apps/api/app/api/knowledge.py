from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.deps import get_current_user
from app.models import User
from app.services import archive_service

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
