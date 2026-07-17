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


def _setup_byok_user(client, registered_user, db_session):
    """登录 + 建项目 + 配 BYOK，返回第一个 section（同 test_llm_config_e2e 的脚手架）。"""
    ensure_default_template(db_session)
    user = db_session.scalar(select(User).where(User.email == registered_user["email"]))
    db_session.add(UserLLMConfig(
        user_id=user.id,
        name="test",
        provider="custom",
        base_url="https://byok-fake.example.com",
        api_key_encrypted=encrypt_value("sk-byok-fake-key"),
        model="byok-model",
        embedding_model="byok-embed",
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


def test_chat_logs_token_usage_from_stream(client, registered_user, db_session):
    """chat 端点：流的最后一块 usage_metadata 透传到 LLMCallLog（不再恒为 None）。"""
    sections = _setup_byok_user(client, registered_user, db_session)
    section = sections[0]

    mock_inst = _mock_chat_openai_with_usage(["你好", "世界"], {"input_tokens": 100, "output_tokens": 50})
    with patch("app.ai.llm_client.ChatOpenAI", return_value=mock_inst):
        res = client.post(f"/api/v1/sections/{section.id}/chat", json={"message": "测试"})

    assert res.status_code == 200
    # SSE 流未被破坏
    assert "event: token" in res.text
    assert "event: done" in res.text

    logs = list(db_session.scalars(select(LLMCallLog).where(LLMCallLog.action == "chat")))
    assert len(logs) == 1
    log = logs[0]
    # 断链 C3 核心：token 不再是 None
    assert log.token_prompt == 100, f"token_prompt 应为 100，实际 {log.token_prompt}"
    assert log.token_completion == 50, f"token_completion 应为 50，实际 {log.token_completion}"
    assert log.status == "success"


def test_generate_logs_token_usage_from_stream(client, registered_user, db_session):
    """generate 端点：token 用量同样透传（验证多块 content 的累积路径）。"""
    sections = _setup_byok_user(client, registered_user, db_session)
    section = sections[0]

    mock_inst = _mock_chat_openai_with_usage(
        ["# 草稿", "\n正文"], {"input_tokens": 250, "output_tokens": 180},
    )
    with patch("app.ai.llm_client.ChatOpenAI", return_value=mock_inst):
        res = client.post(f"/api/v1/sections/{section.id}/generate")

    assert res.status_code == 200
    assert "event: done" in res.text

    logs = list(db_session.scalars(select(LLMCallLog).where(LLMCallLog.action == "generate")))
    assert len(logs) == 1
    log = logs[0]
    assert log.token_prompt == 250
    assert log.token_completion == 180


def test_rewrite_logs_token_usage_from_stream(client, registered_user, db_session):
    """rewrite 端点：token 用量透传。"""
    sections = _setup_byok_user(client, registered_user, db_session)
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
    sections = _setup_byok_user(client, registered_user, db_session)
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
    """provider 未回传 usage_metadata（所有块 usage 均为 None）：token 字段落 None，不报错。

    回归保护：stream_usage 不是所有 provider 都支持；缺 usage 时降级为 None，
    端点与 stats 都不能崩。
    """
    sections = _setup_byok_user(client, registered_user, db_session)
    section = sections[0]

    mock_inst = MagicMock()

    async def fake_astream_no_usage(messages):
        chunk = MagicMock()
        chunk.content = "hello"
        chunk.usage_metadata = None
        yield chunk

    mock_inst.astream = fake_astream_no_usage
    with patch("app.ai.llm_client.ChatOpenAI", return_value=mock_inst):
        res = client.post(f"/api/v1/sections/{section.id}/chat", json={"message": "测试"})

    assert res.status_code == 200
    assert "event: done" in res.text

    logs = list(db_session.scalars(select(LLMCallLog).where(LLMCallLog.action == "chat")))
    assert len(logs) == 1
    log = logs[0]
    assert log.token_prompt is None
    assert log.token_completion is None
    assert log.status == "success"
