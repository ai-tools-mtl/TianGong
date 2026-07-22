# apps/api/tests/test_tool_support.py
"""BYOK tool calling 降级检测（spec Q14-α）。"""
import pytest


def test_check_tool_support_known_supported_model():
    """已知支持 tool calling 的模型（glm-4.7/4.6/4.5/deepseek）放行。"""
    from app.ai.tool_support import check_tool_support
    for m in ["glm-4.7", "glm-4.6", "glm-4.5", "glm-5", "glm-5.1", "glm-5.2",
              "deepseek-chat", "deepseek-r1", "deepseek-v3"]:
        check_tool_support(model=m)  # 不抛异常即放行


def test_check_tool_support_unsupported_model_raises():
    """未知/不支持模型抛 ToolSupportError。"""
    from app.ai.tool_support import check_tool_support, ToolSupportError
    with pytest.raises(ToolSupportError):
        check_tool_support(model="some-old-model-xyz")


def test_check_tool_support_empty_model_raises():
    """空 model 抛 ToolSupportError。"""
    from app.ai.tool_support import check_tool_support, ToolSupportError
    with pytest.raises(ToolSupportError):
        check_tool_support(model="")


def test_check_tool_support_flash_passes():
    """glm-4-flash 支持基础 tool calling，放行。"""
    from app.ai.tool_support import check_tool_support
    check_tool_support(model="glm-4-flash")  # 不抛
    check_tool_support(model="glm-4-air")  # 不抛


def test_check_tool_support_case_insensitive():
    """模型名大小写不敏感。"""
    from app.ai.tool_support import check_tool_support
    check_tool_support(model="GLM-4.7")  # 不抛
    check_tool_support(model="DeepSeek-Chat")  # 不抛
