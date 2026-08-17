"""端到端断链证明：用户配的自定义配置真正驱动 LLM 调用（而非 env）。

这是阶段 0 的核心交付：证明解析出的自定义 chat 配置
（base_url / api_key / model）真正一路传到 ChatOpenAI 构造处，
而不是被 env 兜底覆盖（即「断链」确实修复）。

测试策略：用 TestClient 走真实 HTTP → FastAPI 路由 → orchestrator → llm_client，
仅在 app.ai.llm_client.ChatOpenAI 层打桩，捕获构造参数，断言用的是用户的自定义 key 值。
"""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import encrypt_value, hash_password
from app.models import User, UserLLMConfig
from app.services.project_service import create_project
from app.services.section_service import list_sections
from app.services.seed_service import ensure_default_template


@pytest.fixture(autouse=True)
def _no_env_llm_fallback(monkeypatch):
    """默认锁定 env 兜底不触发（glm_api_key=""）。

    防止 no-config 测试因 OS 环境变量（如开发者本地 export GLM_API_KEY=xxx）
    假失败——pydantic-settings 会读 os.environ，否则 resolve 会返回 env 兜底
    配置而非 None，导致 no_llm_config 错误不再触发。
    本文件内所有「无配置」断言因此稳定；本文件自定义配置测试不受影响（分支①优先）。
    """
    monkeypatch.setattr(get_settings(), "glm_api_key", "")

CUSTOM_BASE_URL = "https://custom-fake.example.com"
CUSTOM_API_KEY = "sk-custom-fake-key-12345"
CUSTOM_MODEL = "custom-model"


def _setup_custom_user(client, registered_user, db_session):
    """登录 + 建项目 + 给当前用户配自定义配置（假 key/url/model）。返回第一个 section。"""
    ensure_default_template(db_session)
    user = db_session.scalar(select(User).where(User.email == registered_user["email"]))
    # 给用户配自定义配置
    db_session.add(UserLLMConfig(
        user_id=user.id,
        name="test",
        provider="custom",
        base_url=CUSTOM_BASE_URL,
        api_key_encrypted=encrypt_value(CUSTOM_API_KEY),
        model=CUSTOM_MODEL,
    ))
    db_session.commit()
    p = create_project(db_session, user=user, title="自定义配置测试发明")
    sections = list_sections(db_session, user_id=user.id, project_id=str(p.id))
    client.post("/api/v1/auth/login", json={
        "username": registered_user["username"], "password": registered_user["password"],
    })
    return sections


def _mock_chat_openai(token_text="hello"):
    """构造 mock 实例（含 async astream / stream / invoke）。

    用法：
        mock_inst, mock_chat = _mock_chat_openai("你好")
        with patch("app.ai.llm_client.ReasoningChatOpenAI", return_value=mock_inst) as mock_chat:
            ...
            _assert_custom_kwargs(mock_chat)  # mock_chat.call_args 捕获构造参数
    """
    mock_inst = MagicMock()

    async def fake_astream(messages):
        chunk = MagicMock()
        chunk.content = token_text
        yield chunk

    mock_inst.astream = fake_astream
    mock_inst.stream = lambda messages: iter([_sync_chunk(token_text)])
    mock_inst.invoke = lambda messages: _sync_chunk(token_text)
    return mock_inst


def _sync_chunk(text):
    chunk = MagicMock()
    chunk.content = text
    return chunk


def _assert_custom_kwargs(mock_chat):
    """断言 ChatOpenAI 被构造时用的是自定义 key 的值。"""
    assert mock_chat.called, "ChatOpenAI 应被实例化"
    _, kwargs = mock_chat.call_args
    assert kwargs["api_key"] == CUSTOM_API_KEY, "LLM 应使用用户的自定义 key，而非 env"
    assert kwargs["base_url"] == CUSTOM_BASE_URL, "LLM 应使用用户的自定义 base_url"
    assert kwargs["model"] == CUSTOM_MODEL, "LLM 应使用用户的自定义 model"


