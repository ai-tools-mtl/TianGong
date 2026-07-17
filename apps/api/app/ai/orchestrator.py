"""AI 编排：引导对话、生成草稿、段落重写。"""

from collections.abc import AsyncIterator, Iterator

from langchain_core.messages import HumanMessage

from app.ai.context_assembler import assemble_messages, get_project_summaries
from app.ai.llm_client import astream_llm, stream_llm
from app.ai.section_prompts import get_section_prompt
from app.models import Message, Section


def _llm_kwargs(llm_config) -> dict:
    """把 ResolvedLLMConfig 转成 get_llm 的关键字参数；None 返回空 dict。"""
    if llm_config is None:
        return {}
    return {
        "base_url": llm_config.base_url or None,
        "api_key": llm_config.api_key or None,
        "model": llm_config.model or None,
    }


def stream_chat(
    db, section: Section, history: list[Message], user_input: str,
    *, llm_config=None,
) -> Iterator[str]:
    """引导对话：流式回复用户问题。"""
    summaries = get_project_summaries(db, section.project_id)
    knowledge = _retrieve_knowledge(db, section, user_input)
    messages = assemble_messages(section, history, user_input, summaries, knowledge)
    yield from stream_llm(messages, **_llm_kwargs(llm_config))


def stream_generate(
    db, section: Section, history: list[Message], *, llm_config=None,
) -> Iterator[str]:
    """生成草稿：基于对话历史生成本章草稿（Markdown 流式）。"""
    summaries = get_project_summaries(db, section.project_id)
    knowledge = _retrieve_knowledge(db, section, section.title)
    sp = get_section_prompt(section.key)
    messages = assemble_messages(
        section, history, project_summaries=summaries, knowledge_context=knowledge
    )
    instruction = (
        f"请根据以上对话内容，整理生成本章节【{section.title}】的草稿。"
        f"要求：{sp.output_format}。用 Markdown 格式输出。"
    )
    messages.append(HumanMessage(content=instruction))
    yield from stream_llm(messages, **_llm_kwargs(llm_config))


def _retrieve_knowledge(db, section: Section, query: str) -> list[dict] | None:
    """检索用户知识库（RAG）。禁用技能短路；异常降级为空。"""
    try:
        from sqlalchemy import select

        from app.models import Project
        from app.rag.retriever import retrieve
        from app.services.skill_service import is_skill_enabled

        project = db.scalar(select(Project).where(Project.id == section.project_id))
        if project is None:
            return None
        # 设计 7.4：rag_search 禁用则不检索
        if not is_skill_enabled(db, project_id=project.id, skill_key="rag_search"):
            return None
        results = retrieve(db, user_id=project.user_id, query=query)
        return [
            {
                "content": r.content,
                "section_key": r.source_section_key,
                "project_title": r.project_title,
            }
            for r in results
        ]
    except Exception:
        return None


def stream_rewrite(
    section: Section, selected_text: str, instruction: str,
    *, llm_config=None,
) -> Iterator[str]:
    """段落重写：基于选中文字 + 指令，流式输出重写结果。"""
    from langchain_core.messages import SystemMessage

    sp = get_section_prompt(section.key)
    system = (
        f"你是专利交底书撰写助手。当前章节：【{section.title}】（{sp.goal}）。"
        f"用户选中了一段文字，请按指令重写。保持 Markdown 格式。"
    )
    messages = [
        SystemMessage(content=system),
        HumanMessage(content=f"原文：\n{selected_text}\n\n指令：{instruction}"),
    ]
    yield from stream_llm(messages, **_llm_kwargs(llm_config))


async def astream_chat(
    db, section: Section, history: list[Message], user_input: str,
    *, llm_config=None,
) -> AsyncIterator[str]:
    """异步引导对话：流式回复用户问题（供 SSE 端点用）。"""
    summaries = get_project_summaries(db, section.project_id)
    knowledge = _retrieve_knowledge(db, section, user_input)
    messages = assemble_messages(section, history, user_input, summaries, knowledge)
    async for token in astream_llm(messages, **_llm_kwargs(llm_config)):
        yield token


async def astream_generate(
    db, section: Section, history: list[Message], *, llm_config=None,
) -> AsyncIterator[str]:
    """异步生成草稿：基于对话历史生成本章草稿（Markdown 流式）。"""
    summaries = get_project_summaries(db, section.project_id)
    knowledge = _retrieve_knowledge(db, section, section.title)
    sp = get_section_prompt(section.key)
    messages = assemble_messages(
        section, history, project_summaries=summaries, knowledge_context=knowledge
    )
    instruction = (
        f"请根据以上对话内容，整理生成本章节【{section.title}】的草稿。"
        f"要求：{sp.output_format}。用 Markdown 格式输出。"
    )
    messages.append(HumanMessage(content=instruction))
    async for token in astream_llm(messages, **_llm_kwargs(llm_config)):
        yield token


async def astream_rewrite(
    section: Section, selected_text: str, instruction: str,
    *, llm_config=None,
) -> AsyncIterator[str]:
    """异步段落重写：基于选中文字 + 指令，流式输出重写结果。"""
    from langchain_core.messages import SystemMessage

    sp = get_section_prompt(section.key)
    system = (
        f"你是专利交底书撰写助手。当前章节：【{section.title}】（{sp.goal}）。"
        f"用户选中了一段文字，请按指令重写。保持 Markdown 格式。"
    )
    messages = [
        SystemMessage(content=system),
        HumanMessage(content=f"原文：\n{selected_text}\n\n指令：{instruction}"),
    ]
    async for token in astream_llm(messages, **_llm_kwargs(llm_config)):
        yield token
