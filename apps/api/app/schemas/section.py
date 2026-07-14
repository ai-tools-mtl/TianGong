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
    version: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SectionUpdate(BaseModel):
    content: dict | None = None
    status: str | None = None  # empty/drafting/confirmed
    expected_version: int | None = None  # 乐观锁：客户端传读取时的版本号
