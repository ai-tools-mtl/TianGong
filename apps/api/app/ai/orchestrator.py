"""AI 编排：引导对话、生成草稿、段落重写。"""

from collections.abc import AsyncIterator, Iterator

from langchain_core.messages import HumanMessage

from app.ai.context_assembler import assemble_messages, get_project_summaries
from app.ai.llm_client import astream_llm, stream_llm
from app.ai.section_prompts import get_section_prompt
from app.models import Message, Section
from app.services.llm_config_service import ResolvedLLMConfig


def stream_chat(
    db, section: Section, history: list[Message], user_input: str,
    *, llm_config: ResolvedLLMConfig,
) -> Iterator[str]:
    """引导对话：流式回复用户问题。"""
    summaries = get_project_summaries(db, section.project_id)
    knowledge = _retrieve_knowledge(db, section, user_input)
    messages = assemble_messages(section, history, user_input, summaries, knowledge)
    yield from stream_llm(messages, llm_config=llm_config)


def stream_generate(
    db, section: Section, history: list[Message],
    *, llm_config: ResolvedLLMConfig,
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
    yield from stream_llm(messages, llm_config=llm_config)


def _retrieve_knowledge(db, section: Section, query: str) -> list[dict] | None:
    """检索用户知识库（RAG）。旧 skill 开关已删除，Task 10 改造为 @tool。临时返回 None。"""
    return None


def stream_rewrite(
    section: Section, selected_text: str, instruction: str,
    *, llm_config: ResolvedLLMConfig,
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
    yield from stream_llm(messages, llm_config=llm_config)


def _section_owner(db, section: Section):
    """取 section 所属项目的 user_id（用于 skill 可见性）。

    build_agent 需要 user_id 来限定 personal skill 可见范围 + RAG 检索范围。
    """
    from sqlalchemy import select

    from app.models import Project

    project = db.scalar(select(Project).where(Project.id == section.project_id))
    return project.user_id if project else None


async def astream_chat(
    db, section: Section, history: list[Message], user_input: str,
    *, llm_config: ResolvedLLMConfig, usage_sink: dict | None = None,
) -> AsyncIterator[tuple[str, dict | str]]:
    """异步引导对话：委托 deepagents agent loop（路线 B）。

    yield (kind, payload) 元组（Task 23：agent loop 透明化）：
      - ("token", str)：文本 token
      - ("tool_call", {"name", "args"})：agent 发起工具调用
      - ("tool_result", {"name", "result"})：工具返回

    agent.astream_events 暴露 token + tool_call/tool_result 事件，本函数
    全部透传给 SSE 层。

    注意：usage_sink 在 agent loop 路径下**不会被填充**——token 用量
    需从 agent 的最终 message 的 usage_metadata 提取（agent loop 多步调用，
    简单累加 usage_sink 较复杂），Task 13 暂留空。旧 astream_llm 路径
    （astream_rewrite 仍在用）仍正确填充 usage_sink。
    """
    from app.ai.agent import build_agent

    agent = build_agent(db, llm_config=llm_config, user_id=_section_owner(db, section))
    async for event in agent.astream_events(
        {"messages": [{"role": "user", "content": user_input}]},
        version="v2",
    ):
        evt = event["event"]
        if evt == "on_chat_model_stream":
            chunk = event["data"].get("chunk")
            if chunk and chunk.content:
                yield ("token", chunk.content)
        elif evt == "on_tool_start":
            yield ("tool_call", {
                "name": event.get("name", ""),
                "args": event.get("data", {}).get("input", {}),
            })
        elif evt == "on_tool_end":
            result = event.get("data", {}).get("output")
            # result 可能是各种类型（str / ToolMessage / dict），统一转 str 截断
            result_str = str(result)[:500] if result is not None else ""
            yield ("tool_result", {
                "name": event.get("name", ""),
                "result": result_str,
            })


async def astream_generate(
    db, section: Section, history: list[Message],
    *, llm_config: ResolvedLLMConfig, usage_sink: dict | None = None,
) -> AsyncIterator[tuple[str, dict | str]]:
    """异步生成草稿：委托 deepagents agent loop（路线 B）。

    yield (kind, payload) 元组（Task 23：agent loop 透明化）：
      - ("token", str)：文本 token
      - ("tool_call", {"name", "args"})：agent 发起工具调用
      - ("tool_result", {"name", "result"})：工具返回

    agent.astream_events 暴露 token + tool_call/tool_result 事件，本函数
    全部透传给 SSE 层。

    注意：usage_sink 在 agent loop 路径下**不会被填充**——token 用量
    需从 agent 的最终 message 的 usage_metadata 提取（agent loop 多步调用，
    简单累加 usage_sink 较复杂），Task 13 暂留空。旧 astream_llm 路径
    （astream_rewrite 仍在用）仍正确填充 usage_sink。
    """
    from app.ai.agent import build_agent

    agent = build_agent(db, llm_config=llm_config, user_id=_section_owner(db, section))
    sp = get_section_prompt(section.key)
    instruction = (
        f"请根据对话历史，整理生成本章节【{section.title}】的草稿。"
        f"要求：{sp.output_format}。用 Markdown 格式输出。"
    )
    async for event in agent.astream_events(
        {"messages": [{"role": "user", "content": instruction}]},
        version="v2",
    ):
        evt = event["event"]
        if evt == "on_chat_model_stream":
            chunk = event["data"].get("chunk")
            if chunk and chunk.content:
                yield ("token", chunk.content)
        elif evt == "on_tool_start":
            yield ("tool_call", {
                "name": event.get("name", ""),
                "args": event.get("data", {}).get("input", {}),
            })
        elif evt == "on_tool_end":
            result = event.get("data", {}).get("output")
            # result 可能是各种类型（str / ToolMessage / dict），统一转 str 截断
            result_str = str(result)[:500] if result is not None else ""
            yield ("tool_result", {
                "name": event.get("name", ""),
                "result": result_str,
            })


async def astream_rewrite(
    section: Section, selected_text: str, instruction: str,
    *, llm_config: ResolvedLLMConfig, usage_sink: dict | None = None,
) -> AsyncIterator[str]:
    """异步段落重写：基于选中文字 + 指令，流式输出重写结果。

    usage_sink 透传给 astream_llm（断链 C3：捕获 token 用量记入 LLMCallLog）。
    """
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
    async for token in astream_llm(messages, llm_config=llm_config, usage_sink=usage_sink):
        yield token
