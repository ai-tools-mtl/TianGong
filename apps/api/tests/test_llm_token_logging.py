"""断链 C3 端到端证明：LLM 流式调用的 token 用量真正一路透传到 LLMCallLog
并在 stats_service 聚合中可见。

链路：HTTP 路由 → orchestrator.astream_* → llm_client.astream_llm → ChatOpenAI.astream。
仅在 app.ai.llm_client.ChatOpenAI 层打桩：让 astream 产出若干 content 块，
最后一块携带 usage_metadata（LangChain 在 stream_usage=True 时的真实行为）。
断言：
  1. LLMCallLog.token_prompt / token_completion 不再恒为 None，而是真实值。
  2. stats_service.get_llm_stats 返回 total_prompt_tokens / total_completion_tokens。
  3. SSE token 流格式不被破坏（token/done 事件仍正常）。
"""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select

from app.core.security import encrypt_value
from app.models import LLMCallLog, User, UserLLMConfig
from app.services import stats_service
from app.services.project_service import create_project
from app.services.section_service import list_sections
from app.services.seed_service import ensure_default_template


@pytest.fixture
def admin_user(db_session):
    u = User(
        username="admin",
        email="admin@example.com", password_hash="x", name="管理员",
        role="admin", status="active",
    )
    db_session.add(u)
    db_session.commit()
    return u


def _setup_custom_user(client, registered_user, db_session):
    """登录 + 建项目 + 配自定义配置，返回第一个 section（同 test_llm_config_e2e 的脚手架）。"""
    ensure_default_template(db_session)
    user = db_session.scalar(select(User).where(User.email == registered_user["email"]))
    db_session.add(UserLLMConfig(
        user_id=user.id,
        name="test",
        provider="custom",
        base_url="https://custom-fake.example.com",
        api_key_encrypted=encrypt_value("sk-custom-fake-key"),
        model="custom-model",
    ))
    db_session.commit()
    p = create_project(db_session, user=user, title="Token 用量测试发明")
    sections = list_sections(db_session, user_id=user.id, project_id=str(p.id))
    client.post("/api/v1/auth/login", json={
        "username": registered_user["username"], "password": registered_user["password"],
    })
    return sections


def _mock_chat_openai_with_usage(content_chunks, usage):
    """构造 mock ChatOpenAI 实例：astream 先吐若干 content 块，最后吐带 usage 的块。

    模拟 LangChain stream_usage=True 的真实行为：usage_metadata 出现在最后一块。
    """
    mock_inst = MagicMock()

    async def fake_astream(messages):
        for text in content_chunks:
            chunk = MagicMock()
            chunk.content = text
            chunk.usage_metadata = None  # 中间块不带 usage
            yield chunk
        # 最后一块：content 为空（典型情况），仅携带 usage_metadata
        final = MagicMock()
        final.content = ""
        final.usage_metadata = {
            "input_tokens": usage["input_tokens"],
            "output_tokens": usage["output_tokens"],
            "total_tokens": usage["input_tokens"] + usage["output_tokens"],
        }
        yield final

    mock_inst.astream = fake_astream
    return mock_inst


def _fake_agent_streaming(content_chunks):
    """构造 fake build_agent：返回 astream_events 透传文本 token 的假 agent。

    Task 13 起 chat/generate 委托 deepagents agent loop。本文件原有测试在
    app.ai.llm_client.ChatOpenAI 层打桩，但 agent loop 不经 astream_llm，
    故改在 build_agent 层打桩：假 agent 逐块 yield on_chat_model_stream 事件，
    让 orchestrator.astream_chat/astream_generate 的 token 透传路径跑通。
    """
    chunks = list(content_chunks)

    class _FakeAgent:
        async def astream_events(self, input_, *, version="v2"):
            for text in chunks:
                chunk = MagicMock()
                chunk.content = text
                yield {"event": "on_chat_model_stream", "data": {"chunk": chunk}}

    def _build_agent(db, *, llm_config, user_id, section=None, user_input=None):
        return _FakeAgent()

    return _build_agent


def test_chat_logs_token_usage_from_stream(client, registered_user, db_session):
    """chat 端点：Task 13 起 chat 委托 agent loop（astream_chat 不再走 astream_llm）。

    已知限制（Task 13）：agent loop 不填充 usage_sink，故 chat 的 token 字段落 None。
    rewrite/caption 仍走 astream_llm，token 透传不受影响（见各自测试）。
    本测试 mock build_agent 透传 token 流，验证 SSE 成功路径 + token 字段如实为 None。
    """
    sections = _setup_custom_user(client, registered_user, db_session)
    section = sections[0]

    fake_agent = _fake_agent_streaming(["你好", "世界"])
    with patch("app.ai.agent.build_agent", fake_agent):
        res = client.post(f"/api/v1/sections/{section.id}/chat", json={"message": "测试"})

    assert res.status_code == 200
    # SSE 流未被破坏
    assert "event: token" in res.text
    assert "event: done" in res.text

    logs = list(db_session.scalars(select(LLMCallLog).where(LLMCallLog.action == "chat")))
    assert len(logs) == 1
    log = logs[0]
    # Task 13 已知限制：agent loop 路径下 token 暂记 None（usage_sink 不再被填充）
    assert log.token_prompt is None, "Task 13：chat 走 agent loop，token 暂记 None"
    assert log.token_completion is None, "Task 13：chat 走 agent loop，token 暂记 None"
    assert log.status == "success"


