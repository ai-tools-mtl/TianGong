from pydantic import BaseModel


class SkillOut(BaseModel):
    """技能定义 + 项目覆盖状态。"""
    skill_key: str
    name: str
    description: str
    enabled: bool
    config: dict | None = None
    is_builtin: bool
    is_overridden: bool


class SkillUpdate(BaseModel):
    enabled: bool
    config: dict | None = None
