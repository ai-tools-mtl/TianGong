"""AI 端点接受 chat_source（不再是 source）。"""

from app.schemas.ai import ChatRequest, GenerateRequest, RewriteRequest


def test_chat_request_accepts_chat_source():
    """ChatRequest schema 接受 chat_source 字段，不接受 source。"""
    req = ChatRequest(message="hi", chat_source="env")
    assert req.chat_source == "env"
    # source 字段应已移除（pydantic 默认 extra=ignore，但显式字段不在 schema）
    assert not hasattr(req, "source") or getattr(req, "source", "UNSET") == "UNSET"


def test_generate_request_accepts_chat_source():
    req = GenerateRequest(chat_source="custom-chat:abc")
    assert req.chat_source == "custom-chat:abc"


def test_rewrite_request_accepts_chat_source():
    req = RewriteRequest(selected_text="x", chat_source="global")
    assert req.chat_source == "global"


def test_caption_request_accepts_chat_source():
    """CaptionRequest 在 ai.py 内联定义，接受 chat_source。"""
    from app.api.ai import CaptionRequest
    req = CaptionRequest(descriptions=["x"], chat_source="env")
    assert req.chat_source == "env"