def _assert_custom_llm_config(captured):
    """断言传入 build_agent 的 llm_config 携带自定义配置值（Task 13 chat/generate 路径）。

    rewrite/caption 仍走 astream_llm（patch ChatOpenAI 捕获构造参数，用 _assert_custom_kwargs）；
    Task 13 起 chat/generate 走 agent loop，自定义配置传到 build_agent 的 llm_config 形参，
    故在此断言 captured[0] 的 base_url/api_key/model。
    """
    assert captured, "build_agent 应被调用"
    cfg = captured[0]
    assert cfg.api_key == CUSTOM_API_KEY, "agent loop 应收到用户的自定义 key"
    assert cfg.base_url == CUSTOM_BASE_URL, "agent loop 应收到用户的自定义 base_url"
    assert cfg.model == CUSTOM_MODEL, "agent loop 应收到用户的自定义 model"


def _fake_agent_factory(token_text, captured):
    """构造 fake build_agent：返回具备 astream_events 的假 agent。

    Task 13 起 chat/generate 委托 deepagents agent loop（astream_chat/astream_generate
    不再走 astream_llm）。这些测试的意图是「自定义配置真正传到 LLM 构造处」——
    build_agent 内部仍调 get_llm → ChatOpenAI，故 patch app.ai.llm_client.ChatOpenAI
    即可捕获构造参数。fake_agent 只负责把 token 流透传，避免触发 check_tool_support
    （假模型 custom-model 不在支持列表）与 MinIO/真实 agent 构造。
    captured：可选 list，收集构造时的 llm_config 以做额外断言。
    """

    class _FakeAgent:
        async def astream_events(self, input_, *, version="v2", config=None):
            chunk = MagicMock()
            chunk.content = token_text
            # MagicMock 自动属性 truthy——usage 捕获/extract_reasoning 路径会把
            # 它们当真值塞进 SSE payload 或 LLMCallLog 后 JSON 序列化炸
            chunk.usage_metadata = None
            chunk.additional_kwargs = {}
            chunk.response_metadata = {}
            yield {"event": "on_chat_model_stream", "data": {"chunk": chunk}}

    async def _build_agent(db, *, llm_config, user_id, section=None, user_input=None, intent=None, **kw):
        if captured is not None:
            captured.append(llm_config)
        return _FakeAgent()

    return _build_agent


# ── SSE 端点：ChatOpenAI 收到自定义配置 ──

def test_chat_uses_user_custom_config_not_env(client, registered_user, db_session):
    """chat 端点：用户配了自定义配置，调 chat 时自定义配置一路传到 build_agent（非 env）。

    Task 13：chat 走 agent loop。断链意图不变——resolve_chat_config 解析出的
    配置传到 build_agent 的 llm_config 形参（build_agent 内部仍 get_llm → ChatOpenAI）。
    本测试 patch build_agent 捕获 llm_config，断言其携带自定义配置值；同时跳过
    check_tool_support（假模型 custom-model 不支持 tool calling）与真实 agent 构造。
    """
    sections = _setup_custom_user(client, registered_user, db_session)
    section = sections[0]

    captured = []
    with patch("app.ai.agent.build_agent", _fake_agent_factory("你好", captured)):
        res = client.post(
            f"/api/v1/sections/{section.id}/chat", json={"message": "测试"},
        )

    assert res.status_code == 200
    assert "event: token" in res.text
    assert "event: done" in res.text
    _assert_custom_llm_config(captured)


def test_generate_uses_user_custom_config_not_env(client, registered_user, db_session):
    """generate 端点：自定义配置传到 build_agent（同 chat，走 agent loop）。"""
    sections = _setup_custom_user(client, registered_user, db_session)
    section = sections[0]

    captured = []
    with patch("app.ai.agent.build_agent", _fake_agent_factory("# 草稿标题", captured)):
        res = client.post(f"/api/v1/sections/{section.id}/generate")

    assert res.status_code == 200
    assert "event: done" in res.text
    _assert_custom_llm_config(captured)


