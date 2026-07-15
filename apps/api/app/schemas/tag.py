from pydantic import BaseModel, Field


class TagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=50)


class TagUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=50)


class TagMerge(BaseModel):
    """合并：source_id 的所有关联转移到 target_id，然后删除 source_id。"""
    source_id: str
    target_id: str


class TagOut(BaseModel):
    id: str
    name: str
    project_count: int = 0

    model_config = {"from_attributes": True}


class ProjectTagOut(BaseModel):
    """项目视角的标签（贴标签接口返回）。"""
    id: str
    name: str

    model_config = {"from_attributes": True}
