"""专利检索路由（/projects/{pid}/patents/*）。

对接智慧芽 PatSnap（无 key 时走 Mock 桩），检索结果存 Project.prior_art_refs。
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.deps import get_current_user
from app.models import User
from app.services import patent_service

router = APIRouter(tags=["patents"])


class SearchRequest(BaseModel):
    """专利检索请求。"""
    query: str = Field(..., min_length=1, max_length=500)


@router.post("/projects/{project_id}/patents/search")
def search_patents(
    project_id: str,
    payload: SearchRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """检索现有技术专利，结果持久化到项目 prior_art_refs。"""
    return patent_service.search_prior_art(
        db, user_id=current_user.id, project_id=project_id, query=payload.query,
    )


@router.get("/projects/{project_id}/patents")
def get_patents(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """读取已存的检索结果。无记录返回 null。"""
    return patent_service.get_prior_art(
        db, user_id=current_user.id, project_id=project_id,
    )
