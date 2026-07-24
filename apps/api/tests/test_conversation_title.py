"""summarize_conversation_title 回归测试（F1：修复 get_llm 调用 bug）。

原 bug：get_llm(**{base_url,api_key,model}) 传错参数（get_llm 期望 ResolvedLLMConfig），
TypeError 被 except Exception 吞掉，标题摘要始终 fallback。
"""

from unittest.mock import MagicMock, patch

from app.services.conversation_service import summarize_conversation_title
from app.services.llm_config_service import ResolvedLLMConfig


def _cfg():
    return ResolvedLLMConfig(
        base_url="https://x.com/v1", api_key="sk-test",
        model="glm-4-flash", embedding_model=None, source="user",
    )


def test_title_calls_llm_when_config_provided(db_session):
    """提供 llm_config → 真正调 get_llm 并用其返回值。"""
    fake_resp = MagicMock()
    fake_resp.content = "专利交底书撰写"
    conv = MagicMock()  # conversation 对象本身在本函数未被使用（只取首条消息）
    with patch("app.services.conversation_service.get_llm") as m_get:
        m_get.return_value.invoke.return_value = fake_resp
        title = summarize_conversation_title(
            db_session, conv, "帮我写一份关于新型电机的交底书", "好的，这是初稿…", llm_config=_cfg(),
        )
    # get_llm 被调用，且传的是 ResolvedLLMConfig（不是 kwargs）
    m_get.assert_called_once()
    arg = m_get.call_args.args[0]
    assert isinstance(arg, ResolvedLLMConfig)
    assert title == "专利交底书撰写"


def test_title_fallback_when_no_config(db_session):
    """llm_config=None → 不调 LLM，直接 fallback（>20 字才截断加省略号）。"""
    conv = MagicMock()
    # 输入须 >20 字才会触发截断 + 省略号（恰好 20 字不截断）。
    long_msg = "这是一个很长的用户消息超过二十个字的情况啊"
    assert len(long_msg) > 20
    with patch("app.services.conversation_service.get_llm") as m_get:
        title = summarize_conversation_title(
            db_session, conv, long_msg, "ai 回复", llm_config=None,
        )
    m_get.assert_not_called()
    assert title.startswith("这是一个很长的用户消息")
    assert title.endswith("...")


def test_title_fallback_on_llm_error(db_session):
    """LLM 调用抛异常 → fallback（不崩）。"""
    conv = MagicMock()
    with patch("app.services.conversation_service.get_llm") as m_get:
        m_get.return_value.invoke.side_effect = Exception("boom")
        title = summarize_conversation_title(
            db_session, conv, "短消息", "ai 回复", llm_config=_cfg(),
        )
    assert title == "短消息"
