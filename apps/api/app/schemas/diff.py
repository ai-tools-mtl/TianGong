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
    # 仅 rewrite-diff 端点填：选区首次出现被 ai_text 替换后的整章 markdown。
    # apply-diff 后端会按 (original, ai_text) 重算 hunks，rewrite 路径必须把
    # 注入后的整章文本原样回传，accepted_hunk_ids 才能与计算时生成的 id 对齐
    # （否则 apply 会拿气泡的 ai_output 当整章 → 重算出完全不同的 hunks → 数据损坏）。
    ai_full: str | None = None


class ApplyDiffRequest(BaseModel):
    """应用 diff 的请求体。"""
    ai_text: str
    accepted_hunk_ids: list[str]  # 被接受的 hunk id 列表
    expected_version: int  # 乐观锁：客户端传读取时的 version


class RewriteDiffRequest(BaseModel):
    """选区重写 diff 的请求体（spec §3.4）。

    selected_text: 用户在编辑器选中的原文
    ai_text: AI 重写后的新文本（来自 streamRewrite SSE 流）
    不含 expected_version：diff 计算只读，乐观锁留给 apply-diff
    """
    selected_text: str
    ai_text: str