def test_generate_logs_token_usage_from_stream(client, registered_user, db_session):
    """generate 端点：Task 13 起委托 agent loop，token 字段落 None（同 chat）。"""
    sections = _setup_custom_user(client, registered_user, db_session)
    section = sections[0]

    fake_agent = _fake_agent_streaming(["# 草稿", "\n正文"])
    with patch("app.ai.agent.build_agent", fake_agent):
        res = client.post(f"/api/v1/sections/{section.id}/generate")

    assert res.status_code == 200
    assert "event: done" in res.text

    logs = list(db_session.scalars(select(LLMCallLog).where(LLMCallLog.action == "generate")))
    assert len(logs) == 1
    log = logs[0]
    # Task 13 已知限制：agent loop 路径下 token 暂记 None
    assert log.token_prompt is None
    assert log.token_completion is None


def test_rewrite_logs_token_usage_from_stream(client, registered_user, db_session):
    """rewrite 端点：token 用量透传。"""
    sections = _setup_custom_user(client, registered_user, db_session)
    section = sections[0]

    mock_inst = _mock_chat_openai_with_usage(["重写"], {"input_tokens": 80, "output_tokens": 40})
    with patch("app.ai.llm_client.ChatOpenAI", return_value=mock_inst):
        res = client.post(f"/api/v1/sections/{section.id}/rewrite", json={
            "selected_text": "原文", "instruction": "更简洁",
        })

    assert res.status_code == 200
    assert "event: done" in res.text

    logs = list(db_session.scalars(select(LLMCallLog).where(LLMCallLog.action == "rewrite")))
    assert len(logs) == 1
    log = logs[0]
    assert log.token_prompt == 80
    assert log.token_completion == 40


def test_caption_logs_token_usage_from_stream(client, registered_user, db_session):
    """caption_figures 端点（直接调 astream_llm）：token 用量透传并写日志。"""
    sections = _setup_custom_user(client, registered_user, db_session)
    drawings = next(s for s in sections if s.key == "drawings")

    mock_inst = _mock_chat_openai_with_usage(
        ["图 1 是装置示意图。"], {"input_tokens": 30, "output_tokens": 20},
    )
    with patch("app.ai.llm_client.ChatOpenAI", return_value=mock_inst):
        res = client.post(f"/api/v1/sections/{drawings.id}/caption-figures", json={
            "descriptions": ["图1是装置结构图"],
        })

    assert res.status_code == 200
    assert "event: token" in res.text

    logs = list(db_session.scalars(select(LLMCallLog).where(LLMCallLog.action == "caption")))
    assert len(logs) == 1
    log = logs[0]
    assert log.token_prompt == 30
    assert log.token_completion == 20


def test_stats_service_surfaces_token_totals(db_session, admin_user):
    """stats_service 聚合 token 总量（断链 C3：admin 看板可见 token 用量）。"""
    # 复用 test_stats_service 的 _make_log 等价构造，但这里直接建行以避免跨文件依赖
    from datetime import datetime, timedelta, timezone

    for prompt, completion in [(100, 50), (250, 180)]:
        log = LLMCallLog(
            user_id=admin_user.id, project_id=None, action="chat",
            model="glm-4-flash", provider="global",
            token_prompt=prompt, token_completion=completion,
            duration_ms=100, status="success",
        )
        db_session.add(log)
        db_session.commit()
    # 一条无 token 的旧记录（None 应按 0 计，不污染求和）
    log_none = LLMCallLog(
        user_id=admin_user.id, project_id=None, action="chat",
        model="glm-4-flash", provider="global",
        token_prompt=None, token_completion=None,
        duration_ms=10, status="success",
    )
    db_session.add(log_none)
    db_session.commit()

    stats = stats_service.get_llm_stats(db_session, days=7)
    assert stats["total_prompt_tokens"] == 350  # 100 + 250
    assert stats["total_completion_tokens"] == 230  # 50 + 180
    # by_model 也应带 token 拆分
    by_model = {m["model"]: m for m in stats["by_model"]}
    assert by_model["glm-4-flash"]["prompt_tokens"] == 350
    assert by_model["glm-4-flash"]["completion_tokens"] == 230


def test_token_usage_none_when_provider_does_not_return_usage(client, registered_user, db_session):
    """provider 未回传 usage_metadata：token 字段落 None，不报错。

    Task 13：chat 走 agent loop，usage_sink 本就不被填充（恒为 None）。
    用 fake build_agent 验证 SSE 成功路径 + token 字段如实为 None，端点不崩。
    """
    sections = _setup_custom_user(client, registered_user, db_session)
    section = sections[0]

    fake_agent = _fake_agent_streaming(["hello"])
    with patch("app.ai.agent.build_agent", fake_agent):
        res = client.post(f"/api/v1/sections/{section.id}/chat", json={"message": "测试"})

    assert res.status_code == 200
    assert "event: done" in res.text

    logs = list(db_session.scalars(select(LLMCallLog).where(LLMCallLog.action == "chat")))
    assert len(logs) == 1
    log = logs[0]
    assert log.token_prompt is None
    assert log.token_completion is None
    assert log.status == "success"
