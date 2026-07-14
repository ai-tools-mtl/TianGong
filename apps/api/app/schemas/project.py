from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    template_id: str | None = None
    metadata: dict[str, Any] | None = None


class ProjectUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    metadata: dict[str, Any] | None = None


class ProjectOut(BaseModel):
    id: str
    title: str
    stage: str
    status: str
    progress_pct: int
    metadata: dict[str, Any] | None = None
    archived_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
