from datetime import datetime

from pydantic import BaseModel


class SectionOut(BaseModel):
    id: str
    project_id: str
    order: int
    key: str
    title: str
    content: dict | None
    summary: str | None
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SectionUpdate(BaseModel):
    content: dict | None = None
    status: str | None = None  # empty/drafting/confirmed
