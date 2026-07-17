"""端到端断链证明：用户配的 BYOK 配置真正驱动 LLM 调用（而非 env）。

这是阶段 0 的核心交付：证明 resolve_llm_config 解析出的 BYOK 配置
（base_url / api_key / model）真正一路传到 ChatOpenAI/OpenAIEmbeddings 构造处，
而不是被 env 兜底覆盖（即「断链」确实修复）。

测试策略：用 TestClient 走真实 HTTP → FastAPI 路由 → orchestrator → llm_client，
仅在 app.ai.llm_client.ChatOpenAI 层打桩，捕获构造参数，断言用的是用户的 BYOK 值。
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
    本文件内所有「无配置」断言因此稳定；本文件 BYOK 测试不受影响（分支①优先）。
    """
    monkeypatch.setattr(get_settings(), "glm_api_key", "")

BYOK_BASE_URL = "https://byok-fake.example.com"
BYOK_API_KEY = "sk-byok-fake-key-12345"
BYOK_MODEL = "byok-model"
BYOK_EMBED = "byok-embed"


def _setup_byok_user(client, registered_user, db_session):
    """登录 + 建项目 + 给当前用户配 BYOK（假 key/url/model）。返回第一个 section。"""
    ensure_default_template(db_session)
    user = db_session.scalar(select(User).where(User.email == registered_user["email"]))
    # 给用户配 BYOK
    db_session.add(UserLLMConfig(
        user_id=user.id,
        name="test",
        provider="custom",
        base_url=BYOK_BASE_URL,
        api_key_encrypted=encrypt_value(BYOK_API_KEY),
        model=BYOK_MODEL,
        embedding_model=BYOK_EMBED,
        is_active=True,
    ))
    db_session.commit()
    p = create_project(db_session, user=user, title="BYOK 测试发明")
    sections = list_sections(db_session, user_id=user.id, project_id=str(p.id))
    client.post("/api/v1/auth/login", json={
        "username": registered_user["username"], "password": registered_user["password"],
    })
    return sections


def _mock_chat_openai(token_text="hello"):
    """构造 mock 实例（含 async astream / stream / invoke）。

    用法：
        mock_inst, mock_chat = _mock_chat_openai("你好")
        with patch("app.ai.llm_client.ChatOpenAI", return_value=mock_inst) as mock_chat:
            ...
            _assert_byok_kwargs(mock_chat)  # mock_chat.call_args 捕获构造参数
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


def _assert_byok_kwargs(mock_chat):
    """断言 ChatOpenAI 被构造时用的是 BYOK 的值。"""
    assert mock_chat.called, "ChatOpenAI 应被实例化"
    _, kwargs = mock_chat.call_args
    assert kwargs["api_key"] == BYOK_API_KEY, "LLM 应使用用户的 BYOK key，而非 env"
    assert kwargs["base_url"] == BYOK_BASE_URL, "LLM 应使用用户的 BYOK base_url"
    assert kwargs["model"] == BYOK_MODEL, "LLM 应使用用户的 BYOK model"


# ── SSE 端点：ChatOpenAI 收到 BYOK 配置 ──

def test_chat_uses_user_byok_config_not_env(client, registered_user, db_session):
    """chat 端点：用户配了 BYOK，调 chat 时 ChatOpenAI 收到的是用户的假 key（非 env）。"""
    sections = _setup_byok_user(client, registered_user, db_session)
    section = sections[0]

    mock_inst = _mock_chat_openai("你好")
    with patch("app.ai.llm_client.ChatOpenAI", return_value=mock_inst) as mock_chat:
        res = client.post(
            f"/api/v1/sections/{section.id}/chat", json={"message": "测试"},
        )

    assert res.status_code == 200
    assert "event: token" in res.text
    assert "event: done" in res.text
    _assert_byok_kwargs(mock_chat)


def test_generate_uses_user_byok_config_not_env(client, registered_user, db_session):
    """generate 端点：ChatOpenAI 收到用户的 BYOK key。"""
    sections = _setup_byok_user(client, registered_user, db_session)
    section = sections[0]

    mock_inst = _mock_chat_openai("# 草稿标题")
    with patch("app.ai.llm_client.ChatOpenAI", return_value=mock_inst) as mock_chat:
        res = client.post(f"/api/v1/sections/{section.id}/generate")

    assert res.status_code == 200
    assert "event: done" in res.text
    _assert_byok_kwargs(mock_chat)


def test_rewrite_uses_user_byok_config_not_env(client, registered_user, db_session):
    """rewrite 端点：ChatOpenAI 收到用户的 BYOK key。"""
    sections = _setup_byok_user(client, registered_user, db_session)
    section = sections[0]

    mock_inst = _mock_chat_openai("重写后的文字")
    with patch("app.ai.llm_client.ChatOpenAI", return_value=mock_inst) as mock_chat:
        res = client.post(f"/api/v1/sections/{section.id}/rewrite", json={
            "selected_text": "原文", "instruction": "更简洁",
        })

    assert res.status_code == 200
    assert "event: done" in res.text
    _assert_byok_kwargs(mock_chat)


def test_caption_figures_uses_user_byok_config_not_env(client, registered_user, db_session):
    """caption_figures 端点（直接调 astream_llm）：ChatOpenAI 收到用户的 BYOK key。"""
    sections = _setup_byok_user(client, registered_user, db_session)
    drawings = next(s for s in sections if s.key == "drawings")

    mock_inst = _mock_chat_openai("图 1 是本发明装置示意图。")
    with patch("app.ai.llm_client.ChatOpenAI", return_value=mock_inst) as mock_chat:
        res = client.post(
            f"/api/v1/sections/{drawings.id}/caption-figures",
            json={"descriptions": ["图1是装置结构图"]},
        )

    assert res.status_code == 200
    assert "event: token" in res.text
    _assert_byok_kwargs(mock_chat)


# ── 无配置：报错事件而非崩溃（阶段 0 strict mode）──

def test_chat_emits_no_llm_config_error_when_unconfigured(client, registered_user, db_session):
    """无 BYOK 且全局关闭时：chat 端点发 no_llm_config 错误事件，不崩溃。"""
    ensure_default_template(db_session)
    user = db_session.scalar(select(User).where(User.email == registered_user["email"]))
    p = create_project(db_session, user=user, title="无配置发明")
    sections = list_sections(db_session, user_id=user.id, project_id=str(p.id))
    client.post("/api/v1/auth/login", json={
        "username": registered_user["username"], "password": registered_user["password"],
    })

    # 确认此用户确实无配置（registered_user 不带 BYOK）
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

    # 建一个无 BYOK 的用户 + 项目
    u = User(username="noreview", email="noreview@test.com", password_hash=hash_password("Pass1234!"), name="t")
    db_session.add(u)
    db_session.commit()
    p = Project(user_id=u.id, title="审查测试")
    db_session.add(p)
    db_session.commit()

    # mock 掉上游依赖（rubric/skill），让流程走到 resolve_llm_config 检查
    from app.models import AgentSkill
    db_session.add(AgentSkill(project_id=p.id, skill_key="rubric_review", enabled=True))
    db_session.add(AgentSkill(project_id=p.id, skill_key="consistency_check", enabled=False))
    db_session.commit()

    with patch("app.services.review_service.get_effective_rubric") as gr:
        class FakeRubric:
            criteria = [{"key": "k", "name": "N", "weight": 1.0}]
        gr.return_value = FakeRubric()

        with pytest.raises(ValidationError, match="未配置 LLM"):
            review_service.run_review(db_session, user_id=u.id, project_id=str(p.id))
