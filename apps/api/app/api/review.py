from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.deps import get_current_user
from app.models import ReviewRecord, User
from app.schemas.review import RubricOut, RubricUpdate
from app.services import review_service, rubric_service

router = APIRouter(tags=["review"])


def _record_to_dict(r: ReviewRecord) -> dict:
    return {
        "id": str(r.id),
        "round": r.round,
        "total_score": r.total_score,
        "previous_score": r.previous_score,
        "dimension_scores": r.dimension_scores,
        "resolved_issues": r.resolved_issues,
        "remaining_issues": r.remaining_issues,
        "created_at": r.created_at.isoformat(),
    }


# ── 审查 ──

@router.post("/projects/{project_id}/review")
def run_review(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    record = review_service.run_review(db, user_id=current_user.id, project_id=project_id)
    return _record_to_dict(record)


@router.get("/projects/{project_id}/reviews")
def list_reviews(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    records = list(db.scalars(
        select(ReviewRecord)
        .where(ReviewRecord.project_id == project_id)
        .order_by(ReviewRecord.created_at.desc())
    ))
    return [_record_to_dict(r) for r in records]


# ── Rubric ──

@router.get("/rubric", response_model=RubricOut)
def get_rubric(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rubric = rubric_service.get_effective_rubric(db, user_id=current_user.id)
    return RubricOut(
        id=str(rubric.id), scope=rubric.scope, name=rubric.name,
        criteria=rubric.criteria, is_customized=rubric.is_customized,
    )


@router.put("/rubric", response_model=RubricOut)
def update_rubric(
    payload: RubricUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rubric = rubric_service.update_user_rubric(
        db, user_id=current_user.id,
        criteria=payload.criteria or [], name=payload.name,
    )
    return RubricOut(
        id=str(rubric.id), scope=rubric.scope, name=rubric.name,
        criteria=rubric.criteria, is_customized=rubric.is_customized,
    )


@router.post("/rubric/reset", response_model=RubricOut)
def reset_rubric(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rubric_service.reset_rubric(db, user_id=current_user.id)
    rubric = rubric_service.get_effective_rubric(db, user_id=current_user.id)
    return RubricOut(
        id=str(rubric.id), scope=rubric.scope, name=rubric.name,
        criteria=rubric.criteria, is_customized=rubric.is_customized,
    )