def test_rewrite_uses_user_custom_config_not_env(client, registered_user, db_session):
    """rewrite 端点：ChatOpenAI 收到用户的自定义 key。"""
    sections = _setup_custom_user(client, registered_user, db_session)
    section = sections[0]

    mock_inst = _mock_chat_openai("重写后的文字")
    with patch("app.ai.llm_client.ReasoningChatOpenAI", return_value=mock_inst) as mock_chat:
        res = client.post(f"/api/v1/sections/{section.id}/rewrite", json={
            "selected_text": "原文", "instruction": "更简洁",
        })

    assert res.status_code == 200
    assert "event: done" in res.text
    _assert_custom_kwargs(mock_chat)


def test_caption_figures_uses_user_custom_config_not_env(client, registered_user, db_session):
    """caption_figures 端点（直接调 astream_llm）：ChatOpenAI 收到用户的自定义 key。"""
    sections = _setup_custom_user(client, registered_user, db_session)
    drawings = next(s for s in sections if s.key == "drawings")

    mock_inst = _mock_chat_openai("图 1 是本发明装置示意图。")
    with patch("app.ai.llm_client.ReasoningChatOpenAI", return_value=mock_inst) as mock_chat:
        res = client.post(
            f"/api/v1/sections/{drawings.id}/caption-figures",
            json={"descriptions": ["图1是装置结构图"]},
        )

    assert res.status_code == 200
    assert "event: token" in res.text
    _assert_custom_kwargs(mock_chat)


# ── 无配置：报错事件而非崩溃（阶段 0 strict mode）──

def test_chat_emits_no_llm_config_error_when_unconfigured(client, registered_user, db_session):
    """无自定义配置且全局关闭时：chat 端点发 no_llm_config 错误事件，不崩溃。"""
    ensure_default_template(db_session)
    user = db_session.scalar(select(User).where(User.email == registered_user["email"]))
    p = create_project(db_session, user=user, title="无配置发明")
    sections = list_sections(db_session, user_id=user.id, project_id=str(p.id))
    client.post("/api/v1/auth/login", json={
        "username": registered_user["username"], "password": registered_user["password"],
    })

    # 确认此用户确实无配置（registered_user 不带自定义配置）
    cfg = db_session.scalar(select(UserLLMConfig).where(UserLLMConfig.user_id == user.id))
    assert cfg is None

    res = client.post(f"/api/v1/sections/{sections[0].id}/chat", json={"message": "测试"})
    assert res.status_code == 200
    assert "no_llm_config" in res.text
    assert "未配置 LLM" in res.text
    # 不应走到 done
    assert "event: done" not in res.text


# ── review_service：无配置拒绝执行（ValidationError）──

def test_review_raises_when_no_llm_config(db_session):
    """run_review 在无 LLM 配置时抛 ValidationError（断链修复：审查真依赖配置）。"""
    import pytest
    from app.core.exceptions import ValidationError
    from app.models import Project
    from app.services import review_service

    # 建一个无自定义配置的用户 + 项目
    u = User(username="noreview", email="noreview@test.com", password_hash=hash_password("Pass1234!"), name="t")
    db_session.add(u)
    db_session.commit()
    p = Project(user_id=u.id, title="审查测试")
    db_session.add(p)
    db_session.commit()

    # mock 掉上游依赖（rubric），让流程走到 resolve_chat_config 检查
    # 旧 project-scoped skill 开关已删除（Task 3），review 默认全开
    with patch("app.services.review_service.get_effective_rubric") as gr:
        class FakeRubric:
            criteria = [{"key": "k", "name": "N", "weight": 1.0}]
        gr.return_value = FakeRubric()

        with pytest.raises(ValidationError, match="未配置 LLM"):
            review_service.run_review(db_session, user_id=u.id, project_id=str(p.id))
