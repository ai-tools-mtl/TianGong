from datetime import datetime

from pydantic import BaseModel


class TemplateOut(BaseModel):
    id: str
    name: str
    source_filename: str | None
    structure: list[dict]
    styles: dict | None
    numbering: dict | None
    is_default: bool
    is_system: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class TemplateSummary(BaseModel):
    """列表用的精简版（不含 structure 细节）。"""
    id: str
    name: str
    is_default: bool
    is_system: bool
    section_count: int

    model_config = {"from_attributes": True}


class ParseJobOut(BaseModel):
    """解析任务状态查询。"""
    id: str
    status: str
    template_id: str | None = None
    error_message: str | None = None

    model_config = {"from_attributes": True}
