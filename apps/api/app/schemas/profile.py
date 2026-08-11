"""写作画像 schema（/settings/profile CRUD）。"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.models.writing_profile import (
    PROFICIENCY_EXPERT,
    PROFICIENCY_INTERMEDIATE,
    PROFICIENCY_NOVICE,
)

_PROFICIENCY_VALID = {PROFICIENCY_NOVICE, PROFICIENCY_INTERMEDIATE, PROFICIENCY_EXPERT}


class WritingProfileOut(BaseModel):
    """画像读取响应（全量字段，未填的为 None）。无记录时各字段全 None。"""
    model_config = {"from_attributes": True}

    profession: Optional[str] = None
    tech_domain: Optional[str] = None
    proficiency: Optional[str] = None
    writing_style: Optional[str] = None
    terminology: Optional[str] = None
    updated_at: Optional[datetime] = None


class WritingProfileUpdate(BaseModel):
    """画像更新请求（全字段可选，仅提供才更新）。

    proficiency 限定三档；其余字段自由文本。
    空请求（全 None）允许——表示不改动，保持 upsert 幂等。
    """
    profession: Optional[str] = Field(None, max_length=100)
    tech_domain: Optional[str] = Field(None, max_length=100)
    proficiency: Optional[str] = None
    writing_style: Optional[str] = None
    terminology: Optional[str] = None

    @field_validator("proficiency")
    @classmethod
    def _check_proficiency(cls, v: Optional[str]) -> Optional[str]:
        """校验 proficiency 取值合法性（None 允许=不改）。"""
        if v is not None and v not in _PROFICIENCY_VALID:
            raise ValueError(f"proficiency 取值必须是 {sorted(_PROFICIENCY_VALID)} 之一")
        return v

