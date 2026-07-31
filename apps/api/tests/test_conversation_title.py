"""summarize_conversation_title 回归测试（B1：改用轻量任务模型）。

summarize_conversation_title 内部自行 resolve 轻量任务模型配置
（resolve_lite_config）：已配 llm_lite_config → 用轻量模型（典型 GLM-4.7-Flash）；
未配 → 回退 resolve_chat_config；全无 → None，降级为前 20 字。

F1 历史 bug（get_llm 传错参数被 except 吞）已由直接传 ResolvedChatConfig 修复，
本文件延续覆盖：真正调到 get_llm、异常降级、无配置降级三条路径。
"""

from unittest.mock import MagicMock, patch

from app.core.config import get_settings
from app.core.security import encrypt_value
from app.models import SystemSetting
from app.services.conversation_service import summarize_conversation_title


def _seed_lite_config(db_session):
    """写入一份完整的 llm_lite_config（resolve_lite_config 命中轻量分支）。"""
    db_session.add(SystemSetting(
        key="llm_lite_config",
        value={
            "base_url": "https://open.bigmodel.cn/api/paas/v4",
            "api_key_encrypted": encrypt_value("sk-lite-1234567890"),
            "model": "glm-4.7-flash",
        },
    ))
    db_session.commit()


def test_title_calls_llm_when_lite_configured(db_session, monkeypatch):
    """配了 llm_lite_config → resolve 命中轻量分支 → 真正调 get_llm 用其返回值。"""
    monkeypatch.setattr(get_settings(), "glm_api_key", "")  # 锁死 env 兜底
    _seed_lite_config(db_session)
    fake_resp = MagicMock()
    fake_resp.content = "专利交底书撰写"
    conv = MagicMock()  # conversation 对象本身在本函数未被使用（只取首条消息）
    with patch("app.services.conversation_service.get_llm") as m_get:
        m_get.return_value.invoke.return_value = fake_resp
        title = summarize_conversation_title(
            db_session, conv, "帮我写一份关于新型电机的交底书", "好的，这是初稿…",
            user_id="00000000-0000-0000-0000-000000000001",
        )
    m_get.assert_called_once()
    assert title == "专利交底书撰写"


def test_title_fallback_when_no_config(db_session, monkeypatch):
    """无任何配置（lite/chat/env 全无）→ 不调 LLM，直接 fallback（>20 字才截断加省略号）。"""
    monkeypatch.setattr(get_settings(), "glm_api_key", "")  # 锁死 env 兜底
    conv = MagicMock()
    # 输入须 >20 字才会触发截断 + 省略号（恰好 20 字不截断）。
    long_msg = "这是一个很长的用户消息超过二十个字的情况啊"
    assert len(long_msg) > 20
    with patch("app.services.conversation_service.get_llm") as m_get:
        title = summarize_conversation_title(
            db_session, conv, long_msg, "ai 回复",
            user_id="00000000-0000-0000-0000-000000000002",
        )
    m_get.assert_not_called()
    assert title.startswith("这是一个很长的用户消息")
    assert title.endswith("...")


def test_title_fallback_on_llm_error(db_session, monkeypatch):
    """配了 lite config 但 LLM 调用抛异常 → fallback（不崩）。"""
    monkeypatch.setattr(get_settings(), "glm_api_key", "")
    _seed_lite_config(db_session)
    conv = MagicMock()
    with patch("app.services.conversation_service.get_llm") as m_get:
        m_get.return_value.invoke.side_effect = Exception("boom")
        title = summarize_conversation_title(
            db_session, conv, "短消息", "ai 回复",
            user_id="00000000-0000-0000-0000-000000000003",
        )
    assert title == "短消息"
