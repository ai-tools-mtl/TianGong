"""AI 编排：引导对话、生成草稿、段落重写。"""

from collections.abc import Iterator

from langchain_core.messages import HumanMessage

from app.ai.context_assembler import assemble_messages, get_project_summaries
from app.ai.llm_client import stream_llm
from app.ai.section_prompts import get_section_prompt
from app.models import Message, Section


def stream_chat(
    db, section: Section, history: list[Message], user_input: str
) -> Iterator[str]:
    """引导对话：流式回复用户问题。"""
    summaries = get_project_summaries(db, section.project_id)
    messages = assemble_messages(section, history, user_input, summaries)
    yield from stream_llm(messages)


def stream_generate(
    db, section: Section, history: list[Message]
) -> Iterator[str]:
    """生成草稿：基于对话历史生成本章草稿（Markdown 流式）。"""
    summaries = get_project_summaries(db, section.project_id)
    sp = get_section_prompt(section.key)
    messages = assemble_messages(section, history, project_summaries=summaries)
    instruction = (
        f"请根据以上对话内容，整理生成本章节【{section.title}】的草稿。"
        f"要求：{sp.output_format}。用 Markdown 格式输出。"
    )
    messages.append(HumanMessage(content=instruction))
    yield from stream_llm(messages)


def stream_rewrite(
    section: Section, selected_text: str, instruction: str
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
    yield from stream_llm(messages)
