"""diff 审查相关 schema（设计 plan15 / spec §4）。"""

from pydantic import BaseModel


class HunkOut(BaseModel):
    """单个 hunk 的响应结构。

    inline: replace 时的字符级 diff [[op, text], ...]（op: -1/0/1），其余为 null
    text: insert 时的整段新文本，其余为 null
    original_para: replace/delete 时的原段，其余为 null
    modified_para: replace 时的修改后段，其余为 null
    """
    id: str
    type: str  # replace | insert | delete
    inline: list[list] | None = None
    text: str | None = None
    original_para: str | None = None
    modified_para: str | None = None

    model_config = {"from_attributes": True}


class DiffRequest(BaseModel):
    """计算 diff 的请求体。"""
    ai_text: str


class DiffResponse(BaseModel):
    """diff 计算响应。"""
    hunks: list[HunkOut]


class ApplyDiffRequest(BaseModel):
    """应用 diff 的请求体。"""
    ai_text: str
    accepted_hunk_ids: list[str]  # 被接受的 hunk id 列表
    expected_version: int  # 乐观锁：客户端传读取时的 version