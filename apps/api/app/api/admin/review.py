"""管理员：知识库审核域（/admin/knowledge/reviews/*）。

从原 admin.py 拆出（refactor/admin-api-split）。包含：
- GET   /admin/knowledge/reviews              待审核工单列表
- POST  /admin/knowledge/reviews/{id}/approve 审核通过
- POST  /admin/knowledge/reviews/{id}/reject  审核拒绝
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.storage import get_storage
from app.deps import require_admin
from app.models import User

router = APIRouter(tags=["admin"])


class RejectComment(BaseModel):
    comment: str | None = None


def _review_out(r, filename: str | None = None) -> dict:
    return {
        "id": str(r.id),
        "submitter_id": str(r.submitter_id),
        "reviewer_id": str(r.reviewer_id) if r.reviewer_id else None,
        "source_type": r.source_type,
        "file_id": str(r.file_id),
        "filename": filename,  # 联查 KnowledgeFile 得到,供审核工作台展示
        "status": r.status,
        "review_comment": r.review_comment,
        "created_at": r.created_at.isoformat(),
        "reviewed_at": r.reviewed_at.isoformat() if r.reviewed_at else None,
    }


@router.get("/admin/knowledge/reviews")
def list_pending_reviews(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """待审核工单列表(时间倒序,带文件名便于审核)。"""
    from app.models import KnowledgeFile
    from app.services import knowledge_review_service
    from sqlalchemy import select

    reviews = knowledge_review_service.list_pending(db)
    # 批量联查 file_id → filename,避免 N+1
    file_ids = [r.file_id for r in reviews]
    files_map: dict = {}
    if file_ids:
        files = db.scalars(select(KnowledgeFile).where(KnowledgeFile.id.in_(file_ids)))
        files_map = {f.id: f.filename for f in files}
    return [_review_out(r, files_map.get(r.file_id)) for r in reviews]


@router.post("/admin/knowledge/reviews/{review_id}/approve")
def approve_review(
    review_id: str,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """审核通过:文件升 global + chunk 升 global。"""
    from app.services import knowledge_review_service

    review = knowledge_review_service.approve(
        db, storage=get_storage(), reviewer=admin, review_id=review_id,
    )
    return _review_out(review)


@router.post("/admin/knowledge/reviews/{review_id}/reject")
def reject_review(
    review_id: str,
    payload: RejectComment,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """审核拒绝:文件留 personal,user 仍可用。"""
    from app.services import knowledge_review_service

    review = knowledge_review_service.reject(
        db, reviewer=admin, review_id=review_id, comment=payload.comment,
    )
    return _review_out(review)
