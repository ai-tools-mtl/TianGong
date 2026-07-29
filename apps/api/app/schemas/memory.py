"""用户长期记忆 schemas。

MemoryOut 不用 field_serializer：Pydantic 先校验后序列化，
UUID→str / None→str 会在校验阶段失败（field_serializer 来不及执行）。
故与 skills.py 的 SkillOut 一致——声明纯 str 字段，
UUID/datetime 的转换交给路由的 _to_out() 显式完成。
"""
from pydantic import BaseModel, Field


class MemoryCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=500)
    source: str = Field("manual", pattern="^(agent|manual)$")


class MemoryUpdate(BaseModel):
    content: str = Field(..., min_length=1, max_length=500)


class MemoryOut(BaseModel):
    """记忆输出。UUID/datetime 由路由 _to_out() 显式转 str（与 skills.py 同策略）。"""
    model_config = {"from_attributes": True}

    id: str
    content: str
    source: str
    created_at: str
    updated_at: str
