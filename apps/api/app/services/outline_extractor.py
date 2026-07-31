"""大纲提取：init 助手「右侧文档实时预览」的核心服务。

每轮对话后，从对话历史用轻量 LLM 提取 8 章结构化要点（Markdown），
写回 conversation.draft_outline 供前端实时渲染。草稿态——不提前建项目，
按扳机落地后才转为正式 section。

范式严格对齐 conversation_service.summarize_conversation_title（B 类轻量任务）：
- resolve_lite_config 优先 admin 配的轻量模型（典型 GLM-4.7-Flash），未配回退用户 chat 配置
- 同步 get_llm().invoke()（非流式），失败降级返回空 dict
- 不抛异常：提取失败只是预览不更新，不影响对话主流程
"""
import json
import re

from sqlalchemy.orm import Session

from app.ai.llm_client import get_llm
from app.core.text_utils import sanitize_text_for_pg
from app.models import Message
from app.services.seed_service import DEFAULT_STRUCTURE

# 8 章 key → title 的映射（与 seed_service.DEFAULT_STRUCTURE 一致，单一数据源）
_OUTLINE_KEYS = [(s["key"], s["title"]) for s in DEFAULT_STRUCTURE]


def _build_dialog_text(messages: list[Message]) -> str:
    """把对话历史拼成「用户/AI」交替文本（裁剪超长，省 token）。"""
    lines = []
    for m in messages:
        role = "用户" if m.role == "user" else "AI"
        # 单条上限 800 字（预览提取不需要完整长文，关键信息在前段）
        lines.append(f"{role}：{m.content[:800]}")
    return "\n\n".join(lines)


def _build_prompt(dialog_text: str) -> str:
    """构造提取 prompt：要求 LLM 按 8 章 key 输出 JSON。"""
    keys_desc = "\n".join(f'- "{k}"：{t}' for k, t in _OUTLINE_KEYS)
    keys_list = ", ".join(f'"{k}"' for k, _ in _OUTLINE_KEYS)
    return (
        "下面是一段专利交底书初始化对话。请从中提取信息，按交底书的 8 个章节整理成结构化要点。\n\n"
        "章节含义：\n"
        f"{keys_desc}\n\n"
        "要求：\n"
        "1. 只输出一个 JSON 对象，key 是章节代号，value 是该章的 Markdown 要点（字符串）\n"
        "2. 信息不足的章节，value 填空字符串 \"\"\n"
        "3. 不要编造未提及的技术细节，只整理对话中已有的信息\n"
        "4. 每章内容简明（一般不超过 150 字），用要点或短段落\n"
        "5. 不要输出 JSON 以外的任何文字（不要 ```json 代码块标记、不要解释）\n\n"
        f"必须包含这些 key：{keys_list}\n\n"
        f"对话内容：\n{dialog_text}\n\n"
        "JSON："
    )


def _parse_outline_json(raw: str) -> dict:
    """容错解析 LLM 输出的 JSON。

    LLM 可能包 ```json 代码块或带前后缀说明，尝试提取首个 {...} 再 json.loads。
    返回 {key: {"title": str, "content": str}} 结构（清洗后）。
    """
    text = raw.strip()
    # 去除可能的 ```json ... ``` 代码块包裹
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    else:
        # 裸文本里抓首个 {...}
        brace = re.search(r"\{.*\}", text, re.DOTALL)
        if brace:
            text = brace.group(0)

    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return {}

    if not isinstance(data, dict):
        return {}

    result = {}
    for key, title in _OUTLINE_KEYS:
        val = data.get(key, "")
        if isinstance(val, str):
            content = sanitize_text_for_pg(val).strip()
        else:
            content = ""
        result[key] = {"title": title, "content": content}
    return result


def extract_outline(db: Session, messages: list[Message], user_id) -> dict:
    """从对话历史提取 8 章草稿大纲。

    返回 {key: {"title": str, "content": str}}；提取失败/无配置/无对话内容时返回空 dict。
    幂等：每轮基于全量历史重算，不做增量合并（避免有损往返）。
    """
    # 无对话内容直接返回空（首轮之前不调 LLM）
    if not messages:
        return {}

    try:
        from app.services.llm_config_service import resolve_lite_config

        llm_config = resolve_lite_config(db, user_id=user_id)
    except Exception:
        return {}
    if llm_config is None:
        return {}

    try:
        from langchain_core.messages import HumanMessage

        llm = get_llm(llm_config)
        dialog_text = _build_dialog_text(messages)
        resp = llm.invoke([HumanMessage(content=_build_prompt(dialog_text))])
        return _parse_outline_json(resp.content if hasattr(resp, "content") else str(resp))
    except Exception:
        return {}
