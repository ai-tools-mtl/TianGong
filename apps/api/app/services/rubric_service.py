from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ReviewRubric


def get_effective_rubric(db: Session, *, user_id) -> ReviewRubric:
    """获取生效的 Rubric：用户自定义 > 系统默认。"""
    user_rubric = db.scalar(
        select(ReviewRubric).where(ReviewRubric.user_id == user_id)
    )
    if user_rubric:
        return user_rubric
    return db.scalar(select(ReviewRubric).where(ReviewRubric.scope == "system"))


def update_user_rubric(
    db: Session, *, user_id, criteria: list[dict], name: str | None = None
) -> ReviewRubric:
    """更新用户 Rubric（覆盖式）。"""
    existing = db.scalar(select(ReviewRubric).where(ReviewRubric.user_id == user_id))
    if existing:
        existing.criteria = criteria
        if name:
            existing.name = name
        existing.is_customized = True
        db.commit()
        db.refresh(existing)
        return existing
    rubric = ReviewRubric(
        user_id=user_id, scope="user",
        name=name or "我的评分标准",
        criteria=criteria, is_customized=True,
    )
    db.add(rubric)
    db.commit()
    db.refresh(rubric)
    return rubric


def reset_rubric(db: Session, *, user_id) -> None:
    """恢复系统默认（删除用户 Rubric）。"""
    existing = db.scalar(select(ReviewRubric).where(ReviewRubric.user_id == user_id))
    if existing:
        db.delete(existing)
        db.commit()
