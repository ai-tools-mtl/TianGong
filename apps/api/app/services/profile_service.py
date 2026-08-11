"""写作画像服务：一对一 upsert（用户显式维护的结构化偏好）。

与 user_memory(source=profile) 的关系：本服务管理结构化画像表，user_memory 管自由记忆，
两者在 context_assembler 里并存（本表强注入，user_memory 走语义检索）。
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ValidationError
from app.models import User, WritingProfile
from app.schemas.profile import WritingProfileUpdate


def get_profile(db: Session, *, user_id) -> WritingProfile | None:
    """读取用户画像（一对一）。无记录返回 None。"""
    return db.scalar(
        select(WritingProfile).where(WritingProfile.user_id == user_id)
    )


def upsert_profile(
    db: Session, *, user_id, data: WritingProfileUpdate
) -> WritingProfile:
    """新建或更新画像（upsert，幂等）。

    - 无记录：create，写入 data 里非 None 的字段。
    - 有记录：仅更新 data 里非 None 的字段（部分更新语义，留空=不改）。
    proficiency 校验在 pydantic schema 层完成（field_validator），非法值请求即 422。
    """
    existing = get_profile(db, user_id=user_id)
    if existing is None:
        profile = WritingProfile(
            user_id=user_id,
            profession=data.profession,
            tech_domain=data.tech_domain,
            proficiency=data.proficiency,
            writing_style=data.writing_style,
            terminology=data.terminology,
        )
        db.add(profile)
    else:
        if data.profession is not None:
            existing.profession = data.profession
        if data.tech_domain is not None:
            existing.tech_domain = data.tech_domain
        if data.proficiency is not None:
            existing.proficiency = data.proficiency
        if data.writing_style is not None:
            existing.writing_style = data.writing_style
        if data.terminology is not None:
            existing.terminology = data.terminology
        profile = existing

    db.commit()
    db.refresh(profile)
    return profile
