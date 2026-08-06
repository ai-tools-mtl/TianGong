# apps/api/tests/test_init_prompt_split.py
"""init 助手 system prompt 拆分一致性测试。

INIT_SYSTEM_PROMPT 已按链路拆为两个常量，此测试守护拆分契约：
- INIT_CHAT_SYSTEM_PROMPT（对话引导，走 agent loop，工具可调用）：含「可用工具」段落
- INIT_GENERATE_SYSTEM_PROMPT（正文生成，走裸 astream_llm，无工具调用入口）：不含「可用工具」，
  改含「系统已自动检索」说明——避免模型等待一个无法调用的工具。

同时验证两者共享 _INIT_COMMON 主体（引导目标/规则/写作规范），仅尾部场景段不同。
"""
import asyncio
from unittest.mock import MagicMock


def test_chat_prompt_advertises_tools():
    """对话版必须向模型说明可用工具（rag_search + save_memory）。"""
    from app.ai.init_orchestrator import INIT_CHAT_SYSTEM_PROMPT

    assert "可用工具" in INIT_CHAT_SYSTEM_PROMPT
    assert "rag_search" in INIT_CHAT_SYSTEM_PROMPT
    assert "save_memory" in INIT_CHAT_SYSTEM_PROMPT


def test_generate_prompt_does_not_advertise_tools():
    """生成版走裸 astream_llm 无工具调用入口，不得出现「可用工具」（否则误导模型）。"""
    from app.ai.init_orchestrator import INIT_GENERATE_SYSTEM_PROMPT

    assert "可用工具" not in INIT_GENERATE_SYSTEM_PROMPT
    # 改用「自动检索/已注入」语义说明 RAG 来源
    assert "自动检索" in INIT_GENERATE_SYSTEM_PROMPT or "已注入" in INIT_GENERATE_SYSTEM_PROMPT


def test_both_prompts_share_common_body():
    """两个 prompt 共享 _INIT_COMMON 主体（引导目标/规则/写作规范一致）。"""
    from app.ai.init_orchestrator import (
        _INIT_COMMON, INIT_CHAT_SYSTEM_PROMPT, INIT_GENERATE_SYSTEM_PROMPT,
    )

    assert INIT_CHAT_SYSTEM_PROMPT.startswith(_INIT_COMMON)
    assert INIT_GENERATE_SYSTEM_PROMPT.startswith(_INIT_COMMON)
    # 核心引导要素都在
    for keyword in ("对话目标", "引导规则", "写作规范", "现有技术及其缺点"):
        assert keyword in _INIT_COMMON


def test_build_section_generate_uses_generate_prompt(monkeypatch, db_session):
    """_build_section_generate_messages 装配的首条消息必须是生成版 prompt（不含「可用工具」）。"""
    from app.ai import init_orchestrator as mod
    from app.ai import context_compactor as cc_mod

    async def _noop(history, current_input, llm_config, *, scene=None):
        snap = MagicMock()
        snap.triggered = False
        snap.to_dict.return_value = {}
        return [], snap

    monkeypatch.setattr(cc_mod, "compress_history", _noop)
    # retrieve 返回空，聚焦 prompt 选择
    from app.rag import retriever as ret_mod
    monkeypatch.setattr(ret_mod, "retrieve", lambda *a, **k: [])

    section = MagicMock()
    section.title = "技术方案"
    section.key = "solution"

    messages = asyncio.run(mod._build_section_generate_messages(
        section, [], llm_config=MagicMock(), outline=None,
        db=db_session, user_id="00000000-0000-0000-0000-000000000000",
    ))

    # 首条是生成版 prompt：不含「可用工具」，含「自动检索/已注入」
    first = messages[0].content
    assert "可用工具" not in first
    assert "自动检索" in first or "已注入" in first
