# apps/api/app/schemas/skill.py
"""Skill schemas（spec 合规版）。

旧 SkillOut/SkillUpdate 已随 agent_skills 表删除（Task 3）。
本文件为新两档可见性体系重建。
"""
from pydantic import BaseModel, Field, field_validator
import re

# spec name 规则：[a-z0-9-]，1-64，不首尾/连续连字符
_NAME_RE = re.compile(r"^(?!-)[a-z0-9-]{1,64}(?<!-)$")


class SkillBase(BaseModel):
    name: str = Field(..., max_length=64, description="spec name, [a-z0-9-]")
    description: str = Field(..., max_length=1024, description="触发条件，单行")
    skill_md: str = Field(..., description="SKILL.md 正文（Markdown，不含 frontmatter）")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not _NAME_RE.match(v):
            raise ValueError("name 必须为 [a-z0-9-]，1-64 字符，不首尾/连续连字符")
        if "--" in v:
            raise ValueError("name 不能有连续连字符")
        return v

    @field_validator("description")
    @classmethod
    def single_line(cls, v: str) -> str:
        if "\n" in v.strip():
            raise ValueError("description 必须单行（spec 触发条件约束）")
        return v.strip()


class SkillCreate(SkillBase):
    """创建 skill。scope 由路由决定（admin=global, user=personal），不在 body。"""


class SkillUpdate(BaseModel):
    """更新 skill（全 Optional，部分更新）。name 不可改（spec: name=目录名）。"""
    description: str | None = Field(None, max_length=1024)
    skill_md: str | None = None
    status: str | None = Field(None, pattern="^(draft|active)$")

    @field_validator("description")
    @classmethod
    def single_line(cls, v):
        if v and "\n" in v.strip():
            raise ValueError("description 必须单行")
        return v.strip() if v else v


class SkillOut(BaseModel):
    """skill 输出（列表 + 详情共用）。"""
    model_config = {"from_attributes": True}

    id: str
    name: str
    description: str
    scope: str
    owner_id: str | None = None
    status: str
    minio_prefix: str
    is_builtin: bool = False
    created_at: str
    updated_at: str


class SkillDetail(SkillOut):
    """详情：含 SKILL.md 正文。"""
    skill_md: str
