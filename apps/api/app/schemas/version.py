from datetime import datetime

from pydantic import BaseModel


class VersionOut(BaseModel):
    id: str
    section_id: str
    content: dict | None
    summary: str | None
    created_by: str
    note: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class VersionCreate(BaseModel):
    note: str | None = None
