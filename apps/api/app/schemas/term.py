"""项目术语表 Pydantic schemas（T2 spec §3.3.2）。"""
import uuid

from pydantic import BaseModel, ConfigDict, Field


class TermCreate(BaseModel):
    term: str = Field(min_length=1, max_length=100)
    definition: str | None = None
    variants: list[str] = Field(default_factory=list)
    source: str = "manual"  # manual | ai（勾选入库时前端传 ai）


class TermUpdate(BaseModel):
    """部分更新：仅更新传入字段（照抄 profile_service.upsert_profile 语义）。"""
    term: str | None = Field(default=None, min_length=1, max_length=100)
    definition: str | None = None
    variants: list[str] | None = None
    enabled: bool | None = None


class TermOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    term: str
    definition: str | None
    variants: list[str]
    enabled: bool
    source: str
    created_at: str
    updated_at: str


class CheckRequest(BaseModel):
    """一致性检查请求。llm_verify：可选 LLM 复核规则路误报（默认关，多一次 lite 调用）。"""
    llm_verify: bool = False
