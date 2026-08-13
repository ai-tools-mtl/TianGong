"""vision 纯函数测试（is_vision_model + build_caption_messages）。"""

import base64

from langchain_core.messages import HumanMessage

from app.ai.vision import build_caption_messages, is_vision_model


def test_is_vision_model_known_vision_models():
    """已知 vision 模型名应识别为 True。"""
    for m in [
        "gpt-4o", "gpt-4o-mini", "gpt-4o-2024-08-06",
        "glm-4v", "glm-4.5v",
        "claude-3-5-sonnet", "claude-3-opus",
        "qwen2.5-vl-72b",
        "moonshot-v1-8k-vision-preview",
        "gemini-1.5-pro",
        "llava-1.5-7b",
        "openai/gpt-4o-mini",  # openrouter 带前缀
    ]:
        assert is_vision_model(m), f"{m} 应识别为 vision"


def test_is_vision_model_non_vision_models():
    """非 vision 模型名应识别为 False（漏判安全，宁可漏不可误判）。"""
    for m in [
        "glm-4-plus", "deepseek-chat", "test-model",
        "", None,
        "moonshot-v1-8k",  # moonshot-v1 纯文本，需 -vision 后缀
        "qwen2.5-7b",
        "gpt-3.5-turbo",
    ]:
        assert not is_vision_model(m), f"{m} 不应识别为 vision"


def test_build_caption_messages_text_fallback():
    """use_vision=False → 纯文字 HumanMessage（与原 caption 行为一致）。"""
    msgs = build_caption_messages(["图1是装置"], [], use_vision=False)
    assert len(msgs) == 2
    human = msgs[1]
    assert isinstance(human, HumanMessage)
    assert isinstance(human.content, str)
    assert "图1是装置" in human.content


def test_build_caption_messages_vision_multimodal():
    """use_vision=True + 图 → 多模态 content list，含 image_url block。"""
    img = (b"\x89PNG\r\n\x1a\n", "image/png")
    msgs = build_caption_messages([], [img], use_vision=True)
    human = msgs[1]
    assert isinstance(human.content, list)
    image_blocks = [c for c in human.content if c.get("type") == "image_url"]
    assert len(image_blocks) == 1
    b64 = base64.b64encode(img[0]).decode("ascii")
    assert image_blocks[0]["image_url"]["url"] == f"data:image/png;base64,{b64}"


def test_build_caption_messages_vision_with_descriptions():
    """use_vision=True + 图 + descriptions → 含 image_url 和文字补充 text block。"""
    img = (b"\x89PNG", "image/png")
    msgs = build_caption_messages(["手绘草图"], [img], use_vision=True)
    human = msgs[1]
    text_blocks = [c for c in human.content if c.get("type") == "text"]
    assert len(text_blocks) >= 2  # 说明 + 补充描述
    assert any("手绘草图" in c["text"] for c in text_blocks)


def test_build_caption_messages_use_vision_but_no_images_falls_back():
    """use_vision=True 但没图 → 仍降级纯文字（不能凭空看图）。"""
    msgs = build_caption_messages(["图1"], [], use_vision=True)
    assert isinstance(msgs[1].content, str)
