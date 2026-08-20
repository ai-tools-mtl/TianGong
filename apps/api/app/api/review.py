from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.deps import get_current_user
from app.models import ReviewRecord, User
from app.schemas.review import RubricOut, RubricUpdate
from app.services import project_service, review_service, rubric_service

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
        "cross_section_issues": r.cross_section_issues or [],
        "section_issues": r.section_issues or [],
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


@router.get("/projects/{project_id}/review/status")
def get_review_status(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """审查进行中状态（dogfood 2026-08-19）：审查是分钟级同步长任务，
    前端离开页面重进后凭此恢复「进行中」展示并禁用重复触发。"""
    project = project_service.get_project(db, user=current_user, project_id=project_id)
    started_at = review_service.is_review_running(project.id)
    return {"running": started_at is not None, "started_at": started_at}


@router.get("/projects/{project_id}/reviews")
def list_reviews(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # 校验项目归属：越权/不存在一律返回 404（防探测，设计 13.1）。
    # 用 project.id（UUID）查询，避免路径 str 直接绑定 Uuid 列导致的类型错误。
    project = project_service.get_project(db, user=current_user, project_id=project_id)
    records = list(db.scalars(
        select(ReviewRecord)
        .where(ReviewRecord.project_id == project.id)
        .order_by(ReviewRecord.created_at.desc())
    ))
    return [_record_to_dict(r) for r in records]


@router.get("/projects/{project_id}/reviews/trend")
def get_review_trend(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """多轮审查趋势数据（供前端画趋势图）。

    返回 [{round, total_score, dimension_scores: {key: score}, created_at}]，
    按轮次升序（时间正序）。
    """
    project = project_service.get_project(db, user=current_user, project_id=project_id)
    records = list(db.scalars(
        select(ReviewRecord)
        .where(ReviewRecord.project_id == project.id)
        .order_by(ReviewRecord.created_at.asc())
    ))
    return [
        {
            "round": r.round,
            "total_score": r.total_score,
            "dimension_scores": {d["key"]: d["score"] for d in r.dimension_scores},
            "created_at": r.created_at.isoformat(),
        }
        for r in records
    ]


@router.get("/projects/{project_id}/reviews/{review_id}/export-pdf")
def export_review_report(
    project_id: str,
    review_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """导出审查报告为 PDF（复用 pdf_service 基建）。

    需 weasyprint 系统库，缺失时 500。
    """
    import uuid as uuid_mod
    project = project_service.get_project(db, user=current_user, project_id=project_id)

    try:
        rid = uuid_mod.UUID(review_id)
    except ValueError:
        raise NotFoundError("审查记录不存在")

    review = db.get(ReviewRecord, rid)
    if review is None or review.project_id != project.id:
        raise NotFoundError("审查记录不存在")

    from app.services.review_export_service import export_review_report as _export
    pdf_bytes = _export(db, project=project, review=review)
    return Response(
        pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''审查报告-第{review.round}轮.pdf"},
    )


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